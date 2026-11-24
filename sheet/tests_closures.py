"""Port closures (their own page, per port), the delay reason rule's helper and the new Master data lists."""

from datetime import datetime, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .constants import OPTION_KIND_KEYS, is_delayed
from .models import ChangeRecord, Option, PortClosure, Vessel
from .tests import FAST_HASHER, ApiTestCase, allow


def cairo(text):
    """'2026-11-13T08:00' as an aware Cairo datetime."""
    return timezone.make_aware(datetime.fromisoformat(text))


class DelayHelperTests(SimpleTestCase):
    def test_is_delayed(self):
        arrived = cairo("2026-11-13T08:00")
        self.assertFalse(is_delayed(arrived, arrived + timedelta(hours=2)))
        self.assertTrue(is_delayed(arrived, arrived + timedelta(hours=2, minutes=1)))
        self.assertFalse(is_delayed(None, arrived))
        self.assertFalse(is_delayed(arrived, None))

    def test_option_kinds_include_delay_and_closure(self):
        self.assertIn("delay", OPTION_KIND_KEYS)
        self.assertIn("closure", OPTION_KIND_KEYS)


class ClosureModelTests(TestCase):
    def test_closure_saved_with_open_end(self):
        closure = PortClosure.objects.create(port="alexandria", start_at=cairo("2026-11-13T06:00"), reason="WEATHER")
        closure.refresh_from_db()
        self.assertIsNone(closure.end_at)
        self.assertEqual(closure.notes, "")

    def test_closure_changes_are_in_history(self):
        closure = PortClosure.objects.create(port="suez", start_at=cairo("2026-11-13T06:00"), reason="WEATHER")
        closure.reason = "FOG"
        closure.save()
        closure.delete()
        actions = list(
            ChangeRecord.objects.filter(object_type="portclosure").order_by("id").values_list("action", flat=True)
        )
        self.assertEqual(actions, ["create", "update", "delete"])

    def test_vessel_delay_reason_defaults_to_empty(self):
        vessel = Vessel.objects.create(name="X", date=datetime(2026, 11, 13).date())
        self.assertEqual(vessel.delay_reason, "")


@FAST_HASHER
class ClosureApiTests(ApiTestCase):
    def setUp(self):
        allow("closure", "WEATHER")
        self.alex = self.login("alex")

    def post(self, client, **fields):
        payload = {"port": "alexandria", "start_at": "2026-11-13T06:00", "end_at": "2026-11-13T14:00",
                   "reason": "WEATHER", **fields}
        return self.call(client, "post", "/api/closures/", payload)

    def make(self, port, start, end=None, reason="WEATHER"):
        return PortClosure.objects.create(port=port, start_at=cairo(start), end_at=end and cairo(end), reason=reason)

    def listed_ids(self, client, query=""):
        status, data = self.call(client, "get", f"/api/closures/{query}")
        self.assertEqual(status, 200)
        return [c["id"] for c in data["closures"]]

    def test_port_user_creates_closures_in_own_port_only(self):
        self.assertEqual(self.post(self.alex, port="suez")[0], 403)
        status, closure = self.post(self.alex, port="", notes="Strong wind")
        self.assertEqual((status, closure["port"], closure["notes"]), (201, "alexandria", "Strong wind"))

    def test_admin_creates_closure_for_any_port(self):
        status, closure = self.post(self.login("admin"), port="suez")
        self.assertEqual((status, closure["port"], closure["port_label"]), (201, "suez", "Suez"))

    def test_admin_unknown_port_refused(self):
        self.assertEqual(self.post(self.login("admin"), port="atlantis")[0], 400)

    def test_other_ports_closures_cannot_be_changed(self):
        suez = self.login("suezuser")
        closure = self.make("alexandria", "2026-11-11T06:00")
        self.assertEqual(self.call(suez, "put", f"/api/closures/{closure.id}/", {"reason": "WEATHER"})[0], 404)
        self.assertEqual(self.call(suez, "delete", f"/api/closures/{closure.id}/")[0], 404)
        self.assertTrue(PortClosure.objects.filter(pk=closure.pk).exists())

    def test_port_user_cannot_see_or_edit_other_port(self):
        suez = self.make("suez", "2026-11-13T06:00")
        self.assertEqual(self.listed_ids(self.alex, "?port=suez"), [])
        payload = {"start_at": "2026-11-13T06:00", "reason": "WEATHER"}
        self.assertEqual(self.call(self.alex, "put", f"/api/closures/{suez.id}/", payload)[0], 404)
        self.assertEqual(self.call(self.alex, "delete", f"/api/closures/{suez.id}/")[0], 404)
        self.assertTrue(PortClosure.objects.filter(pk=suez.pk).exists())

    def test_reason_required_and_listed(self):
        self.assertEqual(self.post(self.alex, reason=""), (400, {"error": "Choose a closure reason."}))
        self.assertEqual(self.post(self.alex, reason="NOPE")[0], 400)
        allow("closure", "SUEZ ONLY", port="suez")
        self.assertEqual(self.post(self.alex, reason="SUEZ ONLY")[0], 400)

    def test_reopened_before_closed_refused(self):
        self.assertEqual(self.post(self.alex, end_at="2026-11-13T05:00"),
                         (400, {"error": "Reopened cannot be before closed from."}))

    def test_start_required(self):
        self.assertEqual(self.post(self.alex, start_at=""), (400, {"error": "Closed from is required."}))

    def test_bad_time_refused(self):
        self.assertEqual(self.post(self.alex, end_at="tomorrow")[0], 400)

    def test_notes_too_long_refused(self):
        self.assertEqual(self.post(self.alex, notes="x" * 501)[0], 400)

    def test_range_overlap_filter(self):
        closure = self.make("alexandria", "2026-11-10T06:00", "2026-11-12T06:00")
        self.assertEqual(self.listed_ids(self.alex, "?from=2026-11-12&to=2026-11-30"), [closure.id])
        self.assertEqual(self.listed_ids(self.alex, "?from=2026-11-13&to=2026-11-30"), [])
        self.assertEqual(self.listed_ids(self.alex, "?from=2026-11-01&to=2026-11-10"), [closure.id])
        self.assertEqual(self.listed_ids(self.alex, "?from=2026-11-01&to=2026-11-09"), [])

    def test_open_closure_overlaps_any_later_range(self):
        closure = self.make("alexandria", "2026-11-10T06:00")
        self.assertEqual(self.listed_ids(self.alex, "?from=2027-03-01&to=2027-03-31"), [closure.id])

    def test_bad_range_refused(self):
        self.assertEqual(self.call(self.alex, "get", "/api/closures/?from=2026-11-30&to=2026-11-01")[0], 400)

    def test_hours_and_local_times_in_json(self):
        _, closure = self.post(self.alex)
        self.assertEqual((closure["start_at"], closure["end_at"], closure["hours"]),
                         ("2026-11-13T06:00", "2026-11-13T14:00", 8.0))
        self.assertTrue(closure["can_edit"])
        _, still = self.post(self.alex, end_at="")
        self.assertEqual((still["end_at"], still["hours"]), (None, None))

    def test_edit_and_delete_recorded_in_history(self):
        _, closure = self.post(self.alex)
        allow("closure", "FOG")
        status, edited = self.call(self.alex, "put", f"/api/closures/{closure['id']}/",
                                   {**closure, "reason": "FOG"})
        self.assertEqual((status, edited["reason"], edited["port"]), (200, "FOG", "alexandria"))
        self.assertEqual(self.call(self.alex, "delete", f"/api/closures/{closure['id']}/")[0], 200)
        actions = ChangeRecord.objects.filter(object_type="portclosure", object_id=closure["id"])
        self.assertEqual(sorted(actions.values_list("action", flat=True)), ["create", "delete", "update"])
        self.assertEqual(actions.get(action="create").username, "alex")

    def test_saved_reason_kept_when_list_value_removed(self):
        _, closure = self.post(self.alex)
        Option.objects.filter(kind="closure").delete()
        self.assertEqual(self.call(self.alex, "put", f"/api/closures/{closure['id']}/", closure)[0], 200)


@FAST_HASHER
class ClosurePageTests(ApiTestCase):
    def test_page_has_closures_nav_and_page(self):
        page = self.login("alex").get("/").content.decode()
        self.assertIn('data-page="closures"', page)
        self.assertIn('id="page-closures"', page)
        self.assertIn('data-act="closure-new"', page)

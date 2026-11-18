"""Delay reason: required when a vessel berthed more than 2 hours after it arrived, refused otherwise."""

from .models import Option, Vessel
from .tests import ApiTestCase, allow

NEEDS_REASON = "Choose a delay reason (berthed more than 2 hours after arrival)."
NOT_DELAYED = "Not delayed (berthed within 2 hours): clear the delay reason."


class DelayReasonTests(ApiTestCase):
    def setUp(self):
        allow("delay", "WEATHER")
        self.alex = self.login("alex")

    def create(self, berthing, **extra):
        payload = {"name": "LATE", "date": "2026-11-13", "arrival_at": "2026-11-13T08:00", "berthing_at": berthing}
        return self.call(self.alex, "post", "/api/vessels/", {**payload, **extra})

    def test_delayed_vessel_without_reason_refused(self):
        self.assertEqual(self.create("2026-11-13T10:01"), (400, {"error": NEEDS_REASON}))

    def test_exactly_two_hours_is_not_delayed(self):
        status, vessel = self.create("2026-11-13T10:00")
        self.assertEqual((status, vessel["delay_reason"]), (201, ""))

    def test_delayed_vessel_with_listed_reason_saved(self):
        status, vessel = self.create("2026-11-13T10:01", delay_reason="WEATHER")
        self.assertEqual((status, vessel["delay_reason"]), (201, "WEATHER"))

    def test_unlisted_delay_reason_refused(self):
        self.assertEqual(self.create("2026-11-13T11:00", delay_reason="NOPE")[0], 400)

    def test_delay_reason_from_other_port_refused(self):
        allow("delay", "SUEZ ONLY", port="suez")
        self.assertEqual(self.create("2026-11-13T11:00", delay_reason="SUEZ ONLY")[0], 400)

    def test_reason_when_not_delayed_refused(self):
        self.assertEqual(self.create("2026-11-13T09:00", delay_reason="WEATHER"), (400, {"error": NOT_DELAYED}))

    def test_no_times_and_no_reason_is_fine(self):
        status, _ = self.call(self.alex, "post", "/api/vessels/", {"name": "PLAIN", "date": "2026-11-13"})
        self.assertEqual(status, 201)

    def test_saved_reason_kept_when_list_value_removed(self):
        _, vessel = self.create("2026-11-13T11:00", delay_reason="WEATHER")
        Option.objects.filter(kind="delay", value="WEATHER").delete()
        payload = {**vessel, "delay_reason": "WEATHER"}
        status, saved = self.call(self.alex, "put", f"/api/vessels/{vessel['id']}/", payload)
        self.assertEqual((status, saved["delay_reason"]), (200, "WEATHER"))

    def test_absent_key_keeps_stored_reason(self):
        _, vessel = self.create("2026-11-13T11:00", delay_reason="WEATHER")
        payload = {key: vessel[key] for key in ("name", "date", "arrival_at", "berthing_at")}
        status, saved = self.call(self.alex, "put", f"/api/vessels/{vessel['id']}/", payload)
        self.assertEqual((status, saved["delay_reason"]), (200, "WEATHER"))

    def test_old_delayed_vessel_needs_reason_on_edit(self):
        _, vessel = self.create("2026-11-13T10:00")
        stored = Vessel.objects.get(pk=vessel["id"])
        Vessel.objects.filter(pk=stored.pk).update(berthing_at=stored.arrival_at.replace(hour=stored.arrival_at.hour + 4))
        payload = {"name": "RENAMED", "date": "2026-11-13", "arrival_at": "2026-11-13T08:00",
                   "berthing_at": "2026-11-13T12:00"}
        self.assertEqual(self.call(self.alex, "put", f"/api/vessels/{vessel['id']}/", payload), (400, {"error": NEEDS_REASON}))

    def test_csv_has_delay_reason_column(self):
        self.create("2026-11-13T11:00", delay_reason="WEATHER")
        text = self.alex.get("/export.csv?from=2026-11-01&to=2026-11-30").content.decode("utf-8-sig")
        header, *rows = text.splitlines()
        columns = header.split(",")
        self.assertIn("Delay reason", columns)
        self.assertEqual(columns.index("Delay reason"), columns.index("Sailed") + 1)
        late = next(r.split(",") for r in rows if r.startswith("LATE"))
        self.assertEqual(late[columns.index("Delay reason")], "WEATHER")

    def test_search_matches_delay_reason(self):
        self.create("2026-11-13T11:00", delay_reason="WEATHER")
        _, data = self.call(self.alex, "get", "/api/vessels/?q=weather&from=2026-11-01&to=2026-11-30")
        self.assertEqual([v["name"] for v in data["vessels"]], ["LATE"])

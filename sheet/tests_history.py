"""Change history (A09, A08): every create / update / delete is recorded with who, when, where and old → new."""

from datetime import date
from unittest import mock

from django.db import DatabaseError
from django.test import TestCase

from .models import ChangeRecord, Guest, HotelStay, Option, Service, Vessel
from .tests import FAST_HASHER, ApiTestCase


def records(**filters):
    return list(ChangeRecord.objects.filter(**filters).order_by("id"))


@FAST_HASHER
class HistoryRecordingTests(ApiTestCase):
    def test_create_update_delete_through_the_api_make_one_record_each(self):
        alex = self.login("alex")
        status, vessel = self.call(alex, "post", "/api/vessels/", {"name": "HIST", "date": "2026-11-13"})
        self.assertEqual(status, 201)
        created = records(object_type="vessel", object_id=vessel["id"])
        self.assertEqual([r.action for r in created], ["create"])
        record = created[0]
        self.assertEqual((record.username, record.user.username, record.port), ("alex", "alex", "alexandria"))
        self.assertEqual(record.ip, "127.0.0.1")
        self.assertEqual(record.changes["name"], [None, "HIST"])

        self.call(alex, "put", f"/api/vessels/{vessel['id']}/", {"name": "HIST 2", "date": "2026-11-13"})
        update = records(object_type="vessel", object_id=vessel["id"], action="update")
        self.assertEqual(len(update), 1)
        self.assertEqual(update[0].changes, {"name": ["HIST", "HIST 2"]})

        self.call(alex, "delete", f"/api/vessels/{vessel['id']}/")
        deleted = records(object_type="vessel", object_id=vessel["id"], action="delete")
        self.assertEqual(len(deleted), 1)
        self.assertEqual(deleted[0].changes["name"], ["HIST 2", None])

    def test_an_update_that_changes_nothing_records_nothing(self):
        alex = self.login("alex")
        _, vessel = self.call(alex, "post", "/api/vessels/", {"name": "SAME", "date": "2026-11-13"})
        self.call(alex, "put", f"/api/vessels/{vessel['id']}/", {"name": "SAME", "date": "2026-11-13"})
        self.assertEqual(records(object_type="vessel", object_id=vessel["id"], action="update"), [])

    def test_deleting_a_vessel_records_every_deleted_child(self):
        vessel = Vessel.objects.create(name="PARENT", date=date(2026, 11, 13), port="alexandria")
        services = [Service.objects.create(vessel=vessel, service_type="Fresh Water", data={}) for _ in range(2)]
        stay = HotelStay.objects.create(vessel=vessel, hotel="H", check_in=date(2026, 11, 13), nights=1)
        guest = Guest.objects.create(stay=stay, name="GUEST")
        self.call(self.login("alex"), "delete", f"/api/vessels/{vessel.id}/")
        deleted = {(r.object_type, r.object_id) for r in records(action="delete")}
        expected = {("vessel", vessel.id), ("hotelstay", stay.id), ("guest", guest.id)}
        expected |= {("service", s.id) for s in services}
        self.assertEqual(deleted, expected)
        self.assertTrue(all(r.username == "alex" for r in records(action="delete")))
        self.assertEqual({r.port for r in records(action="delete")}, {"alexandria"})

    def test_bulk_add_records_each_vessel(self):
        rows = [{"name": f"BULK {i}", "date": "2026-11-13"} for i in range(3)]
        status, data = self.call(self.login("alex"), "post", "/api/vessels/bulk/", {"rows": rows})
        self.assertEqual(status, 201)
        created = records(object_type="vessel", action="create", username="alex")
        self.assertEqual(sorted(r.object_id for r in created), sorted(v["id"] for v in data["vessels"]))
        self.assertEqual({r.port for r in created}, {"alexandria"})

    def test_booking_guests_are_recorded(self):
        alex = self.login("alex")
        payload = {
            "vessel": self.alex_vessel.id, "hotel": "NILE", "check_in": "2026-11-13", "nights": 2,
            "guests": [{"name": "A ONE"}, {"name": "B TWO"}],
        }
        status, _ = self.call(alex, "post", "/api/hotels/", payload)
        self.assertEqual(status, 201)
        self.assertEqual(len(records(object_type="hotelstay", action="create")), 1)
        self.assertEqual(len(records(object_type="guest", action="create")), 2)

    def test_master_data_and_rates_are_recorded(self):
        admin = self.login("admin")
        self.call(admin, "post", "/api/options/", {"kind": "opr", "value": "NEWOPR"})
        self.call(admin, "post", "/api/rates/", {"month": "2026-11", "rate": "50"})
        self.assertEqual(len(records(object_type="option", action="create")), 1)
        self.assertEqual(len(records(object_type="exchangerate", action="create")), 1)

    def test_a_change_without_a_request_is_recorded_as_system(self):
        Option.objects.create(kind="opr", value="ORM")
        record = records(object_type="option")[-1]
        self.assertEqual((record.username, record.user, record.ip), ("system", None, ""))

    def test_a_failing_history_write_rolls_the_change_back(self):
        alex = self.login("alex")
        with (
            mock.patch("sheet.history.ChangeRecord.objects.create", side_effect=DatabaseError("history is gone")),
            self.assertLogs("sheet.security", level="ERROR"),
            self.assertLogs("django.request", level="ERROR"),
        ):
            status, data = self.call(
                alex, "put", f"/api/vessels/{self.alex_vessel.id}/", {"name": "CHANGED", "date": "2026-11-13"}
            )
        self.assertEqual(status, 500)
        self.assertIn("ref", data)
        self.alex_vessel.refresh_from_db()
        self.assertEqual(self.alex_vessel.name, "ALEX SHIP")


class HistoryIsAppendOnlyTests(TestCase):
    def test_admin_cannot_add_change_or_delete_records(self):
        from django.contrib import admin

        model_admin = admin.site._registry[ChangeRecord]
        request = mock.Mock()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))


@FAST_HASHER
class HistoryApiTests(ApiTestCase):
    def test_only_admins_may_read_the_history(self):
        self.assertEqual(self.login("admin").get("/api/history/").status_code, 200)
        self.assertEqual(self.login("alex").get("/api/history/").status_code, 403)
        self.assertEqual(self.login("viewer").get("/api/history/").status_code, 403)

    def test_records_are_newest_first_and_paged(self):
        for i in range(3):
            Option.objects.create(kind="opr", value=f"O{i}")
        data = self.login("admin").get("/api/history/?page_size=10").json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["count"], ChangeRecord.objects.count())
        ids = [r["id"] for r in data["records"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        first = data["records"][0]
        for key in ("at", "username", "ip", "action", "object_type", "object_id", "port", "changes"):
            self.assertIn(key, first)

    def test_filters_by_type_user_and_date(self):
        admin = self.login("admin")
        Option.objects.create(kind="opr", value="BYTYPE")
        self.call(self.login("alex"), "post", "/api/vessels/", {"name": "BYUSER", "date": "2026-11-13"})
        by_type = admin.get("/api/history/?type=option").json()["records"]
        self.assertTrue(by_type and all(r["object_type"] == "option" for r in by_type))
        by_user = admin.get("/api/history/?user=alex").json()["records"]
        self.assertTrue(by_user and all(r["username"] == "alex" for r in by_user))
        self.assertEqual(admin.get("/api/history/?from=2000-01-01&to=2000-01-31").json()["count"], 0)
        today = ChangeRecord.objects.latest("id").at.astimezone().date().isoformat()
        self.assertGreater(admin.get(f"/api/history/?from={today}&to={today}").json()["count"], 0)

    def test_bad_filters_are_a_400(self):
        admin = self.login("admin")
        self.assertEqual(admin.get("/api/history/?from=nope").status_code, 400)
        self.assertEqual(admin.get("/api/history/?page=0").status_code, 400)
        self.assertEqual(admin.get("/api/history/?page_size=7").status_code, 400)

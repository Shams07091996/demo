"""The vessel list: name + fixed LOA, shared by all ports. Read with Vessel Data; add / edit with "Edit terminals and
vessel list"; delete for Admins only. Deleting never changes a visit."""

from sheet.constants import PERMISSION_KEYS
from sheet.models import ChangeRecord
from sheet.tests import ApiTestCase, make_user

from .models import ListedVessel, Visit
from .tests_models import cairo, terminal

URL = "/api/operation/vessels/"


class VesselListTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_user("nomaster", "alexandria", permissions=[k for k in PERMISSION_KEYS if k != "operation.master"])
        make_user("liveonly", "alexandria", permissions=[], pages=["op_live"])
        cls.roza = ListedVessel.objects.create(name="ROZA", loa="199.9")
        ListedVessel.objects.create(name="ALLEGRI", loa="300")

    def test_list_sorted_by_name_and_searched(self):
        status, body = self.call(self.login("nomaster"), "get", URL)
        self.assertEqual(status, 200)
        self.assertEqual([(v["name"], v["loa"]) for v in body["vessels"]], [("ALLEGRI", 300.0), ("ROZA", 199.9)])
        _, body = self.call(self.login("nomaster"), "get", URL + "?q=oz")
        self.assertEqual([v["name"] for v in body["vessels"]], ["ROZA"])

    def test_without_vessel_data_page_is_403(self):
        self.assertEqual(self.call(self.login("liveonly"), "get", URL)[0], 403)

    def test_tick_adds_and_edits(self):
        alex = self.login("alex")
        status, body = self.call(alex, "post", URL, {"name": " cape orion ", "loa": "294.1"})
        self.assertEqual((status, body["name"], body["loa"]), (201, "CAPE ORION", 294.1))
        status, body = self.call(alex, "put", f"{URL}{self.roza.id}/", {"name": "ROZA", "loa": 210})
        self.assertEqual((status, body["loa"]), (200, 210.0))
        self.assertTrue(ChangeRecord.objects.filter(object_type="listedvessel", object_id=self.roza.id).exists())

    def test_without_tick_cannot_write(self):
        user = self.login("nomaster")
        self.assertEqual(self.call(user, "post", URL, {"name": "NEW", "loa": 100})[0], 403)
        self.assertEqual(self.call(user, "put", f"{URL}{self.roza.id}/", {"name": "ROZA", "loa": 100})[0], 403)

    def test_bad_values_refused(self):
        alex = self.login("alex")
        cases = [
            ({"name": " ", "loa": 100}, "Enter the vessel name."),
            ({"name": "X" * 101, "loa": 100}, "Vessel name is too long (at most 100 characters)."),
            ({"name": "roza", "loa": 100}, "That vessel is already on the list."),
            ({"name": "NEW", "loa": ""}, "Enter the LOA."),
            ({"name": "NEW", "loa": 0}, "LOA must be more than 0 and at most 500 m."),
            ({"name": "NEW", "loa": 501}, "LOA must be more than 0 and at most 500 m."),
        ]
        for payload, message in cases:
            status, body = self.call(alex, "post", URL, payload)
            self.assertEqual((status, body["error"]), (400, message), payload)

    def test_only_admins_delete_and_visits_stay(self):
        visit = Visit.objects.create(terminal=terminal(), vessel_name="ROZA", shipping_line="ARKAS", loa="199.9",
                                     eta=cairo("2026-11-21T08:00"))
        self.assertEqual(self.call(self.login("alex"), "delete", f"{URL}{self.roza.id}/")[0], 403)
        self.assertEqual(self.call(self.login("admin"), "delete", f"{URL}{self.roza.id}/")[0], 200)
        self.assertFalse(ListedVessel.objects.filter(pk=self.roza.id).exists())
        visit.refresh_from_db()
        self.assertEqual((visit.vessel_name, float(visit.loa)), ("ROZA", 199.9))

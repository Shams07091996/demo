"""Ships (name, IMO, OPR, customer): the ships API, the IMO check, and vessels linked to ships."""

import json
from datetime import date

from django.test import SimpleTestCase

from .models import ChangeRecord, Customer, Ship, Vessel
from .tests import NEEDED, ApiTestCase, allow
from .validators import imo_valid

AURORA = {"name": "msc aurora", "imo": "9074729", "opr": NEEDED["opr"]}


class ImoTests(SimpleTestCase):
    def test_imo_check_digit(self):
        self.assertTrue(imo_valid("9074729"))
        for bad in ("9074728", "907472", "90747290", "9O74729", "", None, 9074729):
            self.assertFalse(imo_valid(bad), bad)


class ShipApiTests(ApiTestCase):
    def test_port_user_creates_ship(self):
        status, ship = self.call(self.login("alex"), "post", "/api/ships/", AURORA)
        self.assertEqual(status, 201, ship)
        self.assertEqual((ship["name"], ship["imo"], ship["opr"], ship["customer"], ship["calls"], ship["active"]),
                         ("MSC AURORA", "9074729", NEEDED["opr"], None, 0, True))
        self.assertTrue(ChangeRecord.objects.filter(object_type="ship", object_id=ship["id"]).exists())

    def test_imo_required_unique_and_checked(self):
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "post", "/api/ships/", {**AURORA, "imo": ""})[0], 400)
        self.assertEqual(self.call(alex, "post", "/api/ships/", {**AURORA, "imo": "9074728"})[0], 400)
        self.assertEqual(self.call(alex, "post", "/api/ships/", AURORA)[0], 201)
        status, body = self.call(alex, "post", "/api/ships/", {**AURORA, "name": "OTHER"})
        self.assertEqual(status, 400)
        self.assertIn("IMO", body["error"])

    def test_no_imo_ships_do_not_clash(self):
        alex = self.login("alex")
        for name in ("TUG ONE", "TUG TWO"):
            status, ship = self.call(alex, "post", "/api/ships/",
                                     {"name": name, "imo": "9074729", "no_imo": True, "opr": NEEDED["opr"]})
            self.assertEqual(status, 201, ship)
            self.assertEqual(ship["imo"], "")
        self.assertEqual(self.call(alex, "post", "/api/ships/", AURORA)[0], 201)  # a real IMO is still free

    def test_opr_must_be_listed(self):
        allow("opr", "SUEZ ONLY", port="suez")
        self.assertEqual(self.call(self.login("alex"), "post", "/api/ships/", {**AURORA, "opr": "SUEZ ONLY"})[0], 400)
        self.assertEqual(self.call(self.login("alex"), "post", "/api/ships/", {**AURORA, "opr": "NOT LISTED"})[0], 400)
        self.assertEqual(self.call(self.login("admin"), "post", "/api/ships/", {**AURORA, "opr": "SUEZ ONLY"})[0], 201)

    def test_users_read_every_ship(self):
        Ship.objects.create(name="MSC AURORA", imo="9074729")
        status, body = self.call(self.login("suezuser"), "get", "/api/ships/")
        self.assertEqual((status, [s["name"] for s in body["ships"]]), (200, ["MSC AURORA", "TEST SHIP"]))

    def test_search_and_active_filter(self):
        Ship.objects.create(name="MSC AURORA", imo="9074729")
        Ship.objects.create(name="OLD BOAT", imo="", active=False)
        Ship.objects.create(name="A%B.C", imo="")
        alex = self.login("alex")
        names = lambda query: [s["name"] for s in self.call(alex, "get", f"/api/ships/?{query}")[1]["ships"]]  # noqa: E731
        self.assertEqual(names("q=aur"), ["MSC AURORA"])
        self.assertEqual(names("q=907472"), ["MSC AURORA"])
        self.assertEqual(names("q=%25"), ["A%B.C"])
        self.assertEqual(names("q=."), ["A%B.C"])
        self.assertEqual(names("q=boat"), ["OLD BOAT"])
        self.assertEqual(names("q=boat&active=1"), [])
        self.assertEqual(len(names("limit=1")), 1)

    def test_update_ship(self):
        ship = Ship.objects.create(name="MSC AURORA", imo="9074729", opr=NEEDED["opr"])
        status, body = self.call(self.login("alex"), "put", f"/api/ships/{ship.id}/", {**AURORA, "active": False})
        self.assertEqual((status, body["active"]), (200, False))

    def test_customer_on_ship(self):
        customer = Customer.objects.create(name="Blue Owners")
        Customer.objects.create(name="Gone", active=False)
        alex = self.login("alex")
        status, ship = self.call(alex, "post", "/api/ships/", {**AURORA, "customer": customer.id})
        self.assertEqual((status, ship["customer"]), (201, {"id": customer.id, "name": "Blue Owners"}))
        gone = Customer.objects.get(name="Gone")
        self.assertEqual(self.call(alex, "post", "/api/ships/", {**AURORA, "imo": "", "no_imo": True,
                                                                 "customer": gone.id})[0], 400)
        self.assertEqual(self.call(alex, "post", "/api/ships/", {**AURORA, "imo": "", "no_imo": True,
                                                                 "customer": 999999})[0], 400)

    def test_delete_admin_only_and_refused_in_use(self):
        unused = Ship.objects.create(name="UNUSED", imo="")
        used = Ship.objects.create(name="USED", imo="9074729")
        Vessel.objects.create(name="USED", date=date(2026, 11, 13), port="alexandria", ship=used)
        self.assertEqual(self.call(self.login("alex"), "delete", f"/api/ships/{unused.id}/")[0], 403)
        admin = self.login("admin")
        self.assertEqual(self.call(admin, "delete", f"/api/ships/{unused.id}/")[0], 200)
        status, body = self.call(admin, "delete", f"/api/ships/{used.id}/")
        self.assertEqual((status, body["error"]), (400, "In use: mark it inactive instead."))
        self.assertEqual(self.call(self.login("viewer"), "get", "/api/ships/?q=used")[1]["ships"][0]["calls"], 1)


class VesselShipTests(ApiTestCase):
    def raw_post(self, client, payload):
        """A vessel POST without the test helper's automatic ship."""
        response = client.post("/api/vessels/", data=json.dumps(payload), content_type="application/json",
                               HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        return response.status_code, response.json()

    def test_new_vessel_needs_ship(self):
        status, body = self.raw_post(self.login("alex"), {**NEEDED, "name": "NEW", "date": "2026-11-13"})
        self.assertEqual((status, body["error"]), (400, "Choose a ship, or add a new one."))

    def test_ship_links_and_is_returned(self):
        customer = Customer.objects.create(name="Blue Owners")
        ship = Ship.objects.create(name="MSC AURORA", imo="9074729", opr=NEEDED["opr"], customer=customer)
        alex = self.login("alex")
        status, vessel = self.call(alex, "post", "/api/vessels/",
                                   {**NEEDED, "name": "MSC AURORA", "date": "2026-11-13", "ship_id": ship.id})
        self.assertEqual(status, 201, vessel)
        expected = {"id": ship.id, "name": "MSC AURORA", "imo": "9074729", "customer_id": customer.id}
        self.assertEqual(vessel["ship"], expected)
        self.assertEqual(self.call(alex, "get", f"/api/vessels/{vessel['id']}/")[1]["ship"], expected)

    def test_ship_opr_allowed_even_if_unlisted_for_port(self):
        allow("opr", "SUEZ ONLY", port="suez")
        ship = Ship.objects.create(name="SUEZ LINER", imo="9074729", opr="SUEZ ONLY")
        status, vessel = self.call(self.login("alex"), "post", "/api/vessels/",
                                   {**NEEDED, "opr": "SUEZ ONLY", "name": "SUEZ LINER", "date": "2026-11-13",
                                    "ship_id": ship.id})
        self.assertEqual((status, vessel.get("opr")), (201, "SUEZ ONLY"))

    def test_unknown_or_inactive_ship_refused(self):
        gone = Ship.objects.create(name="GONE", imo="", active=False)
        alex = self.login("alex")
        for ship_id in (999999, gone.id, "1", True):
            status, _ = self.call(alex, "post", "/api/vessels/",
                                  {**NEEDED, "name": "X", "date": "2026-11-13", "ship_id": ship_id})
            self.assertEqual(status, 400, ship_id)

    def test_old_vessel_without_ship_still_saves_but_link_cannot_be_removed(self):
        alex = self.login("alex")
        url = f"/api/vessels/{self.alex_vessel.id}/"
        base = {**NEEDED, "name": "ALEX SHIP", "date": "2026-11-13"}
        self.assertEqual(self.call(alex, "put", url, base)[0], 200)
        ship = Ship.objects.create(name="ALEX SHIP", imo="9074729")
        self.assertEqual(self.call(alex, "put", url, {**base, "ship_id": ship.id})[0], 200)
        self.assertEqual(self.call(alex, "put", url, {**base, "ship_id": None})[0], 400)
        self.assertEqual(self.call(alex, "put", url, base)[0], 200)  # no key: keeps the ship
        self.alex_vessel.refresh_from_db()
        self.assertEqual(self.alex_vessel.ship_id, ship.id)
        ship.active = False
        ship.save()
        self.assertEqual(self.call(alex, "put", url, {**base, "ship_id": ship.id})[0], 200)  # its saved ship

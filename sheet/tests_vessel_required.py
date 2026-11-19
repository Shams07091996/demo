"""OPR and POC are required for a new vessel and can't be emptied once set (older vessels without them still save)."""

from .models import Vessel
from .tests import ApiTestCase, allow


class RequiredOprPocTests(ApiTestCase):
    def setUp(self):
        allow("opr", "ARK")
        allow("poc", "ALY")
        self.alex = self.login("alex")

    def create(self, **fields):
        return self.call(self.alex, "post", "/api/vessels/", {"name": "NEW", "date": "2026-11-13", **fields})

    def test_new_vessel_without_opr_refused(self):
        self.assertEqual(self.create(poc="ALY"), (400, {"error": "Choose an OPR."}))

    def test_new_vessel_without_poc_refused(self):
        self.assertEqual(self.create(opr="ARK"), (400, {"error": "Choose a POC."}))

    def test_new_vessel_with_both_saved(self):
        status, vessel = self.create(opr="ARK", poc="ALY")
        self.assertEqual((status, vessel["opr"], vessel["poc"]), (201, "ARK", "ALY"))

    def test_set_value_cannot_be_emptied(self):
        vessel = Vessel.objects.create(name="SET", date="2026-11-13", port="alexandria", opr="ARK", poc="ALY")
        status, data = self.call(self.alex, "put", f"/api/vessels/{vessel.id}/",
                                 {"name": "SET", "date": "2026-11-13", "opr": "", "poc": "ALY"})
        self.assertEqual((status, data), (400, {"error": "Choose an OPR."}))

    def test_admin_must_choose_the_port_of_a_new_vessel(self):
        admin = self.login("admin")
        new = {"name": "NEW", "date": "2026-11-13", "opr": "ARK", "poc": "ALY"}
        self.assertEqual(self.call(admin, "post", "/api/vessels/", new), (400, {"error": "Choose a port."}))
        status, vessel = self.call(admin, "post", "/api/vessels/", {**new, "port": "suez"})
        self.assertEqual((status, vessel["port"]), (201, "suez"))
        # An edit without a port keeps the vessel's port; a port user never sends one.
        status, vessel = self.call(admin, "put", f"/api/vessels/{vessel['id']}/", {**new, "name": "KEPT"})
        self.assertEqual((status, vessel["port"]), (200, "suez"))
        self.assertEqual(self.create(opr="ARK", poc="ALY")[0], 201)

    def test_older_vessel_without_them_still_saves(self):
        status, _ = self.call(self.alex, "put", f"/api/vessels/{self.alex_vessel.id}/",
                              {"name": "ALEX SHIP", "date": "2026-11-13"})
        self.assertEqual(status, 200)

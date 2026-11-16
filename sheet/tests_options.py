"""Master data per port: admins choose the port of a value and can move it later."""

from .models import Option
from .tests import ApiTestCase


class OptionPortTests(ApiTestCase):
    def test_admin_adds_for_a_port_and_moves_a_value(self):
        admin = self.login("admin")
        _, data = self.call(admin, "post", "/api/options/", {"kind": "agent", "value": "NILE", "port": "suez"})
        nile = next(o for o in data["options"] if o["value"] == "NILE")
        self.assertEqual(nile["port"], "suez")
        status, data = self.call(admin, "patch", f"/api/options/{nile['id']}/", {"port": ""})
        self.assertEqual((status, next(o for o in data["options"] if o["id"] == nile["id"])["port"]), (200, ""))
        status, data = self.call(admin, "patch", f"/api/options/{nile['id']}/", {"port": "damietta"})
        self.assertEqual(Option.objects.get(pk=nile["id"]).port, "damietta")

    def test_only_admins_move_values_and_ports_are_checked(self):
        option = Option.objects.create(kind="agent", value="X", port="alexandria")
        self.assertEqual(self.call(self.login("alex"), "patch", f"/api/options/{option.id}/", {"port": ""})[0], 403)
        self.assertEqual(self.call(self.login("viewer"), "patch", f"/api/options/{option.id}/", {"port": ""})[0], 403)
        self.assertEqual(self.call(self.login("admin"), "patch", f"/api/options/{option.id}/", {"port": "mars"})[0], 400)
        Option.objects.create(kind="agent", value="X", port="")
        status, data = self.call(self.login("admin"), "patch", f"/api/options/{option.id}/", {"port": ""})
        self.assertEqual((status, data["error"]), (400, "That value already exists for that port."))
        self.assertEqual(Option.objects.get(pk=option.id).port, "alexandria")

    def test_port_users_still_add_to_their_own_port_only(self):
        _, data = self.call(self.login("alex"), "post", "/api/options/", {"kind": "agent", "value": "LOCAL", "port": "suez"})
        self.assertEqual(next(o for o in data["options"] if o["value"] == "LOCAL")["port"], "alexandria")

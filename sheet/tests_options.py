"""Master data per port: admins choose the port of a value and can move it later."""

from django.utils import timezone

from .models import Option, PortClosure, Vessel
from .tests import ApiTestCase, allow


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


class ReasonListTests(ApiTestCase):
    def used(self, client, kind, value):
        _, data = self.call(client, "get", "/api/options/")
        return next(o["used"] for o in data["options"] if o["kind"] == kind and o["value"] == value)

    def test_delay_and_closure_values_can_be_added(self):
        alex = self.login("alex")
        for kind in ("delay", "closure"):
            status, data = self.call(alex, "post", "/api/options/", {"kind": kind, "value": "WEATHER"})
            self.assertEqual(status, 200)
            self.assertIn((kind, "WEATHER", "alexandria"), [(o["kind"], o["value"], o["port"]) for o in data["options"]])

    def test_delay_usage_counts_vessels(self):
        allow("delay", "WEATHER")
        Vessel.objects.filter(pk__in=[self.alex_vessel.pk, self.suez_vessel.pk]).update(delay_reason="WEATHER")
        self.assertEqual(self.used(self.login("admin"), "delay", "WEATHER"), 2)
        self.assertEqual(self.used(self.login("alex"), "delay", "WEATHER"), 1)

    def test_closure_usage_counts_closures_in_scope(self):
        allow("closure", "FOG")
        start = timezone.now()
        for port in ("alexandria", "suez", "suez"):
            PortClosure.objects.create(port=port, start_at=start, reason="FOG")
        self.assertEqual(self.used(self.login("admin"), "closure", "FOG"), 3)
        self.assertEqual(self.used(self.login("alex"), "closure", "FOG"), 1)

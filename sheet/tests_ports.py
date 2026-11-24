"""Ports as a table (Admins add / rename / turn them off) and the people who work in them."""

from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from . import dataexport, ports, report
from .access import profile_of
from .models import Port, PortClosure, Service
from .tests import NEEDED, ApiTestCase
from .tests_dataexport import read


class PortTableTests(ApiTestCase):
    def test_four_ports_after_migration(self):
        self.assertEqual(list(Port.objects.values_list("key", "name", "active")), [
            ("alexandria", "Alexandria", True), ("portsaid", "Port Said", True),
            ("damietta", "Damietta", True), ("suez", "Suez", True)])
        self.assertEqual(ports.ordered(), [("alexandria", "Alexandria"), ("portsaid", "Port Said"),
                                           ("damietta", "Damietta"), ("suez", "Suez")])
        self.assertEqual(ports.keys(), ["alexandria", "portsaid", "damietta", "suez"])

    def test_make_key(self):
        self.assertEqual(ports.make_key("Port Said"), "portsaid2")  # portsaid is taken
        self.assertEqual(ports.make_key("Abu Qir!"), "abuqir")
        self.assertEqual(ports.make_key("Dekheila"), "dekheila")
        Port.objects.create(key="dekheila", name="Dekheila", position=9)
        self.assertEqual(ports.make_key("Dekheila"), "dekheila2")
        self.assertEqual(len(ports.make_key("x" * 60)), 18)

    def test_exists_and_labels(self):
        Port.objects.filter(key="suez").update(active=False)
        self.assertTrue(ports.exists("suez"))
        self.assertFalse(ports.exists("suez", active_only=True))
        self.assertFalse(ports.exists("nowhere"))
        self.assertEqual(ports.label("nowhere"), "nowhere")
        self.assertNotIn("suez", ports.keys(active_only=True))

    def test_unknown_port_refused(self):
        status, data = self.call(self.login("admin"), "post", "/api/vessels/",
                                 {**NEEDED, "name": "NEW SHIP", "date": "2026-11-13", "port": "nowhere"})
        self.assertEqual(status, 400, data)

    def test_labels_one_query(self):
        with self.assertNumQueries(1):
            ports.labels()

    def test_rename_reaches_every_label(self):
        Port.objects.filter(key="alexandria").update(name="Alexandria West")
        admin = self.login("admin")
        status, vessel = self.call(admin, "get", f"/api/vessels/{self.alex_vessel.id}/")
        self.assertEqual(vessel["port_label"], "Alexandria West")
        PortClosure.objects.create(port="alexandria", start_at="2026-11-13T06:00:00Z", reason="WIND")
        status, data = self.call(admin, "get", "/api/closures/?from=2026-11-01&to=2026-11-30")
        self.assertEqual(data["closures"][0]["port_label"], "Alexandria West")
        service = Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water", data={"revenue": 5})
        status, data = self.call(admin, "get", f"/api/services/{service.id}/receipt/")
        self.assertEqual(data["receipt"]["port"], "Alexandria West")
        admin_profile = profile_of(User.objects.get(username="admin"))
        sheet = read(dataexport.page_file("calculations", admin_profile, {"from": "2026-11-01", "to": "2026-11-30"}))
        self.assertIn("Alexandria West", str(sheet))
        figures = report.data(admin_profile, report.Range(date(2026, 11, 1), date(2026, 11, 30), None))
        self.assertIn("Alexandria West", str(figures))


class PortMigrationTests(TestCase):
    def test_migration_seeds_ports(self):
        self.assertEqual(Port.objects.count(), 4)

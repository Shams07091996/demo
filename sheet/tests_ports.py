"""Ports as a table (Admins add / rename / turn them off) and the people who work in them."""

from datetime import date

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from . import dataexport, ports, report
from .access import profile_of
from .models import Port, PortClosure, Profile, Service
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


class PeopleTests(ApiTestCase):
    def test_admin_is_superuser(self):
        alex = self.login("alex")
        for method, url, body in (("post", "/api/rates/", {"month": "2026-11", "rate": 50}),
                                  ("get", "/api/history/", None),
                                  ("post", "/api/accounting/", {"kind": "service", "id": self.suez_service.id,
                                                                "closed": True})):
            self.assertEqual(self.call(alex, method, url, body)[0], 403, url)
        self.assertTrue(User.objects.get(username="admin").is_superuser)
        self.assertTrue(profile_of(User.objects.get(username="admin")).is_admin)
        self.assertEqual(self.call(self.login("admin"), "get", "/api/history/")[0], 200)

    def test_user_without_ports_is_blocked(self):
        alex = User.objects.get(username="alex")
        Profile.objects.filter(user=alex).update(ports=[], home_port="")
        client = self.login("alex")
        response = client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/no-port/")
        self.assertContains(client.get("/login/no-port/"), "no port yet")
        response = client.get("/api/vessels/")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("ref", response.json())

    def test_exempt_rule_uses_superuser(self):
        admin = profile_of(User.objects.get(username="admin"))
        alex = profile_of(User.objects.get(username="alex"))
        self.assertFalse(admin.may_be_exempt())
        self.assertTrue(alex.may_be_exempt())

    def test_user_ports_stored(self):
        alex = profile_of(User.objects.get(username="alex"))
        self.assertEqual((alex.home_port, alex.ports), ("alexandria", ["alexandria"]))
        viewer = profile_of(User.objects.get(username="viewer"))
        self.assertEqual((viewer.home_port, viewer.ports), ("alexandria", ["alexandria", "portsaid", "damietta"]))


class AccountConversionTests(TransactionTestCase):
    """Migration 0024: roles become ports; Read-only accounts are turned off; non-superuser staff lose staff."""

    def test_migration_converts_accounts(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("sheet", "0023_port")])
        old = executor.loader.project_state([("sheet", "0023_port")]).apps
        OldUser, OldProfile = old.get_model("auth", "User"), old.get_model("sheet", "Profile")
        made = {}
        for name, role, superuser, staff in (("porter", "damietta", False, False), ("boss", "admin", False, True),
                                             ("reader", "readonly", False, False), ("root", "admin", True, True)):
            user = OldUser.objects.create(username=name, is_superuser=superuser, is_staff=staff)
            OldProfile.objects.create(user=user, role=role)
            made[name] = user.pk
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        def get(name):
            user = User.objects.get(pk=made[name])
            return user, Profile.objects.get(user=user)

        user, profile = get("porter")
        self.assertEqual((profile.home_port, profile.ports, user.is_active), ("damietta", ["damietta"], True))
        user, profile = get("boss")
        self.assertEqual((profile.home_port, profile.ports), ("alexandria", ["alexandria", "portsaid", "damietta",
                                                                             "suez"]))
        self.assertFalse(user.is_staff)
        user, profile = get("reader")
        self.assertEqual((profile.ports, user.is_active), ([], False))
        user, profile = get("root")
        self.assertEqual((profile.ports, user.is_superuser, user.is_staff), ([], True, True))

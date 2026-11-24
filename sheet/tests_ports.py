"""Ports as a table (Admins add / rename / turn them off) and the people who work in them."""

from datetime import UTC, date, datetime

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from . import dataexport, ports, report
from .access import profile_of
from .models import (
    ChangeRecord,
    DisposalPrice,
    HotelStay,
    Option,
    Port,
    PortClosure,
    Profile,
    Service,
    Transfer,
    Vessel,
)
from .tests import NEEDED, ApiTestCase, allow
from .tests_dataexport import read
from .tests_disposal import PRICE


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


RANGE = "from=2026-11-01&to=2026-11-30"
TOKENS = {"alexandria": "ALEX", "portsaid": "SAID", "damietta": "DAMI", "suez": "SUEZ"}
AT = datetime(2026, 11, 13, 10, tzinfo=UTC)


class MultiPortTests(ApiTestCase):
    """viewer works in Alexandria, Port Said and Damietta (home Alexandria); never in Suez."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        allow("closure", "WEATHER")
        allow("hotel", "HILTON")
        cls.said_vessel = Vessel.objects.create(name="SAID SHIP", date=date(2026, 11, 13), port="portsaid")
        cls.dami_vessel = Vessel.objects.create(name="DAMI SHIP", date=date(2026, 11, 13), port="damietta")
        for vessel in (cls.alex_vessel, cls.said_vessel, cls.dami_vessel, cls.suez_vessel):
            token = TOKENS[vessel.port]
            Service.objects.create(vessel=vessel, service_type="Fresh Water", agent=f"AG-{token}",
                                   data={"revenue": 10, "revenueCurrency": "EGP"})
            HotelStay.objects.create(vessel=vessel, hotel="HILTON", check_in=AT, nights=1)
            Transfer.objects.create(vessel=vessel, from_place="airport", to_place="port", at=AT)
            PortClosure.objects.create(port=vessel.port, start_at=AT, reason="WEATHER", notes=f"CL-{token}")

    def setUp(self):
        self.viewer = self.login("viewer")

    def text(self, client, url):
        response = client.get(url)
        self.assertEqual(response.status_code, 200, (url, response.content[:300]))
        if response["Content-Type"].startswith("application/vnd.openxmlformats"):
            return str(read(response.content))
        return response.content.decode()

    def seen(self, client, extra=""):
        """{url: the port tokens found in what it answered}."""
        urls = [f"/api/vessels/?{RANGE}", f"/api/services/?{RANGE}&status=in_progress", f"/api/hotels/?{RANGE}",
                f"/api/transfers/?{RANGE}", f"/api/closures/?{RANGE}", f"/api/disposal/?{RANGE}",
                f"/api/calculations/?{RANGE}", f"/api/dashboard/?{RANGE}", "/api/vessels/alerts/?",
                f"/export.csv?{RANGE}", f"/api/export/all/?{RANGE}", f"/api/dashboard/export/?{RANGE}"]
        found = {}
        for url in urls:
            body = self.text(client, url + extra)
            found[url] = {t for t in TOKENS.values() if t in body}
        return found

    def test_lists_cover_all_their_ports(self):
        for url, tokens in self.seen(self.viewer).items():
            self.assertEqual(tokens, {"ALEX", "SAID", "DAMI"}, url)

    def test_asked_port_not_theirs_is_never_wider(self):
        for url, tokens in self.seen(self.viewer, "&port=suez").items():
            self.assertEqual(tokens, {"ALEX", "SAID", "DAMI"}, url)
        for url, tokens in self.seen(self.login("alex"), "&port=suez").items():
            self.assertEqual(tokens, {"ALEX"}, url)

    def test_asked_port_narrows(self):
        for url, tokens in self.seen(self.viewer, "&port=portsaid").items():
            self.assertEqual(tokens, {"SAID"}, url)

    def test_write_into_foreign_port_refused(self):
        before = Vessel.objects.count()
        body = {**NEEDED, "name": "NEW SHIP", "date": "2026-11-13"}
        self.assertEqual(self.call(self.viewer, "post", "/api/vessels/", {**body, "port": "suez"})[0], 403)
        self.assertEqual(Vessel.objects.count(), before)
        status, _ = self.call(self.viewer, "put", f"/api/vessels/{self.alex_vessel.id}/",
                              {**NEEDED, "name": "ALEX SHIP", "date": "2026-11-13", "port": "suez"})
        self.assertEqual(status, 403)
        self.assertEqual(Vessel.objects.get(pk=self.alex_vessel.pk).port, "alexandria")
        closure = {"port": "suez", "start_at": "2026-11-14T06:00", "reason": "WEATHER"}
        self.assertEqual(self.call(self.viewer, "post", "/api/closures/", closure)[0], 403)
        self.assertFalse(PortClosure.objects.filter(port="suez", notes="").exists())
        option = {"kind": "opr", "value": "SUEZ OPR", "port": "suez"}
        self.assertEqual(self.call(self.viewer, "post", "/api/options/", option)[0], 403)
        self.assertFalse(Option.objects.filter(value="SUEZ OPR").exists())

    def test_works_fully_in_extra_port(self):
        status, vessel = self.call(self.viewer, "post", "/api/vessels/",
                                   {**NEEDED, "name": "NEW DAMI", "date": "2026-11-14", "port": "damietta"})
        self.assertEqual((status, vessel.get("port")), (201, "damietta"), vessel)
        status, data = self.call(self.viewer, "post", f"/api/vessels/{self.dami_vessel.id}/services/",
                                 {"type": "Fresh Water", "data": {}})
        self.assertEqual(status, 201, data)
        stay = {"vessel": self.dami_vessel.id, "hotel": "HILTON", "check_in": "2026-11-14", "nights": 1,
                "guests": [{"name": "ahmed test", "rank": "2/E", "group": "on"}]}
        status, data = self.call(self.viewer, "post", "/api/hotels/", stay)
        self.assertEqual(status, 201, data)
        closure = {"port": "damietta", "start_at": "2026-11-14T06:00", "reason": "WEATHER"}
        status, data = self.call(self.viewer, "post", "/api/closures/", closure)
        self.assertEqual(status, 201, data)
        status, _ = self.call(self.viewer, "post", "/api/options/",
                              {"kind": "opr", "value": "DAMI OPR", "port": "damietta"})
        self.assertEqual(status, 200)
        self.assertEqual(Option.objects.get(value="DAMI OPR").port, "damietta")
        status, data = self.call(self.viewer, "put", f"/api/disposal/{self.dami_vessel.id}/", {"garbage": "1"})
        self.assertEqual(status, 200, data)

    def test_option_all_ports_admin_only(self):
        """A User's value goes to their home port when none is named; only an Admin adds to All ports."""
        self.call(self.viewer, "post", "/api/options/", {"kind": "opr", "value": "MINE", "port": ""})
        self.assertEqual(Option.objects.get(value="MINE").port, "alexandria")
        self.call(self.login("admin"), "post", "/api/options/", {"kind": "opr", "value": "EVERYONE", "port": ""})
        everyone = Option.objects.get(value="EVERYONE")
        self.assertEqual(everyone.port, "")
        self.assertEqual(self.call(self.viewer, "delete", f"/api/options/{everyone.id}/")[0], 403)
        said = Option.objects.create(kind="opr", value="SAID OPR", port="portsaid")
        self.assertEqual(self.call(self.viewer, "delete", f"/api/options/{said.id}/")[0], 200)
        suez = Option.objects.create(kind="opr", value="SUEZ ONLY", port="suez")
        self.assertEqual(self.call(self.viewer, "delete", f"/api/options/{suez.id}/")[0], 403)
        listed = {o["value"] for o in self.call(self.viewer, "get", "/api/options/")[1]["options"]}
        self.assertIn("EVERYONE", listed)
        self.assertNotIn("SUEZ ONLY", listed)

    def test_new_vessel_defaults_to_home_port(self):
        status, vessel = self.call(self.viewer, "post", "/api/vessels/",
                                   {**NEEDED, "name": "HOME SHIP", "date": "2026-11-14"})
        self.assertEqual((status, vessel.get("port")), (201, "alexandria"), vessel)
        status, _ = self.call(self.login("admin"), "post", "/api/vessels/",
                              {**NEEDED, "name": "NOWHERE SHIP", "date": "2026-11-14"})
        self.assertEqual(status, 400)


class PortsApiTests(ApiTestCase):
    """The Ports page: Admins add, rename and turn off ports; nobody deletes one."""

    def setUp(self):
        self.admin = self.login("admin")

    def test_admin_only(self):
        for name in ("viewer", "alex"):
            client = self.login(name)
            self.assertEqual(self.call(client, "get", "/api/ports/")[0], 403)
            self.assertEqual(self.call(client, "post", "/api/ports/", {"name": "Dekheila"})[0], 403)
            self.assertEqual(self.call(client, "put", "/api/ports/alexandria/", {"name": "X"})[0], 403)
        self.assertFalse(Port.objects.filter(key="dekheila").exists())
        self.assertEqual(Port.objects.get(key="alexandria").name, "Alexandria")

    def test_add_rename_turn_off(self):
        status, port = self.call(self.admin, "post", "/api/ports/", {"name": "Dekheila"})
        self.assertEqual(status, 201, port)
        self.assertEqual((port["key"], port["name"], port["active"]), ("dekheila", "Dekheila", True))
        self.assertEqual(Port.objects.get(key="dekheila").position, 4)  # after the four first ports
        status, port = self.call(self.admin, "put", "/api/ports/dekheila/", {"name": "El Dekheila", "active": False})
        self.assertEqual((status, port["name"], port["active"]), (200, "El Dekheila", False))
        status, data = self.call(self.admin, "get", "/api/ports/")
        row = next(p for p in data["ports"] if p["key"] == "dekheila")
        self.assertEqual((row["vessels"], row["users"]), (0, 0))
        alex = next(p for p in data["ports"] if p["key"] == "alexandria")
        self.assertEqual((alex["vessels"], alex["users"]), (1, 2))  # ALEX SHIP; alex and viewer
        self.assertEqual(self.call(self.admin, "put", "/api/ports/nowhere/", {"name": "X"})[0], 404)
        records = ChangeRecord.objects.filter(object_type="port")
        self.assertEqual(sorted(records.values_list("action", flat=True)), ["create", "update"])

    def test_name_rules(self):
        for bad in ("", "  ", "x", "x" * 41, "alexandria", " PORT SAID ", None, 5):
            status, data = self.call(self.admin, "post", "/api/ports/", {"name": bad})
            self.assertEqual(status, 400, (bad, data))
        self.assertEqual(self.call(self.admin, "put", "/api/ports/suez/", {"name": "Damietta"})[0], 400)
        self.assertEqual(self.call(self.admin, "put", "/api/ports/suez/", {"active": "no"})[0], 400)
        status, port = self.call(self.admin, "put", "/api/ports/suez/", {"name": "SUEZ"})  # its own name, new case
        self.assertEqual((status, port["name"]), (200, "SUEZ"))
        self.assertEqual(Port.objects.count(), 4)

    def test_key_never_changes_on_rename(self):
        status, port = self.call(self.admin, "put", "/api/ports/alexandria/", {"name": "Alexandria West", "key": "x"})
        self.assertEqual((status, port["key"]), (200, "alexandria"))
        self.assertEqual(Vessel.objects.get(pk=self.alex_vessel.pk).port, "alexandria")
        self.assertEqual(self.call(self.admin, "get", f"/api/vessels/{self.alex_vessel.id}/")[1]["port_label"],
                         "Alexandria West")

    def test_inactive_port_blocks_new_records_only(self):
        dami = Vessel.objects.create(name="DAMI SHIP", date=date(2026, 11, 13), port="damietta")
        DisposalPrice.objects.create(month=date(2026, 10, 1), port="damietta")
        allow("closure", "WEATHER")
        self.assertEqual(self.call(self.admin, "put", "/api/ports/damietta/", {"active": False})[0], 200)
        off = "That port is turned off."
        viewer = self.login("viewer")
        checks = [
            (viewer, "post", "/api/vessels/", {**NEEDED, "name": "NEW", "date": "2026-11-14", "port": "damietta"}),
            (self.admin, "post", "/api/closures/", {"port": "damietta", "start_at": "2026-11-14T06:00",
                                                   "reason": "WEATHER"}),
            (self.admin, "post", "/api/options/", {"kind": "opr", "value": "DAMI OPR", "port": "damietta"}),
            (viewer, "post", "/api/options/", {"kind": "opr", "value": "DAMI OPR", "port": "damietta"}),
            (self.admin, "post", "/api/disposal-prices/", {**PRICE, "month": "2026-11", "port": "damietta"}),
            (self.admin, "put", f"/api/vessels/{self.alex_vessel.id}/",
             {**NEEDED, "name": "ALEX SHIP", "date": "2026-11-13", "port": "damietta"}),
        ]
        for client, method, url, body in checks:
            status, data = self.call(client, method, url, body)
            self.assertEqual((status, data.get("error")), (400, off), url)
        option = Option.objects.create(kind="opr", value="MOVE ME", port="")
        status, data = self.call(self.admin, "patch", f"/api/options/{option.id}/", {"port": "damietta"})
        self.assertEqual((status, data.get("error")), (400, off))
        self.assertFalse(Option.objects.filter(value="DAMI OPR").exists())
        status, data = self.call(viewer, "put", f"/api/vessels/{dami.id}/",
                                 {**NEEDED, "name": "DAMI SHIP 2", "date": "2026-11-13"})
        self.assertEqual(status, 200, data)
        status, data = self.call(self.admin, "post", "/api/disposal-prices/",
                                 {**PRICE, "month": "2026-10", "port": "damietta"})  # that month's price exists
        self.assertEqual(status, 200, data)
        names = [v["name"] for v in self.call(viewer, "get", "/api/vessels/")[1]["vessels"]]
        self.assertIn("DAMI SHIP 2", names)

    def test_no_delete(self):
        self.assertEqual(self.call(self.admin, "delete", "/api/ports/suez/")[0], 405)
        self.assertTrue(Port.objects.filter(key="suez").exists())

    def test_ports_nav_for_admins_only(self):
        page = self.admin.get("/").content.decode()
        self.assertIn('data-page="ports"', page)
        self.assertIn('id="page-ports"', page)
        for name in ("viewer", "alex"):
            page = self.login(name).get("/").content.decode()
            self.assertNotIn('data-page="ports"', page)
            self.assertNotIn('id="page-ports"', page)

"""Terminals: Admins add / change them (never delete); people with an Operation page read their ports' ones."""

from sheet.models import Port, Profile
from sheet.constants import PERMISSION_KEYS
from sheet.tests import ApiTestCase, allow, make_user

from .access import scoped_visits
from .models import Terminal, Visit
from .tests_models import cairo, terminal

URL = "/api/operation/terminals/"
NEW = {"name": "ACCHCO - ALX", "code": "egaly", "port": "alexandria", "quay_length": 500, "cranes": 4,
       "berths": ["23", "24", "25"], "active": True}


class TerminalApiTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.aict = terminal("AICT - ALX", "alexandria")
        cls.old = terminal("OLD - ALX", "alexandria", active=False)
        cls.psd = terminal("PSD EAST", "portsaid", berths=("1", "2"))
        make_user("novessels", "alexandria", pages=["vessels"])
        make_user("nomaster", "alexandria", permissions=[k for k in PERMISSION_KEYS if k != "operation.master"])
        allow("line", "ARKAS", "MAERSK")

    def names(self, body):
        return [t["name"] for t in body["terminals"]]

    def test_user_reads_own_ports_terminals(self):
        status, body = self.call(self.login("alex"), "get", URL)
        self.assertEqual(status, 200)
        self.assertEqual(self.names(body), ["AICT - ALX", "OLD - ALX"])
        old = body["terminals"][1]
        self.assertEqual((old["active"], old["port_label"], old["berths"]), (False, "Alexandria", ["40/1", "40/2"]))
        _, body = self.call(self.login("viewer"), "get", URL)
        self.assertEqual(self.names(body), ["AICT - ALX", "OLD - ALX", "PSD EAST"])
        _, body = self.call(self.login("viewer"), "get", URL + "?port=portsaid")
        self.assertEqual(self.names(body), ["PSD EAST"])

    def test_no_operation_page_is_403(self):
        status, _ = self.call(self.login("novessels"), "get", URL)
        self.assertEqual(status, 403)

    def test_admin_creates(self):
        status, body = self.call(self.login("admin"), "post", URL, NEW)
        self.assertEqual(status, 201)
        self.assertEqual((body["name"], body["code"], body["berths"], body["quay_length"]),
                         ("ACCHCO - ALX", "EGALY", ["23", "24", "25"], 500))

    def test_bad_terminals_refused(self):
        admin = self.login("admin")
        cases = [
            ({"name": "aict - alx"}, "That terminal already exists."),
            ({"name": "A"}, "Name must be 2 to 40 characters."),
            ({"code": ""}, "Enter the terminal code."),
            ({"code": "ABCDEFGHIJK"}, "Code is too long (at most 10 characters)."),
            ({"berths": ["23", "23"]}, "Each berth may appear only once."),
            ({"berths": []}, "Add 1 to 30 berths."),
            ({"berths": [str(n) for n in range(31)]}, "Add 1 to 30 berths."),
            ({"berths": ["12345678901"]}, "A berth name is 1 to 10 characters."),
            ({"quay_length": 0}, "Quay length must be a whole number from 1 to 10000."),
            ({"quay_length": "x"}, "Quay length must be a whole number from 1 to 10000."),
            ({"cranes": 51}, "Cranes must be a whole number from 0 to 50."),
            ({"port": "nowhere"}, "Unknown port."),
        ]
        for change, message in cases:
            status, body = self.call(admin, "post", URL, {**NEW, **change})
            self.assertEqual((status, body["error"]), (400, message), change)

    def test_turned_off_port_takes_no_new_terminal(self):
        Port.objects.filter(key="damietta").update(active=False)
        status, body = self.call(self.login("admin"), "post", URL, {**NEW, "port": "damietta"})
        self.assertEqual((status, body["error"]), (400, "That port is turned off."))

    def test_users_without_the_tick_cannot_write(self):
        user = self.login("nomaster")
        self.assertEqual(self.call(user, "post", URL, NEW)[0], 403)
        self.assertEqual(self.call(user, "put", f"{URL}{self.aict.id}/", NEW)[0], 403)

    def test_tick_writes_in_own_ports_only(self):
        alex = self.login("alex")  # make_user gives every tick, operation.master included
        status, body = self.call(alex, "post", URL, NEW)
        self.assertEqual((status, body["port"]), (201, "alexandria"))
        self.assertEqual(self.call(alex, "post", URL, {**NEW, "name": "PSD WEST", "port": "portsaid"})[0], 403)
        status, body = self.call(alex, "put", f"{URL}{self.aict.id}/", {**NEW, "name": "AICT - ALX", "cranes": 6})
        self.assertEqual((status, body["cranes"]), (200, 6))
        self.assertEqual(self.call(alex, "put", f"{URL}{self.aict.id}/", {**NEW, "name": "AICT - ALX", "port": "portsaid"})[0], 403)
        self.assertEqual(self.call(alex, "put", f"{URL}{self.psd.id}/", {**NEW, "name": "PSD EAST", "port": "portsaid"})[0], 404)

    def test_terminal_shipping_lines(self):
        admin = self.login("admin")
        status, body = self.call(admin, "post", URL, {**NEW, "lines": ["MAERSK", "ARKAS"]})
        self.assertEqual((status, body["lines"]), (201, ["MAERSK", "ARKAS"]))
        status, body = self.call(admin, "post", URL, {**NEW, "name": "X - ALX", "lines": ["NOPE"]})
        self.assertEqual((status, body["error"]),
                         (400, "Shipping line: choose a value from the Master data Shipping line list for this port."))
        status, body = self.call(admin, "post", URL, {**NEW, "name": "Y - ALX", "lines": ["ARKAS", "ARKAS"]})
        self.assertEqual((status, body["error"]), (400, "Each shipping line may appear only once."))
        status, body = self.call(admin, "post", URL, {**NEW, "name": "Z - ALX"})
        self.assertEqual((status, body["lines"]), (201, []))
        saved = Terminal.objects.get(name="ACCHCO - ALX")
        saved.lines = ["MAERSK", "OLDLINE"]
        saved.save()
        status, body = self.call(admin, "put", f"{URL}{saved.id}/", {**NEW, "lines": ["OLDLINE", "ARKAS"]})
        self.assertEqual((status, body["lines"]), (200, ["OLDLINE", "ARKAS"]))

    def test_admin_moves_terminal_and_its_visits_follow(self):
        Visit.objects.create(terminal=self.aict, vessel_name="ROZA", shipping_line="ARKAS",
                             eta=cairo("2026-11-21T08:00"))
        status, body = self.call(self.login("admin"), "put", f"{URL}{self.aict.id}/",
                                 {**NEW, "name": "AICT - ALX", "port": "portsaid"})
        self.assertEqual((status, body["port"]), (200, "portsaid"))
        alex = self.login("alex")
        self.assertNotIn("AICT - ALX", self.names(self.call(alex, "get", URL)[1]))
        self.assertFalse(scoped_visits(Profile.objects.get(user__username="alex")).exists())

    def test_no_delete(self):
        status, _ = self.call(self.login("admin"), "delete", f"{URL}{self.aict.id}/")
        self.assertEqual(status, 405)
        self.assertTrue(Terminal.objects.filter(pk=self.aict.id).exists())

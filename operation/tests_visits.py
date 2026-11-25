"""Vessel visits: add / edit / delete with the input rules, the port rules, the ticks, edit conflicts, the list's
filters and the History."""

from sheet import ports
from sheet.models import ChangeRecord, Port
from sheet.tests import ApiTestCase, allow, make_user

from .models import Visit
from .tests_models import cairo, terminal

URL = "/api/operation/visits/"
FULL = {"vessel_name": "allegri", "shipping_line": "ARKAS", "loa": "200", "eta": "2026-11-20T06:00",
        "ata": "2026-11-20T07:00", "planned_berth": "40/1", "etb": "2026-11-20T09:00", "etc": "2026-11-28T11:00",
        "atb": "2026-11-20T11:00", "actual_berth": "40/2", "cranes": 2, "atd": "2026-11-21T22:00",
        "discharge": 700, "loading": 800}
NO_PAGE = ["op_live", "op_analysis", "op_charts"]


def visit(term, name="ROZA", line="ARKAS", eta="2026-11-21T08:00", **extra):
    return Visit.objects.create(terminal=term, vessel_name=name, shipping_line=line, eta=cairo(eta), **extra)


class VisitData(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        allow("line", "ARKAS", "MAERSK", "CUL")
        cls.aict = terminal("AICT - ALX", "alexandria")
        cls.off = terminal("OLD - ALX", "alexandria", active=False)
        cls.psd = terminal("PSD EAST", "portsaid", berths=("1", "2"))
        make_user("looker", "alexandria", permissions=[], pages=["op_vessels"])
        make_user("nodelete", "alexandria", permissions=["operation.edit"], pages=["op_vessels"])
        make_user("liveonly", "alexandria", permissions=["operation.edit", "operation.delete"], pages=NO_PAGE)
        make_user("historian", "alexandria", permissions=["history.view", "money.view"], pages=["op_vessels"])

    def post(self, user, **change):
        return self.call(self.login(user), "post", URL, {**FULL, "terminal": self.aict.id, **change})


class VisitWriteTests(VisitData):
    def test_create_with_every_field(self):
        status, body = self.post("alex")
        self.assertEqual(status, 201)
        self.assertEqual((body["vessel_name"], body["terminal"], body["terminal_name"], body["port"]),
                         ("ALLEGRI", self.aict.id, "AICT - ALX", "alexandria"))
        self.assertEqual((body["eta"], body["atd"], body["loa"], body["report_date"]),
                         ("2026-11-20T06:00", "2026-11-21T22:00", 200.0, "2026-11-20"))
        self.assertEqual((body["status"], body["waiting"], body["operation"], body["port_stay"], body["total_moves"],
                          body["productivity"]), ("Completed", 4.0, 35.0, 39.0, 1500, 42.9))
        self.assertEqual(body["version"], 1)

    def test_required_and_bad_values_refused(self):
        cases = [
            ({"vessel_name": " "}, "Enter the vessel name."),
            ({"vessel_name": "X" * 101}, "Vessel name is too long (at most 100 characters)."),
            ({"terminal": None}, "Choose a terminal."),
            ({"terminal": 99999}, "Choose a terminal."),
            ({"shipping_line": ""}, "Choose a shipping line."),
            ({"shipping_line": "NOPE"},
             "Shipping line: choose a value from the Master data Shipping line list for this port."),
            ({"eta": ""}, "Enter the ETA."),
            ({"eta": "tomorrow"}, "ETA: enter a valid date and time."),
            ({"loa": "0"}, "LOA must be more than 0 and at most 500 m."),
            ({"loa": "500.1"}, "LOA must be more than 0 and at most 500 m."),
            ({"loa": "abc"}, "LOA must be a number."),
            ({"cranes": 0}, "Cranes must be a whole number from 1 to 50."),
            ({"discharge": -1}, "Discharge must be a whole number from 0 to 1000000."),
            ({"loading": 1.5}, "Loading must be a whole number from 0 to 1000000."),
            ({"planned_berth": "99"}, "Planned berth: choose one of this terminal's berths."),
            ({"actual_berth": "1"}, "Actual berth: choose one of this terminal's berths."),
        ]
        for change, message in cases:
            status, body = self.post("alex", **change)
            self.assertEqual((status, body["error"]), (400, message), change)
        self.assertFalse(Visit.objects.exists())

    def test_times_must_be_in_order(self):
        cases = [
            ({"ata": ""}, "ATB needs the ATA."),
            ({"atb": "", "actual_berth": ""}, "ATD needs the ATB."),
            ({"atb": "2026-11-20T06:59"}, "ATB cannot be before ATA."),
            ({"atd": "2026-11-20T11:00"}, "ATD must be after ATB."),
            ({"etc": "2026-11-20T08:00"}, "ETC cannot be before ETB."),
            ({"etb": "2026-11-20T05:00"}, "ETB cannot be before ETA."),
        ]
        for change, message in cases:
            status, body = self.post("alex", **change)
            self.assertEqual((status, body["error"]), (400, message), change)

    def test_only_eta_and_names_needed(self):
        status, body = self.call(self.login("alex"), "post", URL, {"terminal": self.aict.id, "vessel_name": "MYD",
                                                                     "shipping_line": "CUL", "eta": "2026-11-22T10:00"})
        self.assertEqual((status, body["status"], body["waiting"], body["total_moves"]), (201, "Planned", None, None))

    def test_saved_values_stay_allowed(self):
        saved = visit(self.aict, line="OLDLINE", planned_berth="40/9")
        status, body = self.call(self.login("alex"), "put", f"{URL}{saved.id}/",
                                 {**FULL, "terminal": self.aict.id, "shipping_line": "OLDLINE",
                                  "planned_berth": "40/9"})
        self.assertEqual((status, body["shipping_line"], body["planned_berth"]), (200, "OLDLINE", "40/9"))

    def test_other_ports_terminal_is_403(self):
        status, _ = self.post("alex", terminal=self.psd.id, planned_berth="1", actual_berth="2")
        self.assertEqual(status, 403)
        mine = visit(self.aict)
        status, _ = self.call(self.login("alex"), "put", f"{URL}{mine.id}/",
                              {**FULL, "terminal": self.psd.id, "planned_berth": "1", "actual_berth": "2"})
        self.assertEqual(status, 403)
        mine.refresh_from_db()
        self.assertEqual(mine.terminal_id, self.aict.id)
        theirs = visit(self.psd)
        self.assertEqual(self.call(self.login("alex"), "put", f"{URL}{theirs.id}/",
                                   {**FULL, "terminal": self.aict.id})[0], 404)

    def test_turned_off_terminal(self):
        status, body = self.post("alex", terminal=self.off.id)
        self.assertEqual((status, body["error"]), (400, "That terminal is turned off."))
        old = visit(self.off)
        status, body = self.call(self.login("alex"), "put", f"{URL}{old.id}/", {**FULL, "terminal": self.off.id})
        self.assertEqual((status, body["vessel_name"]), (200, "ALLEGRI"))

    def test_turned_off_port_takes_no_new_visit(self):
        old = visit(self.aict)
        Port.objects.filter(key="alexandria").update(active=False)
        ports.forget()
        status, body = self.post("alex")
        self.assertEqual((status, body["error"]), (400, "That port is turned off."))
        status, body = self.call(self.login("alex"), "put", f"{URL}{old.id}/", {**FULL, "terminal": self.aict.id})
        self.assertEqual((status, body["vessel_name"]), (200, "ALLEGRI"))

    def test_terminal_lines_limit_the_visit_line(self):
        self.aict.lines = ["ARKAS"]
        self.aict.save()
        status, body = self.post("alex", shipping_line="MAERSK")
        self.assertEqual((status, body["error"]), (400, "Shipping line: choose one of this terminal's lines."))
        self.assertEqual(self.post("alex", shipping_line="ARKAS")[0], 201)
        self.aict.lines = []
        self.aict.save()
        self.assertEqual(self.post("alex", shipping_line="MAERSK")[0], 201)
        self.aict.lines = ["ARKAS"]
        self.aict.save()
        old = visit(self.aict, line="CUL")
        status, body = self.call(self.login("alex"), "put", f"{URL}{old.id}/",
                                 {**FULL, "terminal": self.aict.id, "shipping_line": "CUL"})
        self.assertEqual((status, body["shipping_line"]), (200, "CUL"))

    def test_ticks(self):
        self.assertEqual(self.post("looker")[0], 403)
        self.assertEqual(self.call(self.login("looker"), "get", URL)[0], 200)
        self.assertEqual(self.post("liveonly")[0], 403)
        self.assertEqual(self.call(self.login("liveonly"), "get", URL)[0], 403)
        saved = visit(self.aict)
        self.assertEqual(self.call(self.login("nodelete"), "delete", f"{URL}{saved.id}/")[0], 403)
        self.assertEqual(self.call(self.login("looker"), "put", f"{URL}{saved.id}/", FULL)[0], 403)
        self.assertEqual(self.call(self.login("alex"), "delete", f"{URL}{saved.id}/")[0], 200)
        self.assertFalse(Visit.objects.filter(pk=saved.pk).exists())

    def test_old_version_is_a_conflict(self):
        saved = visit(self.aict)
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "put", f"{URL}{saved.id}/",
                                   {**FULL, "terminal": self.aict.id, "version": 1})[0], 200)
        status, body = self.call(alex, "put", f"{URL}{saved.id}/", {**FULL, "terminal": self.aict.id, "version": 1})
        self.assertEqual((status, body["error"]), (409, "conflict"))

    def test_history_for_a_user_of_the_port(self):
        self.post("alex")
        visit(self.psd)
        status, body = self.call(self.login("historian"), "get", "/api/history/?type=visit")
        self.assertEqual(status, 200)
        ports = {r["port"] for r in body["records"] if r["object_type"] == "visit"}
        self.assertEqual(ports, {"alexandria"})
        self.assertEqual(ChangeRecord.objects.filter(object_type="visit").count(), 2)


class VisitListTests(VisitData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.planned = visit(cls.aict, "ALPHA", "ARKAS", "2026-11-22T08:00")
        cls.working = visit(cls.aict, "BRAVO", "MAERSK", "2026-11-21T08:00", ata=cairo("2026-11-21T09:00"),
                            atb=cairo("2026-11-21T12:00"))
        cls.done = visit(cls.aict, "CHARLIE", "ARKAS", "2026-11-20T08:00", ata=cairo("2026-11-19T22:00"),
                         atb=cairo("2026-11-20T00:00"), atd=cairo("2026-11-20T10:00"), discharge=100)
        cls.theirs = visit(cls.psd, "DELTA", "CUL", "2026-11-23T08:00")

    def names(self, user, query=""):
        status, body = self.call(self.login(user), "get", URL + query)
        self.assertEqual(status, 200, body)
        return [v["vessel_name"] for v in body["visits"]]

    def test_scoped_newest_eta_first(self):
        self.assertEqual(self.names("alex"), ["ALPHA", "BRAVO", "CHARLIE"])
        self.assertEqual(self.names("viewer"), ["DELTA", "ALPHA", "BRAVO", "CHARLIE"])
        self.assertEqual(self.names("viewer", "?port=portsaid"), ["DELTA"])
        self.assertEqual(self.names("alex", "?port=portsaid"), ["ALPHA", "BRAVO", "CHARLIE"])

    def test_filters(self):
        self.assertEqual(self.names("alex", "?status=Working,Completed"), ["BRAVO", "CHARLIE"])
        self.assertEqual(self.names("alex", f"?terminal={self.aict.id}&line=ARKAS"), ["ALPHA", "CHARLIE"])
        self.assertEqual(self.names("alex", "?q=rav"), ["BRAVO"])
        self.assertEqual(self.names("alex", "?from=2026-11-19&to=2026-11-19"), ["CHARLIE"])  # its ATA day
        self.assertEqual(self.names("alex", "?from=2026-11-21"), ["ALPHA", "BRAVO"])
        status, body = self.call(self.login("alex"), "get", URL + "?status=Sailing")
        self.assertEqual((status, body["error"]), (400, "Unknown status."))
        status, body = self.call(self.login("alex"), "get", URL + "?from=2026-11-22&to=2026-11-21")
        self.assertEqual((status, body["error"]), (400, "From must be on or before To."))

    def test_sort_and_paging(self):
        self.assertEqual(self.names("alex", "?sort=waiting&dir=asc"), ["CHARLIE", "BRAVO", "ALPHA"])
        self.assertEqual(self.names("alex", "?sort=vessel_name&dir=desc"), ["CHARLIE", "BRAVO", "ALPHA"])
        status, body = self.call(self.login("alex"), "get", URL + "?page_size=2&page=2")
        self.assertEqual((body["total"], body["page"], body["pages"]), (3, 2, 2))
        self.assertEqual([v["vessel_name"] for v in body["visits"]], ["CHARLIE"])
        self.assertEqual(body["lines"], ["ARKAS", "MAERSK"])
        self.assertEqual(self.call(self.login("alex"), "get", URL + "?sort=password")[0], 400)

    def test_rights_in_rows(self):
        status, body = self.call(self.login("looker"), "get", URL)
        self.assertEqual((body["visits"][0]["can_edit"], body["visits"][0]["can_delete"]), (False, False))
        status, body = self.call(self.login("alex"), "get", URL)
        self.assertEqual((body["visits"][0]["can_edit"], body["visits"][0]["can_delete"]), (True, True))

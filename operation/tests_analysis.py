"""Analysis reports / Report charts: the workbook's seven visits must give the workbook's figures."""

from sheet.tests import ApiTestCase, allow, make_user

from .models import Visit
from .tests_models import cairo, terminal

URL = "/api/operation/analysis/"
# name, line, terminal, LOA, ETA, ATA, ATB, ATD, cranes, discharge, loading, planned berth, actual berth
WORKBOOK = [
    ("ALLEGRI", "ARKAS", "ACCHCO - ALX", 200, "11-20T06:00", "11-20T07:00", "11-20T11:00", "11-21T22:00", 2, 700, 800,
     "25", "25"),
    ("EGYCROWN", "MAERSK", "AICT - ALX", 150, "11-21T08:00", "11-21T09:00", "11-21T14:00", "11-22T05:00", 2, 500, 500,
     "40/1", "40/1"),
    ("MYD", "MCL", "AICT - DKH", 200, "11-30T09:00", "11-30T11:00", "11-30T14:00", "12-01T01:00", 2, 200, 300,
     "98/2", "98/2"),
    ("TB QUANZHOU", "MCL", "AICT - DKH", 150, "12-01T14:00", "12-02T01:00", "12-02T02:00", "12-03T05:00", 2, 250, 400,
     "98/1", "98/2"),
    ("ZHONG GU", "CUL", "AICT - ALX", 150, "11-24T06:00", "11-24T07:00", "11-24T10:00", "11-25T14:00", 2, 500, 500,
     "40/1", "40/2"),
    ("GLEVIN", "ICR", "AICT - DKH", 100, "11-22T06:00", "11-22T07:00", "11-22T11:00", "11-25T02:00", 2, 200, 500,
     "98/2", "98/2"),
    ("ROZA", "ARKAS", "ACCHCO - ALX", 200, "11-27T01:00", "11-27T03:00", "11-27T18:00", "11-28T01:00", 1, 100, 500,
     "25", "23"),
]
TERMINALS = [("ACCHCO - ALX", ("23", "24", "25")), ("AICT - ALX", ("40/1", "40/2")),
             ("ACCHCO - DKH", ("96/1", "96/2")), ("AICT - DKH", ("98/1", "98/2")), ("TMT - ALX", ("27", "28"))]


def when(text):
    return cairo(f"2026-{text}")


class AnalysisTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        allow("line", "ARKAS", "MAERSK", "MCL", "CUL", "ICR")
        cls.terminals = {name: terminal(name, "alexandria", berths, position=i)
                         for i, (name, berths) in enumerate(TERMINALS)}
        for name, line, term, loa, eta, ata, atb, atd, cranes, disch, load, planned, actual in WORKBOOK:
            Visit.objects.create(terminal=cls.terminals[term], vessel_name=name, shipping_line=line, loa=loa,
                                 eta=when(eta), ata=when(ata), atb=when(atb), atd=when(atd), cranes=cranes,
                                 discharge=disch, loading=load, planned_berth=planned, actual_berth=actual)
        psd = terminal("PSD EAST", "portsaid", ("1",))
        Visit.objects.create(terminal=psd, vessel_name="THEIRS", shipping_line="CUL", eta=when("11-21T08:00"))
        make_user("chartsonly", "alexandria", pages=["op_charts"])
        make_user("liveonly2", "alexandria", pages=["op_live"])

    def get(self, query="", user="alex"):
        status, body = self.call(self.login(user), "get", URL + query)
        self.assertEqual(status, 200, body)
        return body

    def row(self, rows, name):
        return next(r for r in rows if r["name"] == name)

    def test_headline_matches_the_workbook(self):
        self.assertEqual(self.get()["headline"], {"calls": 7, "waiting": 5.0, "operation": 26.6, "port_stay": 31.6,
                                                  "productivity": 44.5, "per_week": None, "per_month": None,
                                                  "per_year": None})

    def test_terminal_rows_match_the_workbook(self):
        rows = self.get()["terminals"]
        self.assertEqual([r["name"] for r in rows], [name for name, _ in TERMINALS])
        self.assertEqual(self.row(rows, "ACCHCO - ALX"), {
            "name": "ACCHCO - ALX", "calls": 2, "waiting": 9.5, "operation": 21.0, "port_stay": 30.5, "loa": 200.0,
            "cranes": 1.5, "productivity": 64.3, "total_moves": 2100, "berthed": 2})
        self.assertEqual(self.row(rows, "AICT - DKH"), {
            "name": "AICT - DKH", "calls": 3, "waiting": 2.7, "operation": 33.7, "port_stay": 36.3, "loa": 150.0,
            "cranes": 2.0, "productivity": 26.9, "total_moves": 1850, "berthed": 3})
        self.assertEqual(self.row(rows, "AICT - ALX")["productivity"], 51.2)
        self.assertEqual(self.row(rows, "TMT - ALX"), {
            "name": "TMT - ALX", "calls": 0, "waiting": None, "operation": None, "port_stay": None, "loa": None,
            "cranes": None, "productivity": None, "total_moves": 0, "berthed": 0})

    def test_one_row_per_shipping_line(self):
        rows = self.get()["lines"]
        self.assertEqual([r["name"] for r in rows], ["ARKAS", "MCL", "CUL", "ICR", "MAERSK"])
        self.assertEqual((rows[0]["calls"], rows[0]["waiting"], rows[0]["total_moves"]), (2, 9.5, 2100))

    def test_filters(self):
        aict_dkh = self.terminals["AICT - DKH"].id
        body = self.get(f"?terminal={aict_dkh}")
        self.assertEqual(body["headline"]["calls"], 3)
        self.assertEqual([r["name"] for r in body["terminals"]], ["AICT - DKH"])
        self.assertEqual(body["berth_choices"], ["98/1", "98/2"])
        self.assertEqual(self.get("?berth=98/2")["headline"]["calls"], 3)  # actual berth, else planned
        self.assertEqual(self.get("?berth=25")["headline"]["calls"], 1)
        body = self.get("?line=MCL")
        self.assertEqual((body["headline"]["calls"], [r["name"] for r in body["lines"]]), (2, ["MCL"]))
        self.assertEqual(self.get("?from=2026-11-25&to=2026-11-30")["headline"]["calls"], 2)  # ROZA, MYD by ATA
        self.assertEqual(self.get()["line_choices"], ["ARKAS", "CUL", "ICR", "MAERSK", "MCL"])

    def test_calls_per_week_month_year(self):
        headline = self.get("?from=2026-11-20&to=2026-12-03")["headline"]
        self.assertEqual((headline["calls"], headline["per_week"], headline["per_month"], headline["per_year"]),
                         (7, 3.5, 15.2, 182.6))
        self.assertIsNone(self.get("?from=2026-11-20")["headline"]["per_week"])

    def test_nothing_matches(self):
        body = self.get("?line=NOBODY")
        self.assertEqual(body["headline"]["calls"], 0)
        self.assertIsNone(body["headline"]["waiting"])
        self.assertEqual(body["lines"], [])

    def test_bad_input(self):
        status, body = self.call(self.login("alex"), "get", URL + "?from=2026-12-01&to=2026-11-01")
        self.assertEqual((status, body["error"]), (400, "From must be on or before To."))
        self.assertEqual(self.call(self.login("alex"), "get", URL + "?terminal=abc")[0], 400)

    def test_scoping_and_pages(self):
        self.assertEqual(self.get(user="viewer")["headline"]["calls"], 8)
        self.assertEqual(self.get(user="chartsonly")["headline"]["calls"], 7)
        self.assertEqual(self.call(self.login("liveonly2"), "get", URL)[0], 403)

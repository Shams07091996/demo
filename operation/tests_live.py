"""Live data: per active terminal of the person's ports, the vessels under operation and those due in 7 days."""

from datetime import timedelta
from unittest import mock

from sheet.tests import ApiTestCase, make_user

from .tests_models import cairo, terminal
from .tests_visits import visit

URL = "/api/operation/live/"
NOW = cairo("2026-11-25T12:00")


@mock.patch("operation.views.timezone.now", return_value=NOW)
class LiveTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.aict = terminal("AICT - ALX", "alexandria", position=2)
        cls.acchco = terminal("ACCHCO - ALX", "alexandria", berths=("23", "24"), position=1, code="EGALY")
        cls.off = terminal("OLD - ALX", "alexandria", active=False, position=3)
        cls.psd = terminal("PSD EAST", "portsaid", berths=("1",))
        visit(cls.aict, "LATE", atb=NOW - timedelta(hours=2), ata=NOW - timedelta(hours=3), discharge=100)
        visit(cls.aict, "EARLY", atb=NOW - timedelta(hours=10), ata=NOW - timedelta(hours=12))
        visit(cls.aict, "DONE", ata=NOW - timedelta(days=1), atb=NOW - timedelta(hours=20),
              atd=NOW - timedelta(hours=1))
        visit(cls.aict, "SOON", eta="2026-11-25T18:00")
        visit(cls.aict, "NEXT", eta="2026-11-27T08:00")
        visit(cls.aict, "YESTERDAY", eta="2026-11-24T08:00")
        visit(cls.aict, "TOO FAR", eta="2026-12-02T12:00")
        visit(cls.aict, "LAST DAY", eta="2026-12-02T11:59")
        visit(cls.off, "ON OLD", atb=NOW, ata=NOW)
        visit(cls.psd, "THEIRS", eta="2026-11-26T08:00")
        make_user("vesselsonly", "alexandria", pages=["op_vessels"])

    def get(self, user, query=""):
        status, body = self.call(self.login(user), "get", URL + query)
        self.assertEqual(status, 200, body)
        return body["terminals"]

    def test_cards_are_active_terminals_of_my_ports_in_order(self, _now):
        self.assertEqual([t["name"] for t in self.get("alex")], ["ACCHCO - ALX", "AICT - ALX"])
        self.assertEqual([t["name"] for t in self.get("viewer", "?port=portsaid")], ["PSD EAST"])

    def test_working_and_upcoming(self, _now):
        aict = self.get("alex")[1]
        self.assertEqual([v["vessel_name"] for v in aict["working"]], ["EARLY", "LATE"])
        self.assertEqual(aict["working"][1]["live_rate"], 50.0)
        self.assertIsNone(aict["working"][0]["live_rate"])
        self.assertEqual([v["vessel_name"] for v in aict["upcoming"]], ["SOON", "NEXT", "LAST DAY"])
        self.assertEqual(aict["upcoming"][0]["eta"], "2026-11-25T18:00")

    def test_calls_in_last_7_days(self, _now):
        # ETA from 19 Nov 00:00 to the end of 25 Nov: the three created with the default ETA (21 Nov),
        # YESTERDAY and SOON.
        self.assertEqual(self.get("alex")[1]["calls_7d"], 5)

    def test_needs_live_page(self, _now):
        self.assertEqual(self.call(self.login("vesselsonly"), "get", URL)[0], 403)

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
        visit(cls.aict, "LAST DAY", eta="2026-12-01T23:59")  # the 6th day after today: still in
        visit(cls.aict, "THIS MORNING", eta="2026-11-25T08:00")  # due earlier today, not arrived: still in
        visit(cls.aict, "ANCHORED", eta="2026-11-23T08:00", ata=NOW - timedelta(hours=5))  # arrived, not berthed
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
        self.assertEqual([v["vessel_name"] for v in aict["upcoming"]],
                         ["ANCHORED", "YESTERDAY", "THIS MORNING", "SOON", "NEXT", "LAST DAY"])
        self.assertEqual([v["arrived"] for v in aict["upcoming"]], [True, False, False, False, False, False])
        self.assertEqual(aict["upcoming"][3]["eta"], "2026-11-25T18:00")

    def test_overdue_without_ata_stays_marked(self, _now):
        upcoming = {v["vessel_name"]: v for v in self.get("alex")[1]["upcoming"]}
        self.assertEqual((upcoming["YESTERDAY"]["overdue"], upcoming["YESTERDAY"]["arrived"]), (True, False))
        self.assertTrue(upcoming["THIS MORNING"]["overdue"])  # its ETA (08:00) has passed by noon
        self.assertFalse(upcoming["ANCHORED"]["overdue"])  # arrived: Arrived, not Overdue
        self.assertFalse(upcoming["SOON"]["overdue"])

    def test_old_overdue_still_shows(self, _now):
        visit(self.aict, "FORGOTTEN", eta="2026-10-26T08:00")
        names = [v["vessel_name"] for v in self.get("alex")[1]["upcoming"]]
        self.assertEqual(names[0], "FORGOTTEN")

    def test_completed_never_upcoming(self, _now):
        names = [v["vessel_name"] for v in self.get("alex")[1]["upcoming"]]
        self.assertNotIn("DONE", names)
        self.assertNotIn("EARLY", names)

    def test_calls_in_last_7_days(self, _now):
        # ETA from 19 Nov 00:00 to the end of 25 Nov: the three created with the default ETA (21 Nov),
        # YESTERDAY, SOON, THIS MORNING and ANCHORED.
        self.assertEqual(self.get("alex")[1]["calls_7d"], 7)

    def test_needs_live_page(self, _now):
        self.assertEqual(self.call(self.login("vesselsonly"), "get", URL)[0], 403)

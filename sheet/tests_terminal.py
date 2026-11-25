"""Terminal (Master data list per port) and berth (typed) on a vessel."""

from datetime import date

from . import report
from .access import profile_of
from .constants import OPTION_KIND_KEYS
from .models import Vessel
from .tests import NEEDED, ApiTestCase, allow


class TerminalTests(ApiTestCase):
    def setUp(self):
        allow("terminal", "ACCHCO", port="alexandria")
        allow("terminal", "TMT", port="portsaid")
        self.alex = self.login("alex")

    def create(self, **extra):
        return self.call(self.alex, "post", "/api/vessels/", {**NEEDED, "name": "T", "date": "2026-11-13", **extra})

    def test_kind_listed(self):
        self.assertIn("terminal", OPTION_KIND_KEYS)

    def test_saved_and_returned(self):
        status, vessel = self.create(terminal="ACCHCO", berth="98/1")
        self.assertEqual((status, vessel["terminal"], vessel["berth"]), (201, "ACCHCO", "98/1"))

    def test_empty_allowed(self):
        status, vessel = self.create()
        self.assertEqual((status, vessel["terminal"], vessel["berth"]), (201, "", ""))

    def test_other_ports_terminal_refused(self):
        status, body = self.create(terminal="TMT")
        self.assertEqual(status, 400)
        self.assertIn("Terminal", body["error"])

    def test_berth_too_long_refused(self):
        self.assertEqual(self.create(berth="x" * 21)[0], 400)

    def test_save_without_keys_keeps_them(self):
        _, vessel = self.create(terminal="ACCHCO", berth="23")
        status, saved = self.call(self.alex, "put", f"/api/vessels/{vessel['id']}/",
                                  {**NEEDED, "name": "T", "date": "2026-11-13"})
        self.assertEqual((status, saved["terminal"], saved["berth"]), (200, "ACCHCO", "23"))

    def test_excel_calls_by_terminal(self):
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(terminal="ACCHCO", berth="23", date=date(2026, 11, 13))
        sheet = report.data(_admin(),
                            report.Range(date(2026, 11, 1), date(2026, 11, 30), None))["ports_perf"]
        table = next(t for t in sheet["tables"] if t["head"][:3] == ["Port", "Terminal", "Berth"])
        self.assertIn(["Alexandria", "ACCHCO", "23", 1], [row[:4] for row in table["rows"]])


def _admin():
    from django.contrib.auth.models import User

    return profile_of(User.objects.get(username="admin"))

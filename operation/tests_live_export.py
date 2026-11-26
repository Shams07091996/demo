"""Live data's Excel: one sheet per terminal card, laid out like a terminal block of the workbook's Dashboard."""

import io
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import override_settings

from sheet.tests import ApiTestCase, make_user
from sheet.tests_xlsx import tiny_png

from .live import UPCOMING_HEAD, WORKING_HEAD, title_line
from .tests_models import cairo, terminal
from .tests_visits import visit

URL = "/api/operation/live/export/"
NOW = cairo("2026-11-25T12:00")


@mock.patch("operation.live.timezone.now", return_value=NOW)
class LiveExportTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.acchco = terminal("ACCHCO - ALX", "alexandria", berths=("23", "24"), position=1, code="EGALY")
        cls.aict = terminal("AICT - ALX", "alexandria", position=2, code="EGAIT")
        cls.psd = terminal("PSD EAST", "portsaid", berths=("1",), code="EGPSD")
        visit(cls.aict, "WORKING ONE", atb=NOW - timedelta(hours=2), ata=NOW - timedelta(hours=3), discharge=100)
        visit(cls.aict, "LATE ONE", eta="2026-11-24T08:00")
        visit(cls.aict, "WAITING ONE", eta="2026-11-23T08:00", ata=NOW - timedelta(hours=5))
        visit(cls.psd, "THEIRS", eta="2026-11-26T08:00")
        make_user("noexports", "alexandria", permissions=[], pages=["op_live"])
        make_user("nolive", "alexandria", permissions=["exports"], pages=["op_vessels"])

    def parts(self, user, query=""):
        response = self.login(user).get(URL + query)
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        return {n: archive.read(n) if n.startswith("xl/media/") else archive.read(n).decode()
                for n in archive.namelist()}

    def test_one_sheet_per_terminal(self, _now):
        workbook = self.parts("alex")["xl/workbook.xml"]
        self.assertIn('name="EGALY"', workbook)
        self.assertIn('name="EGAIT"', workbook)
        self.assertNotIn("EGPSD", workbook)

    def test_working_and_next_rows(self, _now):
        xml = self.parts("alex")["xl/worksheets/sheet2.xml"]  # AICT, second in order
        for text in ("Under operation", "Next 7 days", *WORKING_HEAD, *UPCOMING_HEAD, "WORKING ONE", "LATE ONE",
                     "WAITING ONE", "Overdue", "Arrived"):
            self.assertIn(f">{text}<", xml)
        self.assertLess(xml.index(">Under operation<"), xml.index(">WORKING ONE<"))
        self.assertLess(xml.index(">Next 7 days<"), xml.index(">LATE ONE<"))
        empty = self.parts("alex")["xl/worksheets/sheet1.xml"]  # ACCHCO has no vessels
        self.assertEqual(empty.count(">No vessels<"), 2)

    def test_one_terminal_only(self, _now):
        parts = self.parts("alex", f"?terminal={self.aict.id}")
        self.assertIn('name="EGAIT"', parts["xl/workbook.xml"])
        self.assertNotIn("EGALY", parts["xl/workbook.xml"])

    def test_other_port_terminal_404(self, _now):
        self.assertEqual(self.login("alex").get(f"{URL}?terminal={self.psd.id}").status_code, 404)
        self.assertEqual(self.login("alex").get(f"{URL}?terminal=abc").status_code, 400)

    def test_needs_exports_and_page(self, _now):
        self.assertEqual(self.login("noexports").get(URL).status_code, 403)
        self.assertEqual(self.login("nolive").get(URL).status_code, 403)

    def test_picture_included(self, _now):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "terminals").mkdir()
            Path(folder, "terminals", "EGALY.png").write_bytes(tiny_png(800, 200))
            with override_settings(LETTERHEAD_DIR=folder):
                parts = self.parts("alex")
        self.assertEqual(parts["xl/media/image1.png"], tiny_png(800, 200))
        self.assertIn("<xdr:pic>", parts["xl/drawings/drawing1.xml"])
        self.assertNotIn("xl/drawings/drawing2.xml", parts)  # AICT has no picture

    def test_no_terminal_gives_no_data_sheet(self, _now):
        make_user("damietta", "damietta", permissions=["exports"], pages=["op_live"])
        parts = self.parts("damietta")
        self.assertIn('name="No data"', parts["xl/workbook.xml"])

    def test_title_line(self, _now):
        card = {"name": "ACCHCO - ALX", "berths": ["23", "24", "25"], "quay_length": 1000, "cranes": 4}
        self.assertEqual(title_line(card), "ACCHCO - ALX | Berth No. 23 / 24 / 25 | Quay 1,000 m | Gantry Cranes: 4")
        self.assertEqual(title_line({"name": "X", "berths": [], "quay_length": None, "cranes": None}), "X")

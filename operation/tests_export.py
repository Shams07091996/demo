"""The Vessel Data page's Excel: the filtered visits as a plain table."""

import io
import zipfile

from sheet.tests import ApiTestCase, make_user

from .tests_models import terminal
from .tests_visits import visit

URL = "/api/operation/visits/export/"
HEAD = ["ID", "Vessel", "Line", "Terminal", "LOA (m)", "ETA", "ATA", "Planned berth", "ETB", "ETC", "ATB",
        "Actual berth", "Cranes", "ATD", "Status", "Waiting (hrs)", "Operation (hrs)", "Discharge", "Loading",
        "Total moves", "Moves/hr", "Port stay (hrs)"]


class ExportTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.aict = terminal("AICT - ALX", "alexandria")
        visit(cls.aict, "ALPHA", "ARKAS")
        visit(cls.aict, "BRAVO", "MAERSK")
        visit(terminal("PSD EAST", "portsaid", ("1",)), "THEIRS")
        make_user("noexports", "alexandria", permissions=["operation.edit"], pages=["op_vessels"])

    def sheet_xml(self, user, query=""):
        client = self.login(user)
        response = client.get(URL + query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return zipfile.ZipFile(io.BytesIO(response.content)).read("xl/worksheets/sheet1.xml").decode()

    def test_header_and_filtered_rows(self):
        xml = self.sheet_xml("alex", "?line=ARKAS")
        positions = [xml.index(f">{title}<") for title in HEAD]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(">ALPHA<", xml)
        self.assertNotIn(">BRAVO<", xml)

    def test_scoped(self):
        self.assertNotIn(">THEIRS<", self.sheet_xml("alex"))
        self.assertIn(">THEIRS<", self.sheet_xml("viewer"))

    def test_needs_exports(self):
        self.assertEqual(self.call(self.login("noexports"), "get", URL)[0], 403)

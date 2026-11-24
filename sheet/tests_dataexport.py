"""Plain-table Excel files of the Hotels, Transport, Port closures, Garbage & Sludge and Calculations pages."""

import io
import re
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from xml.sax.saxutils import unescape

from django.test import override_settings

from . import dataexport
from .models import Guest, HotelStay, PortClosure, Service, Transfer
from .tests import ApiTestCase

HEADERS = {
    "hotels": ["Booking id", "Vessel id", "Vessel", "Port", "Guests", "Hotel", "Check-in", "Nights", "Check-out",
               "Cost per night", "Cost currency", "Revenue per night", "Revenue currency", "Exchange rate", "Draft",
               "Cancelled", "Accounting"],
    "transfers": ["Booking id", "Vessel id", "Vessel", "Port", "Guests", "From", "To", "Airport", "Hotel", "Port name",
                  "Date & time", "Cost", "Cost currency", "Revenue", "Revenue currency", "Exchange rate", "Draft",
                  "Cancelled", "Accounting"],
    "closures": ["Closure id", "Port", "Closed from", "Reopened", "Hours", "Reason", "Notes"],
    "disposal": ["Vessel id", "Vessel", "Date", "OPR", "Port", "Garbage m³", "Sludge t", "Hidden", "Revenue EGP",
                 "Cost EGP", "Profit EGP", "Revenue USD", "Cost USD", "Profit USD", "Rate missing", "Price missing",
                 "Accounting"],
    "calculations": ["Vessel id", "Vessel", "Vessel date", "OPR", "Port", "Item", "Line", "Note", "Record", "Record id",
                     "Cost", "Cost currency", "Revenue", "Revenue currency", "Cost EGP", "Revenue EGP", "Profit EGP",
                     "Cost USD", "Revenue USD", "Profit USD", "Rate source", "Rate missing", "Price missing", "Status",
                     "Cancellation reason", "Accounting"],
}
CELL = re.compile(r'<c r="([A-Z]+)(\d+)"(?: s="(\d+)")?(?: t="inlineStr")?>(?:<v>([^<]*)</v>|<is><t[^>]*>([^<]*)</t></is>)</c>')


def read(data):
    """{sheet name: [[value, ...] per row]} (numbers as float, text as str, empty cells as None)."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    workbook = archive.read("xl/workbook.xml").decode()
    names = [unescape(n) for n in re.findall(r'<sheet name="([^"]+)"', workbook)]
    out = {}
    for i, name in enumerate(names, 1):
        rows = {}
        for col, row, _style, number, text in CELL.findall(archive.read(f"xl/worksheets/sheet{i}.xml").decode()):
            index = sum((ord(c) - 64) * 26 ** k for k, c in enumerate(reversed(col))) - 1
            cells = rows.setdefault(int(row), [])
            cells.extend([None] * (index + 1 - len(cells)))
            cells[index] = float(number) if number else unescape(text)
        out[name] = [rows[k] for k in sorted(rows)]
    return out


def serial(day):
    return float((day - date(1899, 12, 30)).days)


class SheetTests(ApiTestCase):
    def setUp(self):
        from .models import Profile

        self.profile = Profile.objects.get(user__username="viewer")
        self.alex_profile = Profile.objects.get(user__username="alex")

    def rows(self, page, profile=None, **params):
        sheets = read(dataexport.page_file(page, profile or self.profile, params))
        self.assertEqual(len(sheets), 1)
        return next(iter(sheets.values()))

    def test_headers_fixed(self):
        for page, head in HEADERS.items():
            self.assertEqual(self.rows(page)[0], head, page)

    def test_empty_has_header_only(self):
        for page in HEADERS:
            self.assertEqual(len(self.rows(page, **{"from": "2001-01-01", "to": "2001-01-31"})), 1, page)

    def stay(self, guests=("A",), **extra):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 13), nights=2,
                                        **extra)
        for name in guests:
            Guest.objects.create(stay=stay, name=name)
        return stay

    def test_page_file_has_every_filtered_row(self):
        for i in range(250):
            self.stay(guests=(f"FINDME {i}",))
        self.stay(guests=("OTHER",))
        self.assertEqual(len(self.rows("hotels", q="findme")), 251)  # header + every match, not one page of 50
        Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water", status="cancelled",
                               cancel_reason="x", data={"cost": 5, "costCurrency": "EGP"})
        rows = self.rows("calculations", status="cancelled")
        self.assertTrue(len(rows) > 1)
        self.assertTrue(all(r[23] == "Cancelled" for r in rows[1:]))

    def test_formula_text_stays_text(self):
        self.stay(guests=('=HYPERLINK("http://x")', "+1", "@x"))
        data = dataexport.page_file("hotels", self.profile, {})
        sheet = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("<f>", sheet)
        row = next(r for r in self.rows("hotels") if r[4] and "HYPERLINK" in r[4])
        self.assertEqual(row[4], '=HYPERLINK("http://x"); +1; @x')

    def test_values_typed(self):
        stay = self.stay(guests=("A", "B"), cost_per_night=Decimal("80"), revenue_per_night=Decimal("100.5"),
                         acct_closed=True)
        row = next(r for r in self.rows("hotels") if r[0] == stay.id)
        self.assertEqual(row[1:9], [self.alex_vessel.id, "ALEX SHIP", "Alexandria", "A; B", "HILTON",
                                    serial(date(2026, 11, 13)), 2, serial(date(2026, 11, 15))])
        self.assertEqual(row[9:13], [80.0, "EGP", 100.5, "EGP"])
        self.assertEqual(row[14:17], ["No", "No", "Closed"])
        trip = Transfer.objects.create(vessel=self.alex_vessel, from_place="airport", to_place="port",
                                       airport="CAI", at=datetime(2026, 11, 13, 6, tzinfo=UTC))
        row = next(r for r in self.rows("transfers") if r[0] == trip.id)
        self.assertEqual(row[5:8], ["Airport (CAI)", "Port", "CAI"])
        self.assertAlmostEqual(row[10], serial(date(2026, 11, 13)) + 8 / 24, places=6)  # 06:00 UTC = 08:00 Cairo
        closure = PortClosure.objects.create(port="alexandria", start_at=datetime(2026, 11, 13, 4, tzinfo=UTC),
                                             reason="WEATHER")
        row = next(r for r in self.rows("closures") if r[0] == closure.id)
        self.assertEqual((row[1], row[3], row[5]), ("Alexandria", None, "WEATHER"))

    def test_port_user_only_their_port(self):
        rows = self.rows("calculations", profile=self.alex_profile, port="suez")
        self.assertTrue(all(r[4] == "Alexandria" for r in rows[1:]))

    def test_all_file_has_five_sheets(self):
        sheets = read(dataexport.all_file(self.profile, date(2026, 11, 1), date(2026, 11, 30), None))
        self.assertEqual(list(sheets), ["Hotels", "Transport", "Port closures", "Garbage & Sludge", "Calculations"])
        self.assertEqual([rows[0] for rows in sheets.values()], list(HEADERS.values()))


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@override_settings(RATE_LIMIT_EXPORTS_PER_USER=50)
class DownloadTests(ApiTestCase):
    def test_page_download(self):
        with self.assertLogs("sheet.audit", "INFO") as logs:
            response = self.login("viewer").get("/api/export/hotels/", {"q": "x"})
        self.assertEqual((response.status_code, response["Content-Type"]), (200, XLSX))
        self.assertRegex(response["Content-Disposition"], r'^attachment; filename="Hotels \d{4}-\d\d-\d\d\.xlsx"$')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(list(read(response.content)), ["Hotels"])
        self.assertIn("action=data.export page=hotels", logs.output[-1])

    def test_all_download(self):
        response = self.login("admin").get("/api/export/all/", {"from": "2026-11-01", "to": "2026-11-30"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"],
                         'attachment; filename="All data All ports 2026-11-01 to 2026-11-30.xlsx"')
        self.assertEqual(len(read(response.content)), 5)

    def test_port_user_gets_only_their_port(self):
        Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water", data={"cost": 7, "costCurrency": "EGP"})
        alex = self.login("alex")
        page = read(alex.get("/api/export/calculations/", {"port": "suez"}).content)["Calculations"]
        self.assertTrue(page[1:] and all(r[4] == "Alexandria" for r in page[1:]))
        response = alex.get("/api/export/all/", {"from": "2026-11-01", "to": "2026-11-30", "port": "suez"})
        self.assertIn("Alexandria", response["Content-Disposition"])
        rows = read(response.content)["Calculations"]
        self.assertTrue(all(r[4] == "Alexandria" for r in rows[1:]))

    def test_bad_requests(self):
        client = self.login("admin")
        self.assertEqual(client.get("/api/export/vessels/").status_code, 404)
        self.assertEqual(client.get("/api/export/all/").json()["error"], "Choose a From and To date.")
        response = client.get("/api/export/all/", {"from": "2025-01-01", "to": "2027-01-31"})
        self.assertEqual(response.json()["error"], "Choose a range of at most 24 months.")
        self.assertEqual(client.get("/api/export/hotels/", {"from": "nope"}).status_code, 400)
        self.assertEqual(client.get("/api/export/calculations/", {"status": "odd"}).status_code, 400)
        self.assertIn(client.post("/api/export/hotels/").status_code, (403, 405))  # GET only

    @override_settings(RATE_LIMIT_EXPORTS_PER_USER=2)
    def test_export_rate_limited(self):
        viewer = self.login("viewer")
        for _ in range(2):
            self.assertEqual(viewer.get("/api/export/closures/").status_code, 200)
        self.assertEqual(viewer.get("/api/export/closures/").status_code, 429)

"""The management workbook: its tables (report.data) and its download."""

import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone

from . import calculations, dashboard, report, xlsx
from .access import profile_of
from .models import DisposalPrice, ExchangeRate, HotelStay, PortClosure, Service, Transfer, Vessel, VesselDisposal
from .tests import ApiTestCase
from .validators import clean_service_data

RANGE = report.Range(date(2026, 9, 1), date(2026, 12, 31), None)
PARAMS = {"from": "2026-09-01", "to": "2026-12-31"}


def profile(username):
    return profile_of(User.objects.get(username=username))


def table(data, key, index=0):
    return data[key]["tables"][index]


class ManagementFixture(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ExchangeRate.objects.create(month=date(2026, 10, 1), rate=Decimal("50"))
        cls.v_oct = Vessel.objects.create(name="OCT SHIP", date=date(2026, 10, 5), port="alexandria", opr="MSK",
                                          arrival_agent="AG1", sailing_agent="AG2")
        cls.v_dec = Vessel.objects.create(name="DEC SHIP", date=date(2026, 12, 10), port="alexandria", opr="ARK",
                                          arrival_agent="AG2")
        cls.v_noline = Vessel.objects.create(name="NO LINE", date=date(2026, 12, 11), port="alexandria")
        cls.add(cls.v_oct, "Fresh Water", {"revenue": 100, "revenueCurrency": "USD", "cost": 1000}, "AG1")
        cls.add(cls.v_oct, "Landing", {"entries": [{"revenue": 300, "cost": 100}]}, "")
        cls.add(cls.v_dec, "Medical Treatment", {"revenue": 10, "revenueCurrency": "USD"}, "AG1")  # no Dec rate
        cls.add(cls.v_noline, "Certificates", {"revenue": 500}, "AG2")
        HotelStay.objects.create(vessel=cls.v_dec, hotel="H", check_in=date(2026, 12, 9), nights=2,
                                 cost_per_night=Decimal("100"), revenue_per_night=Decimal("150"))
        Transfer.objects.create(vessel=cls.v_dec, from_place="airport", to_place="port",
                                at=timezone.make_aware(timezone.datetime(2026, 12, 9, 10)),
                                cost=Decimal("50"), revenue=Decimal("80"))
        DisposalPrice.objects.create(month=date(2026, 10, 1), port="alexandria", garbage_revenue_extra=Decimal("10"),
                                     garbage_cost_extra=Decimal("100"))
        VesselDisposal.objects.create(vessel=cls.v_oct, garbage=Decimal("5"))

    @classmethod
    def add(cls, vessel, service_type, data, agent):
        return Service.objects.create(vessel=vessel, service_type=service_type, agent=agent,
                                      data=clean_service_data(service_type, data))


class MoneyAndCountTests(ManagementFixture):
    def test_summary_equals_calculations_totals(self):
        data = report.data(profile("admin"), RANGE)
        totals = calculations.response(profile("admin"), PARAMS)["totals"]
        total = table(data, "summary")["total"]
        self.assertEqual(total[0], "Total")
        self.assertEqual(total[3:6], [totals["revenue_egp"], totals["cost_egp"], totals["profit_egp"]])
        notes = data["summary"]["notes"]
        self.assertIn("Money includes hotels, transport and garbage & sludge.", notes)
        self.assertIn("1 money lines used USD 1:1 (no exchange rate for that month).", notes)

    def test_summary_rows_per_port(self):
        rows = table(report.data(profile("admin"), RANGE), "summary")["rows"]
        self.assertEqual([r[0] for r in rows], ["Alexandria", "Suez"])
        self.assertEqual(rows[0][1], 4)  # the three fixture vessels + the base test vessel in November

    def test_months_zero_filled(self):
        rows = table(report.data(profile("admin"), RANGE), "months")["rows"]
        self.assertEqual([r[0] for r in rows], ["2026-09", "2026-10", "2026-11", "2026-12"])
        self.assertEqual(rows[0], ["2026-09", 0, 0, 0.0, 0.0, 0.0])

    def test_lines_sorted_by_revenue_and_no_line(self):
        rows = table(report.data(profile("admin"), RANGE), "lines")["rows"]
        revenues = [r[3] for r in rows]
        self.assertEqual(revenues, sorted(revenues, reverse=True))
        self.assertIn("(no line)", [r[0] for r in rows])
        self.assertEqual(rows[0][0], "MSK")
        by_port = table(report.data(profile("admin"), RANGE), "lines", 1)
        self.assertEqual(by_port["head"][:2], ["Line", "Port"])

    def test_services_include_bookings_and_garbage(self):
        data = report.data(profile("admin"), RANGE)
        services = table(data, "services")
        names = [r[0] for r in services["rows"]]
        for name in ("Hotels", "Transport", "Garbage & Sludge", "Fresh Water"):
            self.assertIn(name, names)
        self.assertEqual(services["total"][2:5], table(data, "summary")["total"][3:6])

    def test_agents_match_dashboard(self):
        rows = table(report.data(profile("admin"), RANGE), "agents")["rows"]
        expected = dashboard.response(profile("admin"), PARAMS)["agents"]
        self.assertEqual([r[0] for r in rows], [a["agent"] or "(no agent)" for a in expected])
        self.assertEqual([r[-1] for r in rows], [a["total"] for a in expected])
        self.assertEqual(rows[-1][0], "(no agent)")

    def test_port_user_only_sees_their_port(self):
        rows = table(report.data(profile("alex"), report.Range(RANGE.date_from, RANGE.date_to, "suez")),
                     "summary")["rows"]
        self.assertEqual([r[0] for r in rows], ["Alexandria"])


def plain(value):
    return value.value if isinstance(value, xlsx.Hours) else value


def cairo(*parts):
    return timezone.make_aware(datetime(*parts))


def landing(day):
    return {"segments": [{"flightNo": "MS 1", "arrivalCity": "Cairo", "arrivalTime": day,
                          "departureCity": "Istanbul", "departureTime": day}]}


class OperationsTests(ManagementFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Vessel.objects.filter(pk=cls.v_oct.pk).update(
            arrival_at=cairo(2026, 10, 5, 8), berthing_at=cairo(2026, 10, 5, 11), sailing_at=cairo(2026, 10, 5, 20),
            delay_reason="PORT CLOSED")
        Vessel.objects.filter(pk=cls.v_dec.pk).update(arrival_at=cairo(2026, 12, 10, 8),
                                                      berthing_at=cairo(2026, 12, 10, 9))
        cls.before = PortClosure.objects.create(port="alexandria", start_at=cairo(2026, 8, 31, 18),
                                                end_at=cairo(2026, 9, 1, 12), reason="WEATHER")
        cls.open = PortClosure.objects.create(port="suez", start_at=cairo(2026, 11, 19, 0), reason="FOG")
        cls.add(cls.v_oct, "Crew Change", {
            "onSigners": [{"name": "EARLY", "flightStructured": landing("02 OCT 10:00"),
                           "brokenVisa": {"revenue": 20, "revenueCurrency": "USD"}},
                          {"name": "ONE DAY", "flightStructured": landing("04 OCT 10:00")}],
            "offSigners": [{"name": "OFF"}]}, "AG1")
        VesselDisposal.objects.filter(vessel=cls.v_oct).update(garbage=Decimal("10"), sludge=Decimal("2"))
        VesselDisposal.objects.create(vessel=cls.v_dec, garbage=Decimal("10"), sludge=Decimal("2"), hidden=True)

    def test_port_performance_averages(self):
        data = report.data(profile("admin"), RANGE)
        ports = table(data, "ports_perf")
        self.assertEqual(ports["head"], ["Port", "Vessels with times", "Avg waiting (h)", "Avg at berth (h)",
                                         "Avg in port (h)", "Delayed vessels"])
        alexandria = next(r for r in ports["rows"] if r[0] == "Alexandria")
        self.assertEqual(plain(alexandria[2]), 2.0)
        self.assertEqual(plain(alexandria[3]), 9.0)
        self.assertEqual(alexandria[5], 1)
        months = table(data, "ports_perf", 1)
        self.assertEqual(months["head"][0], "Month")
        self.assertEqual([r[0] for r in months["rows"]], ["2026-09", "2026-10", "2026-11", "2026-12"])
        self.assertIsNone(plain(months["rows"][0][2]))
        self.assertEqual(table(data, "ports_perf", 2)["rows"], [["PORT CLOSED", 1]])

    def test_closure_hours_clipped(self):
        data = report.data(profile("admin"), RANGE)
        ports = {r[0]: r for r in table(data, "closures")["rows"]}
        self.assertEqual([plain(v) for v in ports["Alexandria"][1:]], [1, 12.0, 0])
        end = min(timezone.now(), cairo(2027, 1, 1, 0))
        expected = (end - self.open.start_at).total_seconds() / 3600
        self.assertAlmostEqual(plain(ports["Suez"][2]), expected, delta=0.1)
        self.assertEqual(ports["Suez"][3], 1)
        reasons = {r[0]: r for r in table(data, "closures", 1)["rows"]}
        self.assertEqual([plain(v) for v in reasons["WEATHER"][1:]], [1, 12.0])

    def test_crew_counts_every_early_arrival(self):
        crew = table(report.data(profile("admin"), RANGE), "crew")
        self.assertEqual(crew["head"], ["Line", "Crew changes", "On-signers", "Off-signers", "Early arrivals",
                                        "Broken visa revenue (EGP)", "Hotel nights", "Transfers"])
        msk = next(r for r in crew["rows"] if r[0] == "MSK")
        self.assertEqual(msk[1:6], [1, 2, 1, 1, 1000.0])
        ark = next(r for r in crew["rows"] if r[0] == "ARK")
        self.assertEqual(ark[6:], [2, 1])
        self.assertEqual(crew["total"][0], "Total")

    def test_disposal_hidden_left_out_and_money_matches(self):
        data = report.data(profile("admin"), RANGE)
        disposal = table(data, "disposal")
        self.assertEqual(disposal["head"], ["Port", "Garbage (m³)", "Sludge (t)", *report.MONEY_HEAD])
        self.assertEqual(disposal["total"][1:3], [10.0, 2.0])
        rows = calculations.response(profile("admin"), {**PARAMS, "page_size": "200"})["rows"]
        revenue = round(sum(r["revenue_egp"] for r in rows if r["kind"] == "Garbage & Sludge"), 2)
        self.assertEqual(disposal["total"][3], revenue)
        months = table(data, "disposal", 1)
        self.assertEqual([r[0] for r in months["rows"]], ["2026-09", "2026-10", "2026-11", "2026-12"])

    def test_empty_range_has_no_rows(self):
        data = report.data(profile("admin"), report.Range(date(2020, 1, 1), date(2020, 1, 31), None))
        for key, index in (("ports_perf", 0), ("ports_perf", 2), ("closures", 0), ("closures", 1), ("crew", 0),
                           ("disposal", 0)):
            self.assertEqual(table(data, key, index)["rows"], [], (key, index))


SHEETS = ["Summary", "By month", "By line", "Profit by service", "Port performance", "Port closures", "Agents",
          "Crew", "Garbage &amp; Sludge"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def parts(response):
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


@override_settings(RATE_LIMIT_EXPORTS_PER_USER=50)
class ExportTests(ManagementFixture):
    URL = "/api/dashboard/export/"

    def get(self, username, **params):
        return self.login(username).get(self.URL, {**PARAMS, **params})

    def test_export_downloads_nine_sheets(self):
        response = self.get("admin")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX)
        self.assertEqual(response["Content-Disposition"],
                         'attachment; filename="Management All ports 2026-09-01 to 2026-12-31.xlsx"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        files = parts(response)
        self.assertEqual(re.findall(r'<sheet name="([^"]+)"', files["xl/workbook.xml"]), SHEETS)
        self.assertIn("xl/charts/chart1.xml", files)

    def test_export_needs_a_range(self):
        client = self.login("admin")
        response = client.get(self.URL)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Choose a From and To date.")
        response = client.get(self.URL, {"from": "2025-01-01", "to": "2027-01-31"})
        self.assertEqual(response.json()["error"], "Choose a range of at most 24 months.")
        response = client.get(self.URL, {"from": "2026-12-01", "to": "2026-11-01"})
        self.assertEqual(response.json()["error"], "From must be on or before To.")
        self.assertEqual(client.get(self.URL, {"from": "2025-01-01", "to": "2026-12-31"}).status_code, 200)

    def test_export_empty_range_no_charts(self):
        response = self.get("admin", **{"from": "2020-01-01", "to": "2020-01-31"})
        self.assertEqual(response.status_code, 200)
        files = parts(response)
        self.assertFalse([name for name in files if name.startswith("xl/charts/")])
        self.assertIn("No data", files["xl/worksheets/sheet1.xml"])

    def test_export_port_user_pinned(self):
        response = self.get("alex", port="suez")
        summary = parts(response)["xl/worksheets/sheet1.xml"]
        self.assertIn("Alexandria", summary)
        self.assertNotIn("Suez", summary)
        self.assertIn("Alexandria", response["Content-Disposition"])

    def test_export_read_only_allowed_and_rate_limited(self):
        self.assertEqual(self.get("viewer").status_code, 200)
        with override_settings(RATE_LIMIT_EXPORTS_PER_USER=2):
            client = self.login("viewer")
            codes = [client.get(self.URL, PARAMS).status_code for _ in range(3)]
        self.assertEqual(codes[-1], 429)

    def test_export_text_literal(self):
        Vessel.objects.filter(pk=self.v_noline.pk).update(opr='=HYPERLINK("x")')
        files = parts(self.get("admin"))
        by_line = files["xl/worksheets/sheet3.xml"]
        self.assertIn("=HYPERLINK(&quot;x&quot;)", by_line.replace('"', "&quot;"))
        self.assertNotIn("<f>", by_line)

    def test_export_post_refused(self):
        self.assertIn(self.login("admin").post(self.URL).status_code, (403, 405))  # CSRF or method


class ConsistencyTests(ManagementFixture):
    def test_line_of_a_vessel_saved_meanwhile_is_left_out(self):
        # A vessel added to the range between the report's queries must not crash it (KeyError → 500).
        real = calculations.rows_for

        def with_newcomer(queryset):
            newcomer = Vessel.objects.create(name="LATE", date=date(2026, 10, 6), port="alexandria", opr="MSK")
            self.add(newcomer, "Crew Change", {"onSigners": [{"name": "A", "brokenVisa": {"revenue": 5}}]}, "")
            VesselDisposal.objects.create(vessel=newcomer, garbage=Decimal("1"))
            return real(queryset)

        with mock.patch.object(calculations, "rows_for", with_newcomer):
            data = report.data(profile("admin"), RANGE)
        self.assertEqual(table(data, "summary")["total"][1], 4 + 1)  # the four fixture vessels + SUEZ SHIP

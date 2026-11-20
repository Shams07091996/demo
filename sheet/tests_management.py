"""The management workbook: its tables (report.data) and its download."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

from . import calculations, dashboard, report
from .access import profile_of
from .models import DisposalPrice, ExchangeRate, HotelStay, Service, Transfer, Vessel, VesselDisposal
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

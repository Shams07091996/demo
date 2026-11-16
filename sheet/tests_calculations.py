"""Calculations: money on every service, the money lines behind every figure, and the Calculations page API."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from . import finance
from .logistics import booking_line
from .models import HotelStay, Service, Transfer
from .tests import ApiTestCase
from .validators import clean_service_data


class EveryServiceHasMoneyTests(SimpleTestCase):
    def test_crew_change_and_others_carry_money(self):
        data = clean_service_data(
            "Crew Change",
            {"onSigners": [{"name": "A"}], "cost": "100", "revenue": "250", "revenueCurrency": "USD", "exchangeRate": "50"},
        )
        self.assertEqual(
            (data["onSigners"][0]["name"], data["cost"], data["revenue"], data["revenueCurrency"]), ("A", 100.0, 250.0, "USD")
        )
        self.assertEqual(finance.compute("Crew Change", data, None)["profit_egp"], 12400.0)
        note = clean_service_data("Others / Remarks", {"note": "x", "cost": "5"})
        self.assertEqual((note["note"], note["cost"]), ("x", 5.0))
        self.assertEqual(finance.compute("Others / Remarks", note, None)["cost_egp"], 5.0)


class CrewChangeMoneyInVesselTotalsTests(ApiTestCase):
    def test_crew_change_money_counts_in_vessel_totals(self):
        Service.objects.create(vessel=self.alex_vessel, service_type="Crew Change", data={"cost": 10, "costCurrency": "EGP"})
        vessel = self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/")[1]
        self.assertEqual(vessel["total_cost_egp"], 10.0)


class ServiceLinesTests(SimpleTestCase):
    def test_lines_show_the_working(self):
        data = {"quantity": 40, "cost": 2000, "costCurrency": "EGP", "revenue": 100, "revenueCurrency": "USD"}
        [line] = finance.service_lines("Fresh Water", data, Decimal("50"))
        self.assertEqual(
            (line["label"], line["revenue"]["rate"], line["revenue"]["egp"], line["rate_source"], line["profit_egp"]),
            ("Fresh Water · 40 t", 50.0, 5000.0, "month", 3000.0),
        )
        self.assertEqual((line["cost"]["currency"], line["cost"]["rate"], line["cost"]["times"]), ("EGP", None, 1))
        own = finance.service_lines("Fresh Water", {"revenue": 1, "revenueCurrency": "USD", "exchangeRate": 48}, Decimal("50"))[0]
        self.assertEqual((own["rate_source"], own["revenue"]["egp"], own["rate_missing"]), ("own", 48.0, False))
        egp_only = finance.service_lines("Certificates", {"certName": "SOLAS", "revenue": 5}, Decimal("50"))[0]
        self.assertEqual((egp_only["label"], egp_only["rate_source"], egp_only["cost"]), ("Certificates · SOLAS", "", None))
        flagged = finance.service_lines("Landing", {"entries": [{"revenue": 10, "revenueCurrency": "USD"}]}, None)[0]
        self.assertEqual((flagged["rate_missing"], flagged["revenue"]["egp"], flagged["revenue"]["rate"]), (True, 10.0, None))

    def test_multi_entries_and_cash_to_master(self):
        lines = finance.service_lines("Delivery Parcels", {"entries": [{"awb": "123", "weight": 3, "cost": 10}, {"cost": 5}]}, None)
        self.assertEqual([line["label"] for line in lines], ["Delivery Parcels · AWB 123 · 3 kg", "Delivery Parcels"])
        data = {"amount": 1000, "amountCurrency": "USD", "percentage": 5}
        [cash] = finance.service_lines("Cash to Master", data, Decimal("50"))
        self.assertEqual((cash["cost"], cash["revenue_egp"], cash["revenue"]["amount"]), (None, 2500.0, 50.0))
        self.assertEqual(cash["note"], "5% of USD 1,000.00 · USD 950.00 to the master")
        fixed = finance.service_lines("Cash to Master", {**data, "shareMode": "fixed", "fixedRevenue": 40}, Decimal("50"))[0]
        self.assertEqual(fixed["note"], "fixed USD 40.00 · USD 960.00 to the master")

    def test_empty_lines_are_dropped_but_one_sided_lines_stay(self):
        self.assertEqual(finance.service_lines("Others / Remarks", {"note": "hello"}, None), [])
        self.assertEqual(finance.service_lines("Others / Remarks", {"note": "x", "cost": 0, "revenue": 0}, None), [])
        self.assertEqual(len(finance.service_lines("Certificates", {"revenue": 5}, None)), 1)
        self.assertEqual(len(finance.service_lines("Landing", {"entries": [{"cost": 1}, {}]}, None)), 1)

    def test_compute_equals_the_sum_of_lines_to_the_cent(self):
        data = {"entries": [{"cost": 0.333, "revenue": 0.335}] * 3}
        lines = finance.service_lines("Landing", data, None)
        figures = finance.compute("Landing", data, None)
        self.assertAlmostEqual(figures["profit_egp"], round(sum(line["profit_egp"] for line in lines), 2), places=2)
        self.assertEqual(len(figures["entries"]), 3)
        self.assertEqual(len(finance.compute("Landing", {"entries": [{}, {"cost": 1}]}, None)["entries"]), 2)  # kept 1:1


class BookingLineTests(ApiTestCase):
    def test_hotel_line_multiplies_by_nights(self):
        stay = HotelStay(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=2,
                         cost_per_night=Decimal("80"), cost_currency="USD",
                         revenue_per_night=Decimal("4500"), revenue_currency="EGP")
        line = booking_line("hotels", stay, Decimal("50"))
        self.assertEqual(
            (line["label"], line["cost"]["times"], line["cost_egp"], line["revenue_egp"], line["profit_egp"]),
            ("Hotel · HILTON · 2 nights", 2, 8000.0, 9000.0, 1000.0),
        )

    def test_transfer_line_names_the_places_and_uses_its_own_rate(self):
        trip = Transfer(vessel=self.alex_vessel, from_place="airport", to_place="hotel", airport="BORG", hotel="HILTON",
                        cost=Decimal("20"), cost_currency="USD", exchange_rate=Decimal("48"), revenue=Decimal("1200"))
        line = booking_line("transfers", trip, Decimal("50"))
        self.assertEqual((line["label"], line["cost_egp"], line["rate_source"]),
                         ("Transfer · Airport (BORG) → Hotel (HILTON)", 960.0, "own"))

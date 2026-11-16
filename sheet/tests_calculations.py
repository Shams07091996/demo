"""Calculations: money on every service, the money lines behind every figure, and the Calculations page API."""

from django.test import SimpleTestCase

from . import finance
from .models import Service
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

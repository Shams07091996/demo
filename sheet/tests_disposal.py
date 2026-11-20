"""Garbage & Sludge: monthly per-port USD prices, the service and its money (USD and EGP)."""

from datetime import date
from decimal import Decimal

from .models import ChangeRecord, DisposalPrice
from .tests import ApiTestCase

PRICE = {"month": "2026-11", "port": "alexandria", "garbage_cost": "10", "garbage_revenue": "15",
         "sludge_cost": "20", "sludge_revenue": "32.5"}


class PriceApiTests(ApiTestCase):
    URL = "/api/disposal-prices/"

    def test_admin_saves_and_updates_a_month_and_port(self):
        admin = self.login("admin")
        status, data = self.call(admin, "post", self.URL, PRICE)
        self.assertEqual(status, 200)
        self.assertEqual(data["prices"], [{
            "id": DisposalPrice.objects.get().id, "month": "2026-11", "label": "11.2026", "port": "alexandria",
            "port_label": "Alexandria", "garbage_cost": 10.0, "garbage_revenue": 15.0, "sludge_cost": 20.0,
            "sludge_revenue": 32.5,
        }])
        self.call(admin, "post", self.URL, {**PRICE, "garbage_cost": "11"})
        price = DisposalPrice.objects.get()
        self.assertEqual((price.month, price.garbage_cost), (date(2026, 11, 1), Decimal("11")))

    def test_every_port_has_its_own_price(self):
        admin = self.login("admin")
        self.call(admin, "post", self.URL, PRICE)
        self.call(admin, "post", self.URL, {**PRICE, "port": "suez"})
        self.assertEqual(DisposalPrice.objects.count(), 2)

    def test_bad_input_refused(self):
        admin = self.login("admin")
        for bad, message in (
            ({"month": "nope"}, "Enter a month."),
            ({"port": "cairo"}, "Unknown port."),
            ({"garbage_cost": "-1"}, "Garbage cost must be 0 or more."),
            ({"sludge_revenue": "abc"}, "Sludge revenue must be a number."),
        ):
            self.assertEqual(self.call(admin, "post", self.URL, {**PRICE, **bad}), (400, {"error": message}))
        self.assertFalse(DisposalPrice.objects.exists())

    def test_only_admins_change_prices(self):
        for user in ("alex", "viewer"):
            status, _ = self.call(self.login(user), "post", self.URL, PRICE)
            self.assertEqual(status, 403)
        price = DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria")
        status, _ = self.call(self.login("alex"), "delete", f"{self.URL}{price.id}/")
        self.assertEqual(status, 403)
        status, data = self.call(self.login("admin"), "delete", f"{self.URL}{price.id}/")
        self.assertEqual((status, data["prices"]), (200, []))

    def test_port_users_read_their_port_only(self):
        DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria")
        DisposalPrice.objects.create(month=date(2026, 11, 1), port="suez")
        _, alex = self.call(self.login("alex"), "get", self.URL)
        _, viewer = self.call(self.login("viewer"), "get", self.URL)
        self.assertEqual([p["port"] for p in alex["prices"]], ["alexandria"])
        self.assertEqual(sorted(p["port"] for p in viewer["prices"]), ["alexandria", "suez"])

    def test_changes_are_in_the_history(self):
        self.call(self.login("admin"), "post", self.URL, PRICE)
        record = ChangeRecord.objects.get(object_type="disposalprice", action="create")
        self.assertEqual(record.username, "admin")


class PricedCase(ApiTestCase):
    """Alexandria, November 2026, rate 50: garbage at 10 / 15 USD per m³, sludge at 20 / 32.50 USD per m³."""

    def setUp(self):
        from .models import ExchangeRate

        ExchangeRate.objects.create(month=date(2026, 11, 1), rate=Decimal("50"))
        DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria", garbage_cost=10, garbage_revenue=15,
                                     sludge_cost=20, sludge_revenue=Decimal("32.5"))
        self.alex = self.login("alex")

    def add(self, vessel, data, client=None):
        from .tests import allow

        allow("agent", "NILE")
        return self.call(client or self.alex, "post", f"/api/vessels/{vessel.id}/services/",
                         {"type": "Garbage & Sludge", "agent": "NILE", "data": data})


class MoneyTests(PricedCase):

    def test_quantities_are_cleaned(self):
        from .validators import clean_service_data

        self.assertEqual(clean_service_data("Garbage & Sludge", {"garbage": "3", "sludge": "", "cost": 99}),
                         {"garbage": 3.0, "sludge": None})
        for bad, message in (({"garbage": "-1"}, "Garbage (m³) must be 0 or more."),
                             ({"sludge": "x"}, "Sludge (m³) must be a number.")):
            with self.assertRaisesMessage(Exception, message):
                clean_service_data("Garbage & Sludge", bad)

    def test_money_from_quantity_price_and_rate(self):
        status, vessel = self.add(self.alex_vessel, {"garbage": 3, "sludge": 2})
        self.assertEqual(status, 201)
        calc = vessel["services"][-1]["calc"]
        # garbage 30 / 45 USD, sludge 40 / 65 USD -> cost 70 USD = 3500 EGP, revenue 110 USD = 5500 EGP
        self.assertEqual((calc["cost_egp"], calc["revenue_egp"], calc["profit_egp"]), (3500.0, 5500.0, 2000.0))
        self.assertFalse(calc["price_missing"] or calc["rate_missing"])
        self.assertEqual(vessel["total_profit_egp"], 2000.0)
        self.assertEqual(vessel["disposal_price"], {"garbage": {"cost": 10.0, "revenue": 15.0},
                                                    "sludge": {"cost": 20.0, "revenue": 32.5}})

    def test_lines_show_their_working(self):
        from .finance import service_lines

        prices = {"garbage": {"cost": 10.0, "revenue": 15.0}, "sludge": {"cost": 20.0, "revenue": 32.5}}
        lines = service_lines("Garbage & Sludge", {"garbage": 3, "sludge": 0}, 50, prices)
        self.assertEqual([item["label"] for item in lines], ["Garbage · 3 m³"])  # no sludge: no line
        cost = lines[0]["cost"]
        self.assertEqual((cost["amount"], cost["times"], cost["currency"], cost["rate"], cost["egp"]),
                         (10.0, 3.0, "USD", 50, 1500.0))

    def test_no_price_for_that_port_and_month_is_flagged(self):
        alex_admin = self.login("admin")
        _, vessel = self.add(self.suez_vessel, {"garbage": 3}, client=alex_admin)
        calc = vessel["services"][-1]["calc"]
        self.assertTrue(calc["price_missing"])
        self.assertEqual((calc["cost_egp"], calc["revenue_egp"]), (0.0, 0.0))
        self.assertIsNone(vessel["disposal_price"])

    def test_price_follows_the_vessel_month(self):
        from .models import Vessel

        _, vessel = self.add(self.alex_vessel, {"garbage": 1})
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(date=date(2026, 12, 2))
        _, moved = self.call(self.alex, "get", f"/api/vessels/{self.alex_vessel.id}/")
        self.assertTrue(moved["services"][-1]["calc"]["price_missing"])


class CalculationsTests(PricedCase):
    """The Calculations page shows these lines in USD and EGP, with USD totals."""

    def test_usd_figures_and_totals(self):
        self.add(self.alex_vessel, {"garbage": 3, "sludge": 2})
        _, data = self.call(self.alex, "get", "/api/calculations/?from=2026-11-01&to=2026-11-30")
        rows = {row["label"]: row for row in data["rows"]}
        garbage = rows["Garbage · 3 m³"]
        self.assertEqual((garbage["cost_usd"], garbage["revenue_usd"], garbage["profit_usd"]), (30.0, 45.0, 15.0))
        self.assertEqual((garbage["cost_egp"], garbage["profit_egp"]), (1500.0, 750.0))
        self.assertEqual(rows["Sludge · 2 m³"]["profit_usd"], 25.0)
        totals = data["totals"]
        self.assertEqual((totals["cost_usd"], totals["revenue_usd"], totals["profit_usd"]), (70.0, 110.0, 40.0))
        self.assertEqual(totals["price_missing_lines"], 0)

    def test_egp_lines_have_no_usd_figures(self):
        _, data = self.call(self.login("admin"), "get", "/api/calculations/?from=2026-11-01&to=2026-11-30")
        fresh_water = next(row for row in data["rows"] if row["kind"] == "Fresh Water")
        self.assertIsNone(fresh_water["profit_usd"])
        self.assertEqual(data["totals"]["profit_usd"], 0.0)

    def test_missing_price_line_is_listed(self):
        self.add(self.suez_vessel, {"sludge": 4}, client=self.login("admin"))
        _, data = self.call(self.login("admin"), "get", "/api/calculations/?from=2026-11-01&to=2026-11-30")
        row = next(row for row in data["rows"] if row["kind"] == "Garbage & Sludge")
        self.assertTrue(row["price_missing"])
        self.assertEqual(data["totals"]["price_missing_lines"], 1)

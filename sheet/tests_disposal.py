"""Garbage & Sludge: monthly prices per port (minimum + extra per unit) and the page of vessel quantities."""

from datetime import date
from decimal import Decimal

from .models import ChangeRecord, DisposalPrice, ExchangeRate, Vessel, VesselDisposal
from .tests import ApiTestCase


def block(min_qty, minimum, currency, extra):
    return {"min_qty": min_qty, "min": minimum, "currency": currency, "extra": extra}


# The user's example: garbage minimum 3 m³ = USD 250 revenue / LE 5,200 cost, sludge minimum 25 t = USD 875 / LE 11,000.
PRICE = {
    "month": "2026-11", "port": "alexandria",
    "garbage": {"revenue": block("3", "250", "USD", "60"), "cost": block("3", "5200", "EGP", "1500")},
    "sludge": {"revenue": block("25", "875", "USD", "30"), "cost": block("25", "11000", "EGP", "400")},
}
URL = "/api/disposal-prices/"


def with_block(kind, side, **changes):
    return {**PRICE, kind: {**PRICE[kind], side: {**PRICE[kind][side], **changes}}}


class BlockAmountTests(ApiTestCase):

    def test_minimum_then_extra(self):
        from .disposal import block_amount

        b = {"min_qty": 3, "min": 250, "extra": 60}
        self.assertEqual([block_amount(q, b) for q in (None, 0, 1, 3, 5, 3.5)], [0.0, 0.0, 250.0, 250.0, 370.0, 280.0])


class PriceApiTests(ApiTestCase):

    def test_admin_saves_and_updates_a_month_and_port(self):
        admin = self.login("admin")
        status, data = self.call(admin, "post", URL, PRICE)
        self.assertEqual(status, 200)
        saved = data["prices"][0]
        self.assertEqual((saved["month"], saved["label"], saved["port"], saved["port_label"]),
                         ("2026-11", "11.2026", "alexandria", "Alexandria"))
        self.assertEqual(saved["garbage"]["cost"], {"min_qty": 3.0, "min": 5200.0, "currency": "EGP", "extra": 1500.0})
        self.assertEqual(saved["sludge"]["revenue"]["currency"], "USD")
        self.call(admin, "post", URL, with_block("garbage", "cost", min="5500"))
        price = DisposalPrice.objects.get()
        self.assertEqual((price.month, price.garbage_cost_min), (date(2026, 11, 1), Decimal("5500")))

    def test_every_port_has_its_own_price(self):
        admin = self.login("admin")
        self.call(admin, "post", URL, PRICE)
        self.call(admin, "post", URL, {**PRICE, "port": "suez"})
        self.assertEqual(DisposalPrice.objects.count(), 2)

    def test_bad_input_refused(self):
        admin = self.login("admin")
        for bad, message in (
            ({**PRICE, "month": "nope"}, "Enter a month."),
            ({**PRICE, "port": "cairo"}, "Unknown port."),
            (with_block("garbage", "revenue", min=""), "Enter the garbage revenue minimum (0 if none)."),
            (with_block("sludge", "cost", extra="-1"), "Sludge cost extra per t must be 0 or more."),
            (with_block("sludge", "revenue", min_qty="abc"), "Sludge revenue minimum quantity must be a number."),
            (with_block("garbage", "cost", currency="GBP"), "Garbage cost currency must be EGP or USD."),
            (with_block("garbage", "revenue", min="9999999999.996"), "Garbage revenue minimum is too large."),
        ):
            self.assertEqual(self.call(admin, "post", URL, bad), (400, {"error": message}))
        self.assertFalse(DisposalPrice.objects.exists())

    def test_only_admins_change_prices(self):
        for user in ("alex", "viewer"):
            status, _ = self.call(self.login(user), "post", URL, PRICE)
            self.assertEqual(status, 403)
        price = DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria")
        status, _ = self.call(self.login("alex"), "delete", f"{URL}{price.id}/")
        self.assertEqual(status, 403)
        status, data = self.call(self.login("admin"), "delete", f"{URL}{price.id}/")
        self.assertEqual((status, data["prices"]), (200, []))

    def test_port_users_read_their_port_only(self):
        DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria")
        DisposalPrice.objects.create(month=date(2026, 11, 1), port="suez")
        _, alex = self.call(self.login("alex"), "get", URL)
        _, viewer = self.call(self.login("viewer"), "get", URL)
        self.assertEqual([p["port"] for p in alex["prices"]], ["alexandria"])
        self.assertEqual(sorted(p["port"] for p in viewer["prices"]), ["alexandria", "suez"])

    def test_changes_are_in_the_history(self):
        self.call(self.login("admin"), "post", URL, PRICE)
        record = ChangeRecord.objects.get(object_type="disposalprice", action="create")
        self.assertEqual(record.username, "admin")


class PageCase(ApiTestCase):
    """Alexandria, November 2026, rate 50, the example prices."""

    PAGE = "/api/disposal/?from=2026-11-01&to=2026-11-30"

    def setUp(self):
        ExchangeRate.objects.create(month=date(2026, 11, 1), rate=Decimal("50"))
        self.call(self.login("admin"), "post", URL, PRICE)
        self.alex = self.login("alex")

    def put(self, vessel, data, client=None):
        return self.call(client or self.alex, "put", f"/api/disposal/{vessel.id}/", data)

    def page(self, client=None, query=""):
        return self.call(client or self.alex, "get", self.PAGE + query)[1]


def ids(data):
    return [r["vessel"]["id"] for r in data["rows"]]


class PageTests(PageCase):

    def test_figures_in_egp_and_usd(self):
        status, row = self.put(self.alex_vessel, {"garbage": "5", "sludge": "25"})
        self.assertEqual(status, 200)
        # garbage: revenue 250 + 2 × 60 = USD 370 (LE 18,500); cost 5,200 + 2 × 1,500 = LE 8,200 (USD 164)
        # sludge (the minimum): revenue USD 875 (LE 43,750); cost LE 11,000 (USD 220)
        self.assertEqual((row["revenue_egp"], row["cost_egp"], row["profit_egp"]), (62250.0, 19200.0, 43050.0))
        self.assertEqual((row["revenue_usd"], row["cost_usd"], row["profit_usd"]), (1245.0, 384.0, 861.0))
        self.assertEqual([item["label"] for item in row["lines"]], ["Garbage · 5 m³", "Sludge · 25 t"])
        self.assertFalse(row["rate_missing"] or row["price_missing"])
        self.assertEqual(self.page()["totals"]["profit_usd"], 861.0)

    def test_port_users_see_and_change_their_port_only(self):
        names = [r["vessel"]["name"] for r in self.page()["rows"]]
        self.assertIn(self.alex_vessel.name, names)
        self.assertNotIn(self.suez_vessel.name, names)
        status, _ = self.put(self.suez_vessel, {"garbage": "1"})
        self.assertEqual(status, 404)

    def test_hide_and_bring_back(self):
        self.put(self.alex_vessel, {"garbage": "5"})
        _, row = self.put(self.alex_vessel, {"hidden": True})
        self.assertEqual((row["hidden"], row["garbage"], row["revenue_egp"]), (True, None, 0.0))
        self.assertNotIn(self.alex_vessel.id, ids(self.page()))
        self.assertIn(self.alex_vessel.id, ids(self.page(query="&show=hidden")))
        self.put(self.alex_vessel, {"hidden": False})
        self.assertIn(self.alex_vessel.id, ids(self.page(query="&show=none")))
        self.assertNotIn(self.alex_vessel.id, ids(self.page(query="&show=with")))

    def test_filters(self):
        self.put(self.alex_vessel, {"sludge": "30"})
        self.assertEqual(ids(self.page(query="&show=with")), [self.alex_vessel.id])
        self.assertEqual(self.call(self.alex, "get", self.PAGE + "&show=odd"), (400, {"error": "Unknown filter."}))

    def test_bad_quantities_refused(self):
        for bad, message in (({"garbage": "-1"}, "Garbage (m³) must be 0 or more."),
                             ({"sludge": "x"}, "Sludge (t) must be a number."),
                             ({"hidden": "yes"}, "Hidden must be true or false."),
                             ({}, "Nothing to change.")):
            self.assertEqual(self.put(self.alex_vessel, bad), (400, {"error": message}))
        self.assertFalse(VesselDisposal.objects.exists())

    def test_missing_price_and_rate_are_flagged(self):
        _, row = self.put(self.suez_vessel, {"garbage": "5"}, client=self.login("admin"))
        self.assertTrue(row["price_missing"])
        self.assertEqual(row["revenue_egp"], 0.0)
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(date=date(2026, 12, 3))
        self.call(self.login("admin"), "post", URL, {**PRICE, "month": "2026-12"})  # a price, but no December rate
        _, row = self.put(self.alex_vessel, {"garbage": "5"})
        self.assertTrue(row["rate_missing"])
        self.assertEqual((row["revenue_usd"], row["revenue_egp"], row["cost_egp"], row["cost_usd"]),
                         (370.0, None, 8200.0, None))

    def test_totals_leave_out_flagged_rows_whole(self):
        self.put(self.alex_vessel, {"garbage": "5"})
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(date=date(2026, 12, 3))  # December: a price, no rate
        self.call(self.login("admin"), "post", URL, {**PRICE, "month": "2026-12"})
        totals = self.call(self.alex, "get", "/api/disposal/?from=2026-12-01&to=2026-12-31")[1]["totals"]
        self.assertEqual((totals["revenue_usd"], totals["cost_egp"], totals["profit_egp"]), (0.0, 0.0, 0.0))
        self.assertEqual(totals["rate_missing_rows"], 1)

    def test_quantities_for_a_hidden_vessel_are_refused(self):
        self.put(self.alex_vessel, {"hidden": True})
        self.assertEqual(self.put(self.alex_vessel, {"garbage": "5"}),
                         (400, {"error": "Bring the vessel back before entering quantities."}))

    def test_a_typed_zero_is_entered(self):
        self.put(self.alex_vessel, {"garbage": "0"})
        self.assertNotIn(self.alex_vessel.id, ids(self.page(query="&show=none")))
        self.assertNotIn(self.alex_vessel.id, ids(self.page(query="&show=with")))

    def test_changes_are_in_the_history(self):
        self.put(self.alex_vessel, {"garbage": "5"})
        self.assertTrue(ChangeRecord.objects.filter(object_type="vesseldisposal", username="alex").exists())


class CalculationsTests(PageCase):
    """Garbage & Sludge lines are on the Calculations page, with USD, but not in the vessel's own totals."""

    def test_lines_usd_and_not_in_vessel_totals(self):
        _, before = self.call(self.alex, "get", f"/api/vessels/{self.alex_vessel.id}/")
        self.put(self.alex_vessel, {"garbage": "5", "sludge": "25"})
        _, data = self.call(self.alex, "get", "/api/calculations/?from=2026-11-01&to=2026-11-30")
        rows = {row["label"]: row for row in data["rows"]}
        garbage = rows["Garbage · 5 m³"]
        self.assertEqual((garbage["kind"], garbage["revenue_egp"], garbage["cost_egp"]),
                         ("Garbage & Sludge", 18500.0, 8200.0))
        self.assertEqual((garbage["revenue_usd"], garbage["cost_usd"], garbage["profit_usd"]), (370.0, 164.0, 206.0))
        self.assertEqual(rows["Sludge · 25 t"]["profit_egp"], 32750.0)
        _, after = self.call(self.alex, "get", f"/api/vessels/{self.alex_vessel.id}/")
        self.assertEqual(after["total_profit_egp"], before["total_profit_egp"])

    def test_missing_price_line_is_listed(self):
        self.put(self.suez_vessel, {"sludge": "4"}, client=self.login("admin"))
        _, data = self.call(self.login("admin"), "get", "/api/calculations/?from=2026-11-01&to=2026-11-30")
        row = next(row for row in data["rows"] if row["kind"] == "Garbage & Sludge")
        self.assertTrue(row["price_missing"])
        self.assertEqual(data["totals"]["price_missing_lines"], 1)

"""Calculations: money on every service, the money lines behind every figure, and the Calculations page API."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from . import finance
from .logistics import booking_line
from .models import ExchangeRate, HotelStay, Service, Transfer, Vessel
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


class CalculationsApiTests(ApiTestCase):
    """ALEX SHIP (Alexandria, 13.11.2026): Fresh Water in USD at its own rate, Landing with 2 EGP entries,
    Certificates with USD revenue and no rate anywhere (the one flagged line), and a hotel stay checking in after
    the range. SUEZ SHIP: Fresh Water cost 10 EGP. No ExchangeRate rows."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Service.objects.create(vessel=cls.alex_vessel, service_type="Fresh Water", data={
            "quantity": 40, "cost": 2000, "costCurrency": "EGP", "revenue": 100, "revenueCurrency": "USD", "exchangeRate": 50})
        Service.objects.create(vessel=cls.alex_vessel, service_type="Landing", data={
            "entries": [{"cost": 10, "revenue": 15}, {"cost": 20, "revenue": 30}]})
        Service.objects.create(vessel=cls.alex_vessel, service_type="Certificates", data={
            "certName": "SOLAS", "revenue": 7, "revenueCurrency": "USD"})
        HotelStay.objects.create(vessel=cls.alex_vessel, hotel="HILTON", check_in=date(2026, 12, 5), nights=2,
                                 cost_per_night=Decimal("100"), revenue_per_night=Decimal("150"))

    def get(self, user, **params):
        response = self.login(user).get("/api/calculations/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def status(self, user, **params):
        return self.login(user).get("/api/calculations/", params).status_code

    def test_rows_and_totals(self):
        data = self.get("admin", **{"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria"})
        self.assertEqual(data["count"], 5)  # fresh water, 2 landing entries, certificates, the hotel stay after the range
        self.assertEqual(data["totals"]["rate_missing_lines"], 1)
        self.assertEqual(data["totals"]["lines"], 5)
        self.assertAlmostEqual(data["totals"]["profit_egp"], sum(r["profit_egp"] for r in data["rows"]), places=2)
        self.assertEqual(data["totals"]["profit_egp"], 3000 + 5 + 10 + 7 + 100)
        hotel = next(r for r in data["rows"] if r["kind"] == "Hotel stay")
        self.assertEqual((hotel["label"], hotel["cost_egp"], hotel["vessel"]["name"]), ("Hotel · HILTON · 2 nights", 200.0, "ALEX SHIP"))
        water = next(r for r in data["rows"] if r["kind"] == "Fresh Water")
        self.assertEqual((water["revenue"]["rate"], water["rate_source"], water["revenue"]["egp"]), (50.0, "own", 5000.0))

    def test_service_lines_match_the_vessel_figures(self):
        vessel = self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/")[1]
        rows = [r for r in self.get("admin", page_size=200)["rows"]
                if r["vessel"]["id"] == self.alex_vessel.id and r["kind"] not in ("Hotel stay", "Transfer")]
        self.assertAlmostEqual(sum(r["cost_egp"] for r in rows), vessel["total_cost_egp"], places=2)
        self.assertAlmostEqual(sum(r["profit_egp"] for r in rows), vessel["total_profit_egp"], places=2)

    def test_range_is_on_the_vessel_date(self):
        self.assertEqual(self.get("admin", **{"from": "2026-12-01", "to": "2026-12-31"})["count"], 0)

    def test_opr_is_exact_and_port_users_are_pinned(self):
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(opr="ARK")
        self.assertEqual(self.get("admin", opr="ark")["count"], 0)
        self.assertEqual({r["vessel"]["name"] for r in self.get("admin", opr="ARK")["rows"]}, {"ALEX SHIP"})
        self.assertEqual({r["vessel"]["port"] for r in self.get("alex", port="suez")["rows"]}, {"alexandria"})

    def test_every_role_can_read_and_totals_cover_every_page(self):
        page = self.get("viewer", page_size=1)
        self.assertEqual((len(page["rows"]), page["totals"]["lines"]), (1, page["count"]))
        self.assertEqual(page["count"], 6)  # ALEX SHIP's 5 + SUEZ SHIP's fresh water

    def test_sorting_and_bad_parameters(self):
        rows = self.get("admin", sort="profit", dir="desc")["rows"]
        self.assertEqual(rows[0]["kind"], "Fresh Water")
        for params in ({"sort": "price"}, {"page": "0"}, {"from": "x"}, {"dir": "up"}):
            self.assertEqual(self.status("admin", **params), 400, params)


    def test_the_opr_choices_are_the_oprs_in_range_and_scope(self):
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(opr="ARK")
        Vessel.objects.filter(pk=self.suez_vessel.pk).update(opr="MSK")
        self.assertEqual(self.get("admin", opr="ARK")["oprs"], ["ARK", "MSK"])  # not narrowed by the OPR filter itself
        self.assertEqual(self.get("alex")["oprs"], ["ARK"])                     # port users: their port only
        self.assertEqual(self.get("admin", **{"from": "2027-01-01"})["oprs"], [])


class CentAccuracyTests(ApiTestCase):
    """The lines a person sees must add up to the vessel's figures, to the cent."""

    def test_rows_add_up_to_the_vessel_total_with_usd_cents(self):
        ExchangeRate.objects.create(month=date(2026, 11, 1), rate=Decimal("47.35"))
        Service.objects.create(vessel=self.alex_vessel, service_type="Landing", data={"entries": [
            {"cost": 1.01, "costCurrency": "USD"}, {"cost": 1.01, "costCurrency": "USD"}]})
        vessel = self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/")[1]
        rows = [r for r in self.login("admin").get("/api/calculations/", {"page_size": 200}).json()["rows"]
                if r["vessel"]["id"] == self.alex_vessel.id]
        self.assertEqual([r["cost_egp"] for r in rows], [47.82, 47.82])
        self.assertEqual(round(sum(r["cost_egp"] for r in rows), 2), vessel["total_cost_egp"])

    def test_profit_is_rounded_revenue_minus_rounded_cost(self):
        [line] = finance.service_lines("Certificates", {"cost": 0.004, "revenue": 0.016}, None)
        self.assertEqual((line["cost_egp"], line["revenue_egp"], line["profit_egp"]), (0.0, 0.02, 0.02))
        self.assertEqual(finance.compute("Certificates", {"cost": 0.004, "revenue": 0.016}, None)["profit_egp"], 0.02)


class StatusColumnsTests(ApiTestCase):
    """Calculations rows carry the operations status and the accounting state; both filter the rows and the totals.
    ALEX SHIP: Fresh Water (completed, 10 / 30), Landing (in progress, 2 entries), Certificates (cancelled, revenue 7),
    a hotel stay; SUEZ SHIP: nothing."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.water = Service.objects.create(vessel=cls.alex_vessel, service_type="Fresh Water", status="completed",
                                           data={"cost": 10, "revenue": 30})
        cls.landing = Service.objects.create(vessel=cls.alex_vessel, service_type="Landing", data={
            "entries": [{"cost": 1, "revenue": 2}, {"cost": 3, "revenue": 4}]})
        cls.certs = Service.objects.create(vessel=cls.alex_vessel, service_type="Certificates", status="cancelled",
                                           cancel_reason="Owner", data={"certName": "SOLAS", "revenue": 7})
        cls.stay = HotelStay.objects.create(vessel=cls.alex_vessel, hotel="NILE", check_in=date(2026, 11, 13), nights=1,
                                            cost_per_night=Decimal("5"), revenue_per_night=Decimal("8"))

    def get(self, **params):
        response = self.login("viewer").get("/api/calculations/", {"port": "alexandria", **params})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def kinds(self, **params):
        return sorted(r["kind"] for r in self.get(**params)["rows"])

    def test_rows_carry_status_and_closed(self):
        rows = {r["kind"]: r for r in self.get()["rows"]}
        water = rows["Fresh Water"]
        self.assertEqual((water["status"], water["cancel_reason"], water["closed"], water["ref"]),
                         ("completed", "", False, {"kind": "service", "id": self.water.id}))
        self.assertEqual((rows["Certificates"]["status"], rows["Certificates"]["cancel_reason"]), ("cancelled", "Owner"))
        hotel = rows["Hotel stay"]
        self.assertEqual((hotel["status"], hotel["closed"], hotel["ref"]),
                         (None, False, {"kind": "hotel", "id": self.stay.id}))

    def test_status_filter_all_except_completed(self):
        self.assertEqual(self.kinds(status="in_progress,cancelled"), ["Certificates", "Landing", "Landing"])

    def test_status_filter_drops_bookings(self):
        self.assertNotIn("Hotel stay", self.kinds(status="in_progress,completed,cancelled"))

    def test_accounting_filter_open(self):
        HotelStay.objects.filter(pk=self.stay.pk).update(acct_closed=True)
        self.assertEqual(self.kinds(accounting="open"), ["Certificates", "Fresh Water", "Landing", "Landing"])
        self.assertEqual(self.kinds(accounting="closed"), ["Hotel stay"])
        self.assertEqual(len(self.kinds(accounting="open,closed")), 5)

    def test_totals_follow_filters_with_counts(self):
        Service.objects.filter(pk=self.water.pk).update(acct_closed=True)
        totals = self.get()["totals"]
        self.assertEqual((totals["open"], totals["closed"], totals["lines"]), (4, 1, 5))
        totals = self.get(status="in_progress")["totals"]
        self.assertEqual((totals["lines"], totals["cost_egp"], totals["revenue_egp"], totals["open"], totals["closed"]),
                         (2, 4.0, 6.0, 2, 0))

    def test_filter_values_refused(self):
        client = self.login("viewer")
        for params in ({"status": "done"}, {"accounting": "settled"}, {"status": "completed,x"}):
            self.assertEqual(client.get("/api/calculations/", params).status_code, 400, params)
        self.assertEqual(len(self.kinds(status="completed,,")), 1)
        self.assertEqual(len(self.kinds(accounting="")), 5)

    def test_multi_entry_service_rows_share_closed(self):
        Service.objects.filter(pk=self.landing.pk).update(acct_closed=True)
        landing = [r for r in self.get()["rows"] if r["kind"] == "Landing"]
        self.assertEqual([(r["closed"], r["ref"]["id"]) for r in landing], [(True, self.landing.id)] * 2)

    def test_disposal_row_ref(self):
        from .models import DisposalPrice, VesselDisposal

        DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria", garbage_revenue_min_qty=1,
                                     garbage_revenue_min=Decimal("100"))
        record = VesselDisposal.objects.create(vessel=self.alex_vessel, garbage=Decimal("1"))
        row = next(r for r in self.get()["rows"] if r["kind"] == "Garbage & Sludge")
        self.assertEqual((row["status"], row["ref"]), (None, {"kind": "disposal", "id": record.id}))

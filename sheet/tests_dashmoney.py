"""The Dashboard's Money view: revenue, cost and profit of the Calculations lines, by service, customer and month."""

from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from .models import Customer, DisposalPrice, HotelStay, Service, Ship, Transfer, Vessel, VesselDisposal
from .tests import ApiTestCase, make_user

URL = "/api/dashboard/money/"
NOV = {"from": "2026-11-01", "to": "2026-11-30"}


class DashboardMoneyTests(ApiTestCase):
    """ALEX SHIP (13.11, ship of A OWNERS): Fresh Water billed to B (cost 100 / revenue 250, agent DELTA), Crew Change
    with no billing party (revenue 300), a hotel stay (2 × 150 / 2 × 100), a transfer (cost 50 / revenue 80), garbage
    1 m³ at a 100 EGP minimum. OCT SHIP (20.10, no ship): Fresh Water revenue 40. SUEZ SHIP: Fresh Water cost 10."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.a = Customer.objects.create(name="A OWNERS")
        cls.b = Customer.objects.create(name="B MANAGERS")
        ship = Ship.objects.create(name="ALEX SHIP", customer=cls.a)
        Vessel.objects.filter(pk=cls.alex_vessel.pk).update(ship=ship)
        cls.water = Service.objects.create(
            vessel=cls.alex_vessel, service_type="Fresh Water", agent="DELTA", billing_party=cls.b,
            data={"cost": 100, "costCurrency": "EGP", "revenue": 250, "revenueCurrency": "EGP"})
        Service.objects.create(vessel=cls.alex_vessel, service_type="Crew Change", data={
            "onSigners": [], "offSigners": [], "revenue": 300, "revenueCurrency": "EGP"})
        HotelStay.objects.create(vessel=cls.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 13), nights=2,
                                 cost_per_night=Decimal("100"), revenue_per_night=Decimal("150"))
        Transfer.objects.create(vessel=cls.alex_vessel, from_place="airport", airport="CAI", to_place="port",
                                port_name="ALEXANDRIA", at=timezone.make_aware(datetime(2026, 11, 13, 8)),
                                cost=Decimal("50"), revenue=Decimal("80"))
        DisposalPrice.objects.create(month=date(2026, 11, 1), port="alexandria", garbage_revenue_min_qty=1,
                                     garbage_revenue_min=Decimal("100"), garbage_revenue_currency="EGP")
        VesselDisposal.objects.create(vessel=cls.alex_vessel, garbage=Decimal("1"))
        october = Vessel.objects.create(name="OCT SHIP", date=date(2026, 10, 20), port="alexandria")
        Service.objects.create(vessel=october, service_type="Fresh Water",
                               data={"revenue": 40, "revenueCurrency": "EGP"})
        make_user("nomoney", "alexandria", permissions=[], pages=["dashboard"])

    def get(self, user="admin", **params):
        response = self.login(user).get(URL, {**NOV, **params})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def by(self, data, key, name="kind"):
        return {row[name]: (row["revenue_egp"], row["cost_egp"], row["profit_egp"]) for row in data[key]}

    def test_totals_equal_calculations(self):
        for params in ({"port": "alexandria"}, {}, {"from": "2026-10-01"}):
            money = self.get(**params)["totals"]
            calc = self.login("admin").get("/api/calculations/", {**NOV, **params}).json()["totals"]
            self.assertEqual((money["revenue_egp"], money["cost_egp"], money["profit_egp"], money["lines"]),
                             (calc["revenue_egp"], calc["cost_egp"], calc["profit_egp"], calc["lines"]), params)

    def test_by_service_includes_bookings_and_garbage(self):
        data = self.get(port="alexandria")
        self.assertEqual(self.by(data, "by_service"), {
            "Fresh Water": (250.0, 100.0, 150.0), "Crew Change": (300.0, 0.0, 300.0),
            "Hotel stay": (300.0, 200.0, 100.0), "Transfer": (80.0, 50.0, 30.0),
            "Garbage & Sludge": (100.0, 0.0, 100.0)})
        kinds = [row["kind"] for row in data["by_service"]]
        self.assertEqual(kinds[-3:], ["Hotel stay", "Transfer", "Garbage & Sludge"])

    def test_by_customer_ship_customer_for_bookings(self):
        data = self.get(port="alexandria")
        self.assertEqual(self.by(data, "by_customer", "name"), {
            "A OWNERS": (300.0 + 300.0 + 80.0 + 100.0, 250.0, 530.0),  # crew change, hotel, transfer, garbage
            "B MANAGERS": (250.0, 100.0, 150.0)})
        self.assertEqual(data["by_customer"][0]["id"], self.a.id)  # highest revenue first

    def test_no_customer_last(self):
        data = self.get(**{"from": "2026-10-01"})
        self.assertEqual((data["by_customer"][-1]["id"], data["by_customer"][-1]["name"]), (None, "No customer"))

    def test_customer_filter(self):
        data = self.get(port="alexandria", customer=str(self.b.id))
        self.assertEqual(self.by(data, "by_service"), {"Fresh Water": (250.0, 100.0, 150.0)})
        none = self.get(customer="__none__", **{"from": "2026-10-01"})
        self.assertEqual({r["name"] for r in none["by_customer"]}, {"No customer"})

    def test_service_filter_hotel_stay(self):
        data = self.get(port="alexandria", service="Hotel stay")
        self.assertEqual(self.by(data, "by_service"), {"Hotel stay": (300.0, 200.0, 100.0)})
        self.assertEqual(self.login("admin").get(URL, {**NOV, "service": "Nope"}).status_code, 400)

    def test_agent_filter_drops_bookings(self):
        data = self.get(port="alexandria", agent="DELTA")
        self.assertEqual(self.by(data, "by_service"), {"Fresh Water": (250.0, 100.0, 150.0)})
        none = self.get(port="alexandria", agent="__none__")
        self.assertEqual(set(self.by(none, "by_service")), {"Crew Change"})

    def test_opr_filter(self):
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(opr="MSK")
        self.assertEqual(self.get(opr="MSK")["totals"]["lines"], 5)
        self.assertEqual(self.get(opr="ARK")["totals"]["lines"], 0)

    def test_months_zero_filled(self):
        Vessel.objects.create(name="JAN SHIP", date=date(2027, 1, 5), port="alexandria")
        Service.objects.create(vessel=Vessel.objects.get(name="JAN SHIP"), service_type="Fresh Water",
                               data={"revenue": 5, "revenueCurrency": "EGP"})
        data = self.get(**{"from": "2026-10-01", "to": "2027-01-31", "port": "alexandria"})
        self.assertEqual([m["month"] for m in data["months"]], ["2026-10", "2026-11", "2026-12", "2027-01"])
        self.assertEqual(data["months"][2]["revenue_egp"], 0)
        self.assertEqual(data["months"][0]["revenue_egp"], 40.0)

    def test_needs_money_view_403(self):
        self.assertEqual(self.login("nomoney").get(URL, NOV).status_code, 403)

    def test_port_user_sees_own_ports_only(self):
        kinds = self.get("alex")["by_service"]
        self.assertEqual(self.get("alex")["totals"]["cost_egp"], 350.0)  # the Suez Fresh Water's 10 left out
        self.assertTrue(kinds)

    def test_kinds_for_the_dropdown(self):
        self.assertEqual(self.get()["kinds"][-3:], ["Hotel stay", "Transfer", "Garbage & Sludge"])

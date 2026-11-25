"""Access rework piece 3: what money.edit (the forms' money boxes) and money.view (the overviews) hide."""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from . import crewbookings
from .constants import MULTI_TYPES, PAGE_KEYS, PERMISSION_KEYS
from .models import ChangeRecord, Customer, CustomerRate, ExchangeRate, Guest, HotelStay, Service, Transfer, Vessel
from .moneyaccess import keep_service_money, service_money_sent, strip_service_data
from .tests import FAST_HASHER, NEEDED, ApiTestCase, allow, make_user
from .tests_logistics import stay, trip
from .validators import UID_RE, clean_service_data

A, B, C, D = "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd"


def _entry(uid, cost, awb=""):
    return {"uid": uid, "awb": awb, "cost": cost, "costCurrency": "USD", "revenue": cost * 2, "revenueCurrency": "USD"}


class ServiceMoneyRuleTests(SimpleTestCase):
    def test_strip_single(self):
        data = {"quantity": 5, "cost": 10, "costCurrency": "USD", "revenue": 20, "revenueCurrency": "EGP",
                "exchangeRate": 50}
        self.assertEqual(strip_service_data("Fresh Water", data), {"quantity": 5})
        self.assertEqual(data["cost"], 10)  # a copy: the stored data is untouched

    def test_strip_multi_keeps_awb_weight_uid(self):
        data = {"entries": [{**_entry(A, 1, "123"), "weight": 4}], "exchangeRate": 50}
        self.assertEqual(strip_service_data("Delivery Parcels", data),
                         {"entries": [{"uid": A, "awb": "123", "weight": 4}]})

    def test_strip_crew_drops_broken_visa_only(self):
        member = {"uid": A, "name": "Ali", "needsHotel": True, "brokenVisa": {"cost": 5}}
        data = {"onSigners": [member], "offSigners": [{"uid": B, "name": "Omar"}], "cost": 3, "revenue": 4}
        self.assertEqual(strip_service_data("Crew Change", data),
                         {"onSigners": [{"uid": A, "name": "Ali", "needsHotel": True}],
                          "offSigners": [{"uid": B, "name": "Omar"}]})

    def test_strip_cash_to_master_is_empty(self):
        data = {"amount": 100, "amountCurrency": "USD", "shareMode": "percent", "percentage": 5, "fixedRevenue": None,
                "exchangeRate": None}
        self.assertEqual(strip_service_data("Cash to Master", data), {})

    def test_strip_note_keeps_the_note(self):
        self.assertEqual(strip_service_data("Others / Remarks", {"note": "x", "cost": 1}), {"note": "x"})

    def test_sent_detects_nested_keys(self):
        self.assertTrue(service_money_sent("Landing", {"entries": [{"cost": None}]}))
        self.assertTrue(service_money_sent("Crew Change", {"onSigners": [{"brokenVisa": {}}]}))
        self.assertTrue(service_money_sent("Fresh Water", {"exchangeRate": None}))
        self.assertTrue(service_money_sent("Cash to Master", {"shareMode": "fixed"}))
        self.assertFalse(service_money_sent("Delivery Parcels", {"entries": [{"awb": "1", "weight": 2}]}))
        self.assertFalse(service_money_sent("Fresh Water", {"quantity": 3}))
        self.assertFalse(service_money_sent("Fresh Water", None))

    def test_keep_matches_entries_by_uid(self):
        stored = {"entries": [_entry(A, 1), _entry(B, 2), _entry(C, 3)], "exchangeRate": 48}
        cleaned = clean_service_data("Landing", {"entries": [{"uid": A}, {"uid": C}, {"uid": D}]})
        kept = keep_service_money("Landing", cleaned, "Landing", stored)
        self.assertEqual([e["cost"] for e in kept["entries"]], [1, 3, None])
        self.assertEqual([e["revenue"] for e in kept["entries"]], [2, 6, None])
        self.assertEqual(kept["entries"][2]["costCurrency"], "EGP")
        self.assertEqual(kept["exchangeRate"], 48)

    def test_keep_matches_crew_by_uid(self):
        stored = {"onSigners": [{"uid": A, "name": "Ali", "brokenVisa": {"cost": 5, "costCurrency": "USD",
                                                                          "revenue": 9, "revenueCurrency": "USD"}}],
                  "offSigners": [], "cost": 3, "costCurrency": "USD", "revenue": 4, "revenueCurrency": "EGP",
                  "exchangeRate": None}
        cleaned = clean_service_data("Crew Change", {"onSigners": [{"uid": B, "name": "New"},
                                                                   {"uid": A, "name": "Ali S"}]})
        kept = keep_service_money("Crew Change", cleaned, "Crew Change", stored)
        self.assertEqual(kept["onSigners"][1]["brokenVisa"]["revenue"], 9)
        self.assertEqual(kept["onSigners"][1]["name"], "Ali S")
        self.assertIsNone(kept["onSigners"][0]["brokenVisa"]["cost"])
        self.assertEqual((kept["cost"], kept["costCurrency"], kept["revenue"]), (3, "USD", 4))

    def test_keep_type_change_keeps_nothing(self):
        cleaned = clean_service_data("Landing", {"entries": [{"uid": A}]})
        self.assertEqual(keep_service_money("Landing", cleaned, "Fresh Water", {"cost": 9}), cleaned)
        self.assertEqual(keep_service_money("Landing", cleaned, "Landing", None), cleaned)

    def test_keep_unchanged_save_equals_stored(self):
        stored = clean_service_data("Cash to Master", {"amount": 100, "shareMode": "fixed", "fixedRevenue": 7})
        cleaned = clean_service_data("Cash to Master", strip_service_data("Cash to Master", stored))
        self.assertEqual(keep_service_money("Cash to Master", cleaned, "Cash to Master", stored), stored)

    def test_multi_entries_get_stable_uids(self):
        cleaned = clean_service_data("Landing", {"entries": [{"uid": "abcdef012345"}, {"uid": "abcdef012345"}, {}]})
        uids = [e["uid"] for e in cleaned["entries"]]
        self.assertEqual(uids[0], "abcdef012345")
        self.assertEqual(len(set(uids)), 3)
        self.assertTrue(all(UID_RE.match(uid) for uid in uids))


class EntryUidMigrationTests(TransactionTestCase):
    def test_migration_0026_gives_entries_uids(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("sheet", "0025_profile_permissions")])
        old = executor.loader.project_state([("sheet", "0025_profile_permissions")]).apps
        OldVessel, OldService = old.get_model("sheet", "Vessel"), old.get_model("sheet", "Service")
        vessel = OldVessel.objects.create(name="OLD", port="alexandria", date=date(2026, 1, 5))
        landing = OldService.objects.create(vessel=vessel, service_type="Landing",
                                            data={"entries": [{"awb": "1", "cost": 5}, {"awb": "2"}]})
        water = OldService.objects.create(vessel=vessel, service_type="Fresh Water", data={"cost": 5})
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        entries = Service.objects.get(pk=landing.pk).data["entries"]
        self.assertEqual(len({e["uid"] for e in entries}), 2)
        self.assertTrue(all(UID_RE.match(e["uid"]) for e in entries))
        self.assertEqual(entries[0]["cost"], 5)
        self.assertEqual(Service.objects.get(pk=water.pk).data, {"cost": 5})
        self.assertIn("Landing", MULTI_TYPES)


# ---- Task 2: vessels and services -------------------------------------------------------------------------------

NO_MONEY_PAGES = ("calculations", "rates", "history")
OVERVIEW_KEYS = {"total_cost_egp", "total_profit_egp", "calc"}
BOX_KEYS = {"cost", "costCurrency", "revenue", "revenueCurrency", "exchangeRate", "brokenVisa", "amount",
            "shareMode", "percentage", "fixedRevenue"}


def all_but(keys, *gone):
    return [key for key in keys if key not in gone]


def keys_in(value):
    """Every dict key anywhere inside a JSON value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_in(v)}
    return set()


def service_keys(vessel_json):
    return keys_in([s["data"] for s in vessel_json["services"]])


class MoneyUsers(ApiTestCase):
    """edit_only: money.edit, no money.view; view_only: money.view, no money.edit; neither. A vessel dated today with
    a three-line Landing, a Crew Change with a broken visa and a Fresh Water service, and a month rate of 50."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_user("edit_only", "alexandria", permissions=all_but(PERMISSION_KEYS, "money.view", "history.view"),
                  pages=all_but(PAGE_KEYS, *NO_MONEY_PAGES))
        make_user("view_only", "alexandria", permissions=all_but(PERMISSION_KEYS, "money.edit"))
        make_user("neither", "alexandria", permissions=all_but(PERMISSION_KEYS, "money.edit", "money.view",
                                                               "history.view"),
                  pages=all_but(PAGE_KEYS, *NO_MONEY_PAGES))
        cls.vessel = Vessel.objects.create(name="TODAY SHIP", date=timezone.localdate(), port="alexandria")
        ExchangeRate.objects.create(month=cls.vessel.date.replace(day=1), rate=50)
        cls.landing = Service.objects.create(vessel=cls.vessel, service_type="Landing", data=clean_service_data(
            "Landing", {"entries": [_entry(A, 1, "1"), _entry(B, 2, "2"), _entry(C, 3, "3")]}))
        cls.crew = Service.objects.create(vessel=cls.vessel, service_type="Crew Change", data=clean_service_data(
            "Crew Change", {"onSigners": [{"uid": D, "name": "ALI", "brokenVisa": {"cost": 5, "revenue": 9}}],
                            "cost": 30, "revenue": 40}))
        cls.water = Service.objects.create(vessel=cls.vessel, service_type="Fresh Water",
                                           data=clean_service_data("Fresh Water", {"quantity": 7, "cost": 10}))
        crewbookings.sync(cls.vessel)  # the crew's draft bookings, as an API save would have made them


@FAST_HASHER
class VesselMoneyApiTests(MoneyUsers):
    def vessel_routes(self, who):
        """Every route that sends this vessel's JSON: list, detail, alerts, and the write responses."""
        client = self.login(who)
        url = f"/api/vessels/{self.vessel.pk}/"
        found = {}
        body = self.call(client, "get", "/api/vessels/")[1]
        found["list"] = next(v for v in body["vessels"] if v["id"] == self.vessel.pk)
        found["totals"] = body["totals"]
        found["detail"] = self.call(client, "get", url)[1]
        found["alerts"] = next(v for v in self.call(client, "get", "/api/vessels/alerts/")[1]["today"]
                               if v["id"] == self.vessel.pk)
        found["vessel put"] = self.call(client, "put", url, {**found["detail"], **NEEDED})[1]
        found["service post"] = self.call(client, "post", f"{url}services/",
                                          {"type": "Certificates", "data": {"certName": "X"}})[1]
        water = next(s for s in found["detail"]["services"] if s["id"] == self.water.pk)
        found["service put"] = self.call(client, "put", f"/api/services/{self.water.pk}/",
                                         {"type": "Fresh Water", "data": water["data"]})[1]
        return found

    def test_every_vessel_route_hides_overviews_without_view(self):
        for route, body in self.vessel_routes("edit_only").items():
            if route == "totals":
                self.assertNotIn("cost_egp", body)
                self.assertNotIn("profit_egp", body)
                continue
            self.assertEqual(keys_in(body) & {"total_cost_egp", "total_profit_egp"}, set(), route)
            self.assertFalse(any("calc" in s for s in body["services"]), route)
            self.assertIn("cost", service_keys(body), route)
            self.assertEqual(body["rate"], 50.0, route)

    def test_every_vessel_route_hides_boxes_without_edit(self):
        for route, body in self.vessel_routes("view_only").items():
            if route == "totals":
                self.assertIn("profit_egp", body)
                continue
            self.assertIn("total_profit_egp", body, route)
            self.assertTrue(all("calc" in s for s in body["services"]), route)
            keys = service_keys(body)
            self.assertEqual(keys & BOX_KEYS, set(), route)
            self.assertLessEqual({"quantity", "awb", "uid", "name"}, keys, route)

    def test_neither_gets_no_rate(self):
        body = self.call(self.login("neither"), "get", f"/api/vessels/{self.vessel.pk}/")[1]
        self.assertNotIn("rate", body)
        self.assertEqual(keys_in(body) & (OVERVIEW_KEYS | BOX_KEYS), set())

    def test_sort_by_money_needs_view(self):
        for path in ("/api/vessels/?sort=total_cost_egp", "/export.csv?sort=total_cost_egp"):
            self.assertEqual(self.login("edit_only").get(path).status_code, 403, path)
            self.assertEqual(self.login("admin").get(path).status_code, 200, path)

    def test_csv_drops_money_columns(self):
        head = self.login("edit_only").get("/export.csv").content.decode("utf-8-sig").splitlines()[0]
        self.assertNotIn("Total Cost LE", head)
        self.assertNotIn("Total Profit LE", head)
        self.assertIn("Services", head)
        admin = self.login("admin").get("/export.csv").content.decode("utf-8-sig").splitlines()[0]
        self.assertIn("Total Profit LE", admin)

    def put_as_sent(self, who, service, change=None, client=None, **extra):
        """GET the vessel as `who`, then PUT the service back as it was sent (after `change`)."""
        client = client or self.login(who)
        body = self.call(client, "get", f"/api/vessels/{self.vessel.pk}/")[1]
        sent = next(s for s in body["services"] if s["id"] == service.pk)
        data = change(sent["data"]) if change else sent["data"]
        return self.call(client, "put", f"/api/services/{service.pk}/", {"type": sent["type"], "data": data, **extra})

    def test_save_without_money_keeps_it_and_changes_nothing(self):
        client = self.login("view_only")  # signing in writes History of its own
        for service in (self.landing, self.crew, self.water):
            before, records = Service.objects.get(pk=service.pk), ChangeRecord.objects.count()
            self.assertEqual(self.put_as_sent("view_only", service, client=client)[0], 200)
            after = Service.objects.get(pk=service.pk)
            self.assertEqual(after.data, before.data, service.service_type)
            self.assertEqual(after.version, before.version, service.service_type)
            self.assertEqual(ChangeRecord.objects.count(), records, service.service_type)

    def test_removing_a_line_keeps_the_others_money(self):
        def drop_middle(data):
            return {**data, "entries": [data["entries"][0], data["entries"][2]]}

        self.assertEqual(self.put_as_sent("view_only", self.landing, drop_middle)[0], 200)
        entries = Service.objects.get(pk=self.landing.pk).data["entries"]
        self.assertEqual([(e["uid"], e["cost"], e["revenue"]) for e in entries], [(A, 1, 2), (C, 3, 6)])

    def test_sending_money_without_edit_is_403(self):
        changes = [
            (self.water, lambda d: {**d, "cost": 99}),
            (self.landing, lambda d: {**d, "entries": [{**d["entries"][0], "revenue": 99}]}),
            (self.crew, lambda d: {**d, "onSigners": [{**d["onSigners"][0], "brokenVisa": {"cost": 99}}]}),
        ]
        for service, change in changes:
            before = Service.objects.get(pk=service.pk).data
            self.assertEqual(self.put_as_sent("view_only", service, change)[0], 403, service.service_type)
            self.assertEqual(Service.objects.get(pk=service.pk).data, before)
        status, _ = self.call(self.login("view_only"), "post", f"/api/vessels/{self.vessel.pk}/services/",
                              {"type": "Fresh Water", "data": {"cost": 5}})
        self.assertEqual(status, 403)

    def test_new_service_without_edit_has_no_money(self):
        status, _ = self.call(self.login("view_only"), "post", f"/api/vessels/{self.vessel.pk}/services/",
                              {"type": "Fresh Water", "data": {"quantity": 3}})
        self.assertEqual(status, 201)
        data = Service.objects.filter(vessel=self.vessel, service_type="Fresh Water").latest("id").data
        self.assertEqual((data["quantity"], data["cost"]), (3, None))

    def test_cancel_bookings_keeps_money_without_edit(self):
        for who, kept in (("view_only", True), ("admin", False)):
            HotelStay.objects.all().delete()
            Service.objects.filter(pk=self.crew.pk).update(status="in_progress", cancel_reason="")
            stay = HotelStay.objects.create(vessel=self.vessel, hotel="HILTON", check_in=self.vessel.date, nights=1,
                                            cost_per_night=100, revenue_per_night=100, draft=False)
            Guest.objects.create(stay=stay, name="ALI", crew_uid=D)
            status, _ = self.put_as_sent(who, self.crew, status="cancelled", cancel_reason="Owner",
                                         cancel_bookings=[{"kind": "hotel", "id": stay.pk}])
            self.assertEqual(status, 200, who)
            stay.refresh_from_db()
            self.assertTrue(stay.cancelled, who)
            self.assertEqual(stay.cost_per_night == 100, kept, who)


# ---- Task 3: bookings, Garbage & Sludge, customers, receipt ---------------------------------------------------

BOOKING_BOXES = {"cost", "revenue", "cost_per_night", "revenue_per_night", "cost_currency", "revenue_currency",
                 "exchange_rate"}


@FAST_HASHER
class FormMoneyApiTests(MoneyUsers):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        allow("hotel", "HILTON")
        allow("airport", "BORG EL ARAB")
        cls.hotel = HotelStay.objects.create(vessel=cls.vessel, hotel="HILTON", check_in=cls.vessel.date, nights=2,
                                             cost_per_night=80, cost_currency="USD", revenue_per_night=100,
                                             exchange_rate=49)
        Guest.objects.create(stay=cls.hotel, name="AHMED TEST")
        cls.car = Transfer.objects.create(vessel=cls.vessel, from_place="airport", to_place="hotel",
                                          airport="BORG EL ARAB", hotel="HILTON",
                                          at=timezone.now().replace(second=0, microsecond=0), cost=30,
                                          revenue=45)
        Guest.objects.create(transfer=cls.car, name="AHMED TEST")
        cls.customer = Customer.objects.create(name="Blue Owners")
        CustomerRate.objects.create(customer=cls.customer, service_type="Fresh Water", amount=50, currency="USD")

    def booking_routes(self, client):
        found = []
        for kind, obj, new in (("hotels", self.hotel, stay(vessel=self.vessel.pk)),
                               ("transfers", self.car, trip(vessel=self.vessel.pk))):
            url = f"/api/{kind}/{obj.pk}/"
            found += self.call(client, "get", f"/api/{kind}/")[1]["bookings"]
            detail = self.call(client, "get", url)[1]
            found += [detail, self.call(client, "put", url, detail)[1], self.call(client, "post", f"/api/{kind}/", new)[1]]
        return found

    def test_booking_routes_hide_money_without_edit(self):
        for row in self.booking_routes(self.login("view_only")):
            self.assertEqual(set(row) & BOOKING_BOXES, set(), row)
        for row in self.booking_routes(self.login("edit_only")):
            self.assertTrue(set(row) & BOOKING_BOXES, row)

    def test_booking_save_without_money_keeps_it(self):
        client = self.login("view_only")
        for kind, obj in (("hotels", self.hotel), ("transfers", self.car)):
            url = f"/api/{kind}/{obj.pk}/"
            # Only the booking's own records: every booking save rewrites its guests (and their History) anyway.
            own = ChangeRecord.objects.filter(object_type=type(obj).__name__.lower(), object_id=obj.pk)
            records, version = own.count(), type(obj).objects.get(pk=obj.pk).version
            self.assertEqual(self.call(client, "put", url, self.call(client, "get", url)[1])[0], 200)
            after = type(obj).objects.get(pk=obj.pk)
            self.assertEqual((after.version, own.count()), (version, records), kind)
        self.hotel.refresh_from_db()
        self.assertEqual((self.hotel.cost_per_night, self.hotel.cost_currency, self.hotel.exchange_rate),
                         (80, "USD", 49))

    def test_new_booking_without_edit_has_no_money(self):
        status, row = self.call(self.login("view_only"), "post", "/api/hotels/", stay(vessel=self.vessel.pk))
        self.assertEqual(status, 201, row)
        made = HotelStay.objects.get(pk=row["id"])
        self.assertEqual((made.cost_per_night, made.cost_currency, made.revenue_per_night), (None, "EGP", None))

    def test_booking_money_sent_without_edit_is_403(self):
        client = self.login("view_only")
        url = f"/api/hotels/{self.hotel.pk}/"
        detail = self.call(client, "get", url)[1]
        self.assertEqual(self.call(client, "put", url, {**detail, "cost_per_night": 1})[0], 403)
        self.assertEqual(self.call(client, "post", "/api/transfers/",
                                   trip(vessel=self.vessel.pk, exchange_rate=None))[0], 403)
        self.hotel.refresh_from_db()
        self.assertEqual(self.hotel.cost_per_night, 80)

    def test_disposal_rows_and_totals(self):
        figures = {"revenue_egp", "cost_egp", "profit_egp", "revenue_usd", "rate_missing", "price_missing"}
        edit = self.call(self.login("edit_only"), "get", "/api/disposal/")[1]
        self.assertNotIn("totals", edit)
        self.assertTrue(all(figures <= set(r) for r in edit["rows"]))
        view = self.call(self.login("view_only"), "get", "/api/disposal/")[1]
        self.assertIn("totals", view)
        self.assertTrue(all(not figures & set(r) and "garbage" in r for r in view["rows"]))
        row = self.call(self.login("view_only"), "put", f"/api/disposal/{self.vessel.pk}/", {"garbage": 3})[1]
        self.assertEqual((row["garbage"], set(row) & figures), (3.0, set()))
        row = self.call(self.login("edit_only"), "put", f"/api/disposal/{self.vessel.pk}/", {"garbage": 4})[1]
        self.assertLessEqual(figures, set(row))

    def test_customer_rates_hidden_and_kept(self):
        client = self.login("view_only")
        listed = self.call(client, "get", "/api/customers/")[1]["customers"]
        self.assertTrue(all("rates" not in c for c in listed))
        url = f"/api/customers/{self.customer.pk}/"
        body = {"name": "Blue Owners 2", "notes": "", "contacts": []}
        status, saved = self.call(client, "put", url, body)
        self.assertEqual(status, 200, saved)
        self.assertNotIn("rates", saved)
        self.assertEqual(self.customer.rates.get().amount, 50)
        rates = {"Fresh Water": {"amount": 50, "currency": "USD"}}
        self.assertEqual(self.call(client, "put", url, {**body, "rates": rates})[0], 403)
        self.assertEqual(self.call(client, "post", "/api/customers/", {**body, "name": "New"})[0], 201)
        self.assertIn("rates", self.call(self.login("edit_only"), "get", "/api/customers/")[1]["customers"][0])

    def test_receipt_prefill_amounts_need_edit(self):
        Service.objects.filter(pk=self.water.pk).update(data=clean_service_data(
            "Fresh Water", {"quantity": 7, "revenue": 120, "revenueCurrency": "USD"}))
        url = f"/api/services/{self.water.pk}/receipt/"
        self.assertEqual(self.call(self.login("view_only"), "get", url)[1]["receipt"]["services"], "Fresh Water")
        self.assertEqual(self.call(self.login("edit_only"), "get", url)[1]["receipt"]["services"],
                         "Fresh Water with cost $120")

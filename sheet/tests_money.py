"""Access rework piece 3: what money.edit (the forms' money boxes) and money.view (the overviews) hide."""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from .constants import MULTI_TYPES
from .models import Service
from .moneyaccess import keep_service_money, service_money_sent, strip_service_data
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

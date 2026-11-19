"""Crew members: uid, Needs hotel, broken visa; vessel date = sailing date; automatic draft bookings; alerts."""

from django.test import SimpleTestCase

from . import finance
from .errors import BadRequest
from .tests import ApiTestCase
from .validators import UID_RE, clean_service_data


def crew(on=(), off=(), **money):
    return clean_service_data("Crew Change", {"onSigners": list(on), "offSigners": list(off), **money})


class CrewDataTests(SimpleTestCase):
    def test_new_member_gets_uid(self):
        member = crew(on=[{"name": "A"}])["onSigners"][0]
        self.assertRegex(member["uid"], UID_RE)

    def test_valid_uid_kept_duplicate_replaced(self):
        data = crew(on=[{"name": "A", "uid": "abcdef123456"}], off=[{"name": "B", "uid": "abcdef123456"},
                                                                   {"name": "C", "uid": "XYZ"}])
        self.assertEqual(data["onSigners"][0]["uid"], "abcdef123456")
        self.assertRegex(data["offSigners"][0]["uid"], UID_RE)
        self.assertNotEqual(data["offSigners"][0]["uid"], "abcdef123456")
        self.assertRegex(data["offSigners"][1]["uid"], UID_RE)

    def test_needs_hotel_is_bool(self):
        data = crew(on=[{"name": "A", "needsHotel": "yes"}, {"name": "B"}])
        self.assertIs(data["onSigners"][0]["needsHotel"], True)
        self.assertIs(data["onSigners"][1]["needsHotel"], False)

    def test_broken_visa_on_signers_only(self):
        visa = {"cost": "50", "costCurrency": "USD"}
        data = crew(on=[{"name": "A", "brokenVisa": visa}], off=[{"name": "B", "brokenVisa": visa}])
        self.assertEqual(data["onSigners"][0]["brokenVisa"]["cost"], 50.0)
        self.assertEqual(data["onSigners"][0]["brokenVisa"]["costCurrency"], "USD")
        self.assertIsNone(data["onSigners"][0]["brokenVisa"]["revenue"])
        self.assertNotIn("brokenVisa", data["offSigners"][0])

    def test_negative_broken_visa_refused(self):
        with self.assertRaises(BadRequest):
            crew(on=[{"name": "A", "brokenVisa": {"cost": -1}}])

    def test_broken_visa_adds_money_lines(self):
        visa = {"cost": 10, "costCurrency": "USD", "revenue": 20, "revenueCurrency": "USD"}
        data = crew(on=[{"name": "J SMITH", "brokenVisa": visa}], cost=100, costCurrency="EGP")
        result = finance.compute("Crew Change", data, 50)
        self.assertEqual((result["cost_egp"], result["revenue_egp"]), (600, 1000))
        labels = [line["label"] for line in finance.service_lines("Crew Change", data, 50)]
        self.assertIn("Broken visa · J SMITH", labels)

    def test_zero_broken_visa_has_no_line(self):
        data = crew(on=[{"name": "J SMITH", "brokenVisa": {"cost": 0}}], cost=100)
        labels = [line["label"] for line in finance.service_lines("Crew Change", data, 50)]
        self.assertEqual(len(labels), 1)


class SailingDateTests(ApiTestCase):
    def setUp(self):
        self.alex = self.login("alex")

    def put(self, **times):
        payload = {"name": "ALEX SHIP", "date": "2026-11-13", **times}
        return self.call(self.alex, "put", f"/api/vessels/{self.alex_vessel.id}/", payload)

    def test_sailing_time_sets_vessel_date(self):
        status, vessel = self.put(arrival_at="2026-11-13T08:00", sailing_at="2026-11-15T23:30")
        self.assertEqual((status, vessel["date"]), (200, "2026-11-15"))

    def test_sailing_dates_are_cairo_days(self):
        self.assertEqual(self.put(sailing_at="2026-11-30T23:30")[1]["date"], "2026-11-30")
        status, vessel = self.put(sailing_at="2026-12-01T00:10")
        self.assertEqual((status, vessel["date"]), (200, "2026-12-01"))

    def test_without_sailing_posted_date_kept(self):
        self.assertEqual(self.put(arrival_at="2026-11-13T08:00")[1]["date"], "2026-11-13")

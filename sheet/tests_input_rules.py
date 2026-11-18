"""Tighter input rules: list values come from Master data, service numbers are real and never negative, too-long
text is refused with a message instead of being cut."""

from datetime import date

from .models import HotelStay, Option, Service, Vessel
from .tests import ApiTestCase


class InputRulesData(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for kind, value, port in [
            ("opr", "ARK", ""), ("poc", "ALY", ""), ("agent", "DELTA SHIPPING", ""),
            ("agent", "SUEZ AGENCY", "suez"), ("hotel", "HILTON", ""), ("airport", "BORG EL ARAB", "alexandria"),
            ("port", "DEKHEILA", "alexandria"),
        ]:
            Option.objects.get_or_create(kind=kind, value=value, port=port)

    def setUp(self):
        self.alex = self.login("alex")
        self.admin = self.login("admin")

    def vessel(self, client=None, **fields):
        payload = {"name": "RULE SHIP", "date": "2026-11-13", **fields}
        return self.call(client or self.alex, "post", "/api/vessels/", payload)

    def service(self, data, agent="", vessel=None, service_type="Fresh Water"):
        vessel = vessel or self.alex_vessel
        payload = {"type": service_type, "agent": agent, "data": data}
        return self.call(self.alex, "post", f"/api/vessels/{vessel.id}/services/", payload)


class MasterDataListTests(InputRulesData):
    def test_vessel_values_from_the_lists_are_accepted(self):
        status, _ = self.vessel(opr="ARK", poc="ALY", arrival_agent="DELTA SHIPPING", sailing_agent="DELTA SHIPPING")
        self.assertEqual(status, 201)

    def test_empty_list_values_are_still_allowed(self):
        self.assertEqual(self.vessel(opr="", poc="", arrival_agent="", sailing_agent="")[0], 201)

    def test_vessel_value_not_in_the_list_is_refused(self):
        for field in ("opr", "poc", "arrival_agent", "sailing_agent"):
            with self.subTest(field=field):
                status, body = self.vessel(**{field: "MADE UP"})
                self.assertEqual(status, 400)
                self.assertIn("Master data", body["error"])
        self.assertFalse(Vessel.objects.filter(name="RULE SHIP").exists())

    def test_another_ports_value_is_refused(self):
        status, _ = self.vessel(arrival_agent="SUEZ AGENCY")  # alex is pinned to Alexandria
        self.assertEqual(status, 400)

    def test_admin_may_use_a_value_of_the_vessels_own_port(self):
        self.assertEqual(self.vessel(self.admin, port="suez", arrival_agent="SUEZ AGENCY")[0], 201)

    def test_a_value_already_saved_stays_allowed(self):
        vessel = Vessel.objects.create(name="OLD", date=date(2026, 11, 13), port="alexandria", opr="OLD OPR")
        status, _ = self.call(self.alex, "put", f"/api/vessels/{vessel.id}/",
                              {"name": "OLD RENAMED", "date": "2026-11-13", "opr": "OLD OPR"})
        self.assertEqual(status, 200)
        vessel.refresh_from_db()
        self.assertEqual((vessel.name, vessel.opr), ("OLD RENAMED", "OLD OPR"))

    def test_service_agent_must_be_in_the_list(self):
        self.assertEqual(self.service({"cost": 10}, agent="DELTA SHIPPING")[0], 201)
        status, body = self.service({"cost": 10}, agent="NOBODY")
        self.assertEqual(status, 400)
        self.assertIn("Master data", body["error"])

    def test_service_keeps_its_saved_agent(self):
        service = Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water", agent="GONE AGENT")
        status, _ = self.call(self.alex, "put", f"/api/services/{service.id}/",
                              {"type": "Fresh Water", "agent": "GONE AGENT", "data": {"cost": 5}})
        self.assertEqual(status, 200)

    def test_booking_hotel_airport_and_port_must_be_in_the_lists(self):
        guests = [{"name": "ahmed"}]
        stay = {"vessel": self.alex_vessel.id, "check_in": "2026-11-14", "nights": 1, "guests": guests}
        self.assertEqual(self.call(self.alex, "post", "/api/hotels/", {**stay, "hotel": "HILTON"})[0], 201)
        self.assertEqual(self.call(self.alex, "post", "/api/hotels/", {**stay, "hotel": "NO SUCH HOTEL"})[0], 400)
        trip = {"vessel": self.alex_vessel.id, "from_place": "airport", "to_place": "port", "at": "2026-11-14T10:00",
                "guests": guests}
        good = {**trip, "airport": "BORG EL ARAB", "port_name": "DEKHEILA"}
        self.assertEqual(self.call(self.alex, "post", "/api/transfers/", good)[0], 201)
        self.assertEqual(self.call(self.alex, "post", "/api/transfers/", {**good, "airport": "CAIRO"})[0], 400)
        self.assertEqual(self.call(self.alex, "post", "/api/transfers/", {**good, "port_name": "NOWHERE"})[0], 400)

    def test_booking_keeps_its_saved_hotel(self):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="CLOSED HOTEL", check_in=date(2026, 11, 14),
                                        nights=1)
        payload = {"hotel": "CLOSED HOTEL", "check_in": "2026-11-14", "nights": 2, "guests": [{"name": "ahmed"}]}
        self.assertEqual(self.call(self.alex, "put", f"/api/hotels/{stay.id}/", payload)[0], 200)


class ServiceNumberTests(InputRulesData):
    def assert_refused(self, data, service_type="Fresh Water", words="0 or more"):
        status, body = self.service(data, service_type=service_type)
        self.assertEqual(status, 400, data)
        self.assertIn(words, body["error"])

    def test_negative_amounts_are_refused(self):
        self.assert_refused({"cost": -1})
        self.assert_refused({"revenue": -5})
        self.assert_refused({"quantity": -2})
        self.assert_refused({"note": "x", "cost": -1}, "Others / Remarks")
        self.assert_refused({"amount": -100}, "Cash to Master")
        self.assert_refused({"entries": [{"cost": 1}, {"revenue": -3}]}, "Delivery Parcels")
        self.assert_refused({"entries": [{"weight": -1}]}, "Delivery Parcels")

    def test_text_where_a_number_belongs_is_refused_not_dropped(self):
        self.assert_refused({"cost": "12a"}, words="number")
        self.assert_refused({"quantity": "lots"}, words="number")
        self.assert_refused({"cost": True}, words="number")
        self.assert_refused({"cost": "NaN"}, words="number")
        self.assert_refused({"cost": 1e12}, words="too large")

    def test_negative_exchange_rate_is_refused(self):
        self.assert_refused({"cost": 1, "exchangeRate": -50}, words="Exchange rate")

    def test_percentage_must_be_0_to_100(self):
        self.assert_refused({"amount": 100, "percentage": 150}, "Cash to Master", words="Percentage")
        self.assert_refused({"amount": 100, "percentage": -1}, "Cash to Master", words="Percentage")

    def test_good_numbers_and_empty_fields_are_saved(self):
        status, _ = self.service({"cost": "1500.50", "revenue": 0, "quantity": "", "exchangeRate": 49.5})
        self.assertEqual(status, 201)
        data = Service.objects.filter(vessel=self.alex_vessel).latest("id").data
        self.assertEqual((data["cost"], data["revenue"], data["quantity"], data["exchangeRate"]),
                         (1500.5, 0.0, None, 49.5))
        self.assertEqual(self.service({"amount": 100, "percentage": 5}, service_type="Cash to Master")[0], 201)


class TooLongTextTests(InputRulesData):
    def test_too_long_vessel_name_is_refused_with_the_limit(self):
        status, body = self.vessel(name="X" * 121)
        self.assertEqual(status, 400)
        self.assertIn("120", body["error"])
        self.assertEqual(self.vessel(name="X" * 120)[0], 201)

    def test_too_long_service_text_is_refused(self):
        self.assertEqual(self.service({"note": "n" * 1001}, service_type="Others / Remarks")[0], 400)
        self.assertEqual(self.service({"entries": [{"awb": "A" * 61}]}, service_type="Delivery Parcels")[0], 400)

    def test_too_long_guest_name_is_refused(self):
        payload = {"vessel": self.alex_vessel.id, "hotel": "HILTON", "check_in": "2026-11-14", "nights": 1,
                   "guests": [{"name": "G" * 121}]}
        self.assertEqual(self.call(self.alex, "post", "/api/hotels/", payload)[0], 400)

    def test_too_long_summary_note_is_refused(self):
        status, _ = self.vessel(summary={"Vendor Name": "V" * 81})
        self.assertEqual(status, 400)

    def test_too_long_master_data_value_is_refused(self):
        status, body = self.call(self.admin, "post", "/api/options/", {"kind": "agent", "value": "A" * 101})
        self.assertEqual(status, 400)
        self.assertIn("at most 100", body["error"])
        self.assertEqual(self.call(self.admin, "post", "/api/options/", {"kind": "agent", "value": "A" * 100})[0], 200)


class ReviewFollowUpTests(InputRulesData):
    def test_exchange_rate_zero_means_empty(self):
        self.assertEqual(self.service({"cost": 1, "exchangeRate": 0})[0], 201)
        data = Service.objects.filter(vessel=self.alex_vessel).latest("id").data
        self.assertIsNone(data["exchangeRate"])

    def test_admin_moving_a_vessel_checks_the_new_ports_list(self):
        Option.objects.get_or_create(kind="opr", value="ALEX ONLY", port="alexandria")
        Option.objects.get_or_create(kind="opr", value="SUEZ ONLY", port="suez")
        vessel = Vessel.objects.create(name="MOVER", date=date(2026, 11, 13), port="alexandria", opr="ARK")
        url = f"/api/vessels/{vessel.id}/"
        base = {"name": "MOVER", "date": "2026-11-13", "port": "suez"}
        self.assertEqual(self.call(self.admin, "put", url, {**base, "opr": "ALEX ONLY"})[0], 400)
        self.assertEqual(self.call(self.admin, "put", url, {**base, "opr": "SUEZ ONLY"})[0], 200)

    def test_transfer_keeps_its_saved_airport_and_port(self):
        guests = [{"name": "ahmed"}]
        trip = {"vessel": self.alex_vessel.id, "from_place": "airport", "to_place": "port", "at": "2026-11-14T10:00",
                "airport": "BORG EL ARAB", "port_name": "DEKHEILA", "guests": guests}
        status, row = self.call(self.alex, "post", "/api/transfers/", trip)
        self.assertEqual(status, 201)
        Option.objects.filter(kind__in=("airport", "port")).delete()  # both values leave the lists
        self.assertEqual(self.call(self.alex, "put", f"/api/transfers/{row['id']}/", trip)[0], 200)

    def test_too_long_booking_place_names_are_refused_not_cut(self):
        stay = {"vessel": self.alex_vessel.id, "check_in": "2026-11-14", "nights": 1, "guests": [{"name": "ahmed"}]}
        status, body = self.call(self.alex, "post", "/api/hotels/", {**stay, "hotel": "HILTON" + "X" * 150})
        self.assertEqual(status, 400)
        self.assertIn("at most 100", body["error"])

    def test_too_long_guest_details_are_refused(self):
        stay = {"vessel": self.alex_vessel.id, "hotel": "HILTON", "check_in": "2026-11-14", "nights": 1}
        for guest in ({"name": "a", "rank": "R" * 61}, {"name": "a", "nationality": "N" * 61},
                      {"name": "a", "flight": "F" * 21}):
            with self.subTest(guest=guest):
                self.assertEqual(self.call(self.alex, "post", "/api/hotels/", {**stay, "guests": [guest]})[0], 400)

    def test_guest_name_is_checked_after_upper_casing(self):
        stay = {"vessel": self.alex_vessel.id, "hotel": "HILTON", "check_in": "2026-11-14", "nights": 1}
        name = "ß" + "a" * 119  # 120 characters, 121 once upper-cased ("SS")
        self.assertEqual(self.call(self.alex, "post", "/api/hotels/", {**stay, "guests": [{"name": name}]})[0], 400)

    def test_more_than_100_lines_is_refused_not_dropped(self):
        status, body = self.service({"entries": [{"awb": "x"}] * 101}, service_type="Landing")
        self.assertEqual(status, 400)
        self.assertIn("100", body["error"])
        self.assertEqual(self.service({"entries": [{"awb": "x"}] * 100}, service_type="Landing")[0], 201)

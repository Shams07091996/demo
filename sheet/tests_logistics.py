"""Hotels and Transport: storage, input checks, the bookings API and the crew picker data."""

from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase
from django.utils import timezone

from .errors import BadRequest
from .logistics import parse_flight_time
from .models import Guest, HotelStay, Option, Service, Transfer
from .tests import ApiTestCase, allow
from .validators import clean_guests, clean_hotel_stay, clean_transfer

G = [{"name": "ahmed test", "rank": "2/E", "nationality": "Egyptian", "group": "on", "flight": "TK689"}]


def stay(**o):
    return {"hotel": "HILTON", "check_in": "2026-11-14", "nights": 2, "guests": G, **o}


def trip(**o):
    return {"from_place": "airport", "to_place": "hotel", "airport": "BORG EL ARAB", "hotel": "HILTON",
            "at": "2026-11-14T14:30", "guests": G, **o}


class BookingData(ApiTestCase):
    """A 2-guest stay and a transfer on ALEX SHIP (Alexandria), a stay on SUEZ SHIP."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        allow("hotel", "HILTON")
        allow("airport", "BORG EL ARAB")
        allow("port", "DEKHEILA")
        cls.stay = HotelStay.objects.create(
            vessel=cls.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=3,
            cost_per_night=Decimal("80"), cost_currency="USD",
        )
        Guest.objects.create(stay=cls.stay, position=0, name="AHMED TEST", rank="2/E")
        Guest.objects.create(stay=cls.stay, position=1, name="ALI SAYED", rank="OS")
        cls.suez_stay = HotelStay.objects.create(vessel=cls.suez_vessel, hotel="SUEZ INN", check_in=date(2026, 11, 14), nights=1)
        Guest.objects.create(stay=cls.suez_stay, position=0, name="SUEZ GUEST")
        cls.transfer = Transfer.objects.create(
            vessel=cls.alex_vessel, from_place="airport", to_place="hotel", airport="BORG EL ARAB", hotel="HILTON",
            at=timezone.make_aware(datetime(2026, 11, 15, 14, 30)), cost=Decimal("900"), revenue=Decimal("1200"),
        )
        Guest.objects.create(transfer=cls.transfer, position=0, name="AHMED TEST", flight="TK689")

    def list(self, user, kind, **params):
        response = self.login(user).get(f"/api/{kind}/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def client_status(self, user, kind, **params):
        return self.login(user).get(f"/api/{kind}/", params).status_code

    def payload(self, **o):
        guests = [{"name": "ahmed test", "rank": "2/E", "group": "on"}, {"name": "ali sayed", "rank": "OS", "group": "on"}]
        return {"vessel": self.alex_vessel.id, "hotel": "HILTON", "check_in": "2026-11-14", "nights": 3,
                "cost_per_night": "80", "cost_currency": "USD", "revenue_per_night": "4500", "guests": guests, **o}


class BookingApiTests(BookingData):
    def ids(self, kind, **params):
        return [b["id"] for b in self.list("admin", kind, **params)["bookings"]]

    def test_stay_overlap_edges(self):
        self.assertIn(self.stay.id, self.ids("hotels", **{"from": "2026-11-16", "to": "2026-11-16"}))   # inside
        self.assertNotIn(self.stay.id, self.ids("hotels", **{"from": "2026-11-17", "to": "2026-11-20"}))  # checks out on from
        self.assertIn(self.stay.id, self.ids("hotels", **{"from": "2026-11-10", "to": "2026-11-14"}))  # checks in on to
        self.assertNotIn(self.stay.id, self.ids("hotels", **{"from": "2026-11-10", "to": "2026-11-13"}))

    def test_transfer_range_inclusive_and_search(self):
        self.assertEqual(self.list("admin", "transfers", **{"from": "2026-11-15", "to": "2026-11-15"})["count"], 1)
        self.assertEqual(self.list("admin", "transfers", **{"from": "2026-11-16"})["count"], 0)
        self.assertEqual(self.list("admin", "hotels", q="ali")["count"], 1)        # any guest
        self.assertEqual(self.list("admin", "hotels", q="alex ship")["count"], 1)  # vessel name
        self.assertEqual(self.list("admin", "hotels", q="suez inn")["count"], 1)   # hotel
        self.assertEqual(self.list("admin", "transfers", q="tk689")["count"], 1)   # flight
        self.assertEqual(self.list("admin", "transfers", q="hilton")["count"], 1)  # hotel on a transfer
        self.assertEqual(self.list("admin", "hotels", q="%")["count"], 0)

    def test_rows_carry_vessel_guests_and_dates(self):
        row = next(b for b in self.list("admin", "hotels")["bookings"] if b["id"] == self.stay.id)
        self.assertEqual(row["vessel"]["name"], "ALEX SHIP")
        self.assertEqual([g["name"] for g in row["guests"]], ["AHMED TEST", "ALI SAYED"])
        self.assertEqual((row["check_in"], row["check_out"], row["cost_per_night"], row["cost_currency"]),
                         ("2026-11-14", "2026-11-17", 80.0, "USD"))
        trip_row = self.list("admin", "transfers")["bookings"][0]
        self.assertEqual((trip_row["at"], trip_row["from_place"], trip_row["hotel"], trip_row["cost"]),
                         ("2026-11-15T14:30", "airport", "HILTON", 900.0))

    def test_read_only_sees_booking_money_but_cannot_write(self):
        """User decision: read-only users can see money everywhere; they still can't change anything."""
        row = next(b for b in self.list("viewer", "hotels")["bookings"] if b["id"] == self.stay.id)
        self.assertEqual((row["cost_per_night"], row["cost_currency"], row["revenue_per_night"]), (80.0, "USD", None))
        trip_row = self.list("viewer", "transfers")["bookings"][0]
        self.assertEqual((trip_row["cost"], trip_row["revenue"], trip_row["revenue_currency"]), (900.0, 1200.0, "EGP"))
        self.assertEqual(self.call(self.login("viewer"), "post", "/api/hotels/", self.payload())[0], 403)
        self.assertEqual(self.call(self.login("viewer"), "delete", f"/api/hotels/{self.stay.id}/")[0], 403)

    def test_port_user_is_kept_to_own_port(self):
        alex = self.login("alex")
        ports = {b["vessel"]["port"] for b in self.list("alex", "hotels", port="suez")["bookings"]}
        self.assertEqual(ports, {"alexandria"})
        self.assertEqual(self.call(alex, "post", "/api/hotels/", self.payload(vessel=self.suez_vessel.id))[0], 404)
        self.assertEqual(self.call(alex, "get", f"/api/hotels/{self.suez_stay.id}/")[0], 404)
        self.assertEqual(self.call(alex, "put", f"/api/hotels/{self.suez_stay.id}/", self.payload())[0], 404)
        self.assertEqual(self.call(alex, "delete", f"/api/hotels/{self.suez_stay.id}/")[0], 404)
        self.assertTrue(HotelStay.objects.filter(pk=self.suez_stay.id).exists())

    def test_create_edit_delete_keeps_guest_copy(self):
        alex = self.login("alex")
        status, row = self.call(alex, "post", "/api/hotels/", self.payload())
        self.assertEqual((status, [g["name"] for g in row["guests"]]), (201, ["AHMED TEST", "ALI SAYED"]))
        Service.objects.filter(vessel=self.alex_vessel).delete()  # the crew change goes away
        self.assertEqual(len(self.call(alex, "get", f"/api/hotels/{row['id']}/")[1]["guests"]), 2)
        guests = [{"name": "only one"}]
        status, row = self.call(alex, "put", f"/api/hotels/{row['id']}/", self.payload(nights=4, guests=guests))
        self.assertEqual((status, row["check_out"], [g["name"] for g in row["guests"]]), (200, "2026-11-18", ["ONLY ONE"]))
        self.assertEqual(self.call(alex, "delete", f"/api/hotels/{row['id']}/")[0], 200)
        self.assertFalse(HotelStay.objects.filter(pk=row["id"]).exists())

    def test_create_transfer_and_errors_reach_the_user(self):
        admin = self.login("admin")
        trip_data = {"vessel": self.alex_vessel.id, "from_place": "hotel", "to_place": "port", "hotel": "HILTON",
                     "port_name": "DEKHEILA", "at": "2026-11-17T08:00", "guests": [{"name": "ahmed test"}]}
        status, row = self.call(admin, "post", "/api/transfers/", trip_data)
        self.assertEqual((status, row["at"], row["to_place"], row["port_name"], row["airport"]),
                         (201, "2026-11-17T08:00", "port", "DEKHEILA", ""))
        status, data = self.call(admin, "post", "/api/transfers/", {**trip_data, "guests": []})
        self.assertEqual((status, data["error"]), (400, "Add at least one guest."))
        self.assertEqual(self.call(admin, "post", "/api/transfers/", {**trip_data, "vessel": 999999})[0], 404)
        self.assertEqual(self.call(admin, "post", "/api/transfers/", {**trip_data, "vessel": "x"})[0], 404)

    def test_changing_a_bookings_vessel_is_ignored_on_edit(self):
        admin = self.login("admin")
        status, row = self.call(admin, "put", f"/api/hotels/{self.stay.id}/", self.payload(vessel=self.suez_vessel.id))
        self.assertEqual((status, row["vessel"]["id"]), (200, self.alex_vessel.id))

    def test_sorting_paging_and_bad_params(self):
        self.assertEqual([b["hotel"] for b in self.list("admin", "hotels", sort="hotel", dir="asc")["bookings"]],
                         ["HILTON", "SUEZ INN"])
        page = self.list("admin", "hotels", page_size=1, page=2)
        self.assertEqual((page["count"], page["pages"], len(page["bookings"])), (2, 2, 1))
        for p in ({"from": "x"}, {"page": "0"}, {"sort": "price"}, {"from": "2026-12-01", "to": "2026-11-01"}):
            self.assertEqual(self.client_status("admin", "hotels", **p), 400, p)

    def test_bookings_are_not_in_vessel_money(self):
        vessel = self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/")[1]
        self.assertEqual(vessel["total_cost_egp"], 0)


class LogisticsValidationTests(SimpleTestCase):
    def assertRejects(self, clean, data, message):
        with self.assertRaises(BadRequest) as caught:
            clean(data)
        self.assertEqual(str(caught.exception), message)

    def test_guests_are_cleaned_and_limited(self):
        guest = clean_guests(G)[0]
        self.assertEqual((guest["name"], guest["rank"], guest["group"], guest["flight"]), ("AHMED TEST", "2/E", "on", "TK689"))
        self.assertRejects(clean_guests, [], "Add at least one guest.")
        self.assertRejects(clean_guests, "x", "Add at least one guest.")
        self.assertRejects(clean_guests, G * 7, "At most 6 guests per booking.")
        self.assertRejects(clean_guests, G + [{"name": "  "}], "Every guest needs a name.")
        self.assertEqual(clean_guests([{"name": "X", "group": "boss"}])[0]["group"], "")
        self.assertEqual(len(clean_guests(G * 6)), 6)

    def test_stay_rules(self):
        cleaned = clean_hotel_stay(stay(cost_per_night="80", cost_currency="USD", revenue_per_night="4500", exchange_rate="49.5"))
        self.assertEqual((cleaned["nights"], cleaned["check_in"], cleaned["cost_per_night"], cleaned["cost_currency"]),
                         (2, date(2026, 11, 14), Decimal("80"), "USD"))
        self.assertEqual(cleaned["exchange_rate"], Decimal("49.5"))
        for nights in (0, 61, "two", None):
            self.assertRejects(clean_hotel_stay, stay(nights=nights), "Nights must be a whole number from 1 to 60.")
        self.assertRejects(clean_hotel_stay, stay(check_in="14.11.2026"), "Enter a valid check-in date.")
        self.assertRejects(clean_hotel_stay, stay(hotel=" "), "Choose a hotel.")
        self.assertRejects(clean_hotel_stay, stay(cost_per_night=-1), "Prices cannot be negative.")
        self.assertRejects(clean_hotel_stay, stay(revenue_per_night=-1), "Prices cannot be negative.")
        self.assertEqual((cleaned["revenue_per_night"], cleaned["revenue_currency"]), (Decimal("4500"), "EGP"))
        self.assertRejects(clean_hotel_stay, stay(exchange_rate=0), "Exchange rate must be a positive number.")
        self.assertEqual(clean_hotel_stay(stay(cost_per_night="80", cost_currency="GBP"))["cost_currency"], "EGP")
        self.assertIsNone(clean_hotel_stay(stay(cost_per_night=""))["cost_per_night"])

    def test_transfer_rules(self):
        self.assertEqual(clean_transfer(trip())["hotel"], "HILTON")
        self.assertEqual(clean_transfer(trip(from_place="airport", to_place="port", port_name="DEKHEILA"))["hotel"], "")
        self.assertEqual(clean_transfer(trip())["at"].strftime("%Y-%m-%d %H:%M"), "2026-11-14 14:30")
        self.assertRejects(clean_transfer, trip(to_place="airport"), "From and To must be different.")
        self.assertRejects(clean_transfer, trip(from_place="hotel", to_place="hotel"), "From and To must be different.")
        self.assertRejects(clean_transfer, trip(hotel=""), "Choose a hotel.")
        self.assertRejects(clean_transfer, trip(from_place="sea"), "Choose where from and where to.")
        self.assertRejects(clean_transfer, trip(at=""), "Enter the date and time.")
        self.assertRejects(clean_transfer, trip(at="2026-11-14"), "Enter the date and time.")
        self.assertRejects(clean_transfer, trip(cost="-5"), "Prices cannot be negative.")
        self.assertRejects(clean_transfer, trip(revenue="-5"), "Prices cannot be negative.")
        self.assertEqual(clean_transfer(trip(revenue="12", revenue_currency="USD"))["revenue"], Decimal("12"))


class ModelTests(ApiTestCase):
    def test_check_out_and_cascade(self):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=3)
        Guest.objects.create(stay=stay, position=0, name="AHMED TEST")
        self.assertEqual(stay.check_out, date(2026, 11, 17))
        self.alex_vessel.delete()
        self.assertFalse(HotelStay.objects.exists() or Guest.objects.exists())

    def test_guest_belongs_to_exactly_one_booking(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Guest.objects.create(position=0, name="NOBODY")

    def test_hotel_is_a_master_data_kind_counted_by_bookings(self):
        HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14), nights=1)
        Option.objects.create(kind="hotel", value="HILTON")
        _, data = self.call(self.login("admin"), "get", "/api/options/")
        hilton = next(o for o in data["options"] if o["kind"] == "hotel")
        self.assertEqual(hilton["used"], 1)
        # a port user only counts bookings they can see
        _, data = self.call(self.login("suezuser"), "get", "/api/options/")
        self.assertEqual(next(o for o in data["options"] if o["kind"] == "hotel")["used"], 0)


class CrewHelperTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        seg = lambda no, dep_city, dep, arr_city, arr: {  # noqa: E731
            "flightNo": no, "departureCity": dep_city, "departureTime": dep, "arrivalCity": arr_city, "arrivalTime": arr,
        }
        on = {"name": "Ahmed Test", "personalStructured": {"rank": "2/E", "nationality": "Egyptian"},
              "flightStructured": {"segments": [seg("TK 1", "Manila", "12 NOV 22:00", "Istanbul", "13 NOV 05:00"),
                                                seg("MS 123", "Istanbul", "13 NOV 07:00", "Alexandria", "13 NOV 10:00")]}}
        off = {"name": "Mona Off", "personalStructured": {"nationality": "Indian"},
               "flightStructured": {"segments": [seg("TK 690", "Alexandria", "14 NOV 05:00", "Istanbul", "14 NOV 08:00")]}}
        Service.objects.create(vessel=cls.alex_vessel, service_type="Crew Change", data={"onSigners": [on], "offSigners": [off]})

    def test_parse_flight_time(self):
        near = date(2026, 11, 13)
        self.assertEqual(parse_flight_time("13 NOV 10:00", "", near).strftime("%Y-%m-%d %H:%M"), "2026-11-13 10:00")
        self.assertEqual(parse_flight_time("13 nov 2026 10:00", "", near).strftime("%Y-%m-%d %H:%M"), "2026-11-13 10:00")
        self.assertEqual(parse_flight_time("02 JAN 06:15", "", date(2026, 12, 30)).year, 2027)  # nearest year
        self.assertEqual(parse_flight_time("10:00", "13.11.2026", near).strftime("%Y-%m-%d %H:%M"), "2026-11-13 10:00")
        for text in ("TBA", "", "31 FEB 10:00", "10:00", "13 NOV 25:00", None):
            self.assertIsNone(parse_flight_time(text, "", near), text)

    def test_crew_helper_lists_on_and_off_signers_with_the_right_leg(self):
        status, data = self.call(self.login("viewer"), "get", f"/api/vessels/{self.alex_vessel.id}/crew/")
        self.assertEqual(status, 200)
        on, off = data["crew"]
        self.assertEqual((on["group"], on["name"], on["rank"], on["nationality"]), ("on", "Ahmed Test", "2/E", "Egyptian"))
        self.assertEqual((on["flight"], on["arrival"], on["departure"]), ("MS 123", "2026-11-13T10:00", ""))
        self.assertEqual((off["group"], off["flight"], off["departure"], off["arrival"]), ("off", "TK 690", "2026-11-14T05:00", ""))

    def test_crew_helper_is_scoped_and_empty_without_a_crew_change(self):
        self.assertEqual(self.call(self.login("suezuser"), "get", f"/api/vessels/{self.alex_vessel.id}/crew/")[0], 404)
        self.assertEqual(self.call(self.login("admin"), "get", f"/api/vessels/{self.suez_vessel.id}/crew/")[1], {"crew": []})


class GuestsFirstTests(SimpleTestCase):
    def test_missing_guests_is_reported_before_other_problems(self):
        """Guests are the first part of the dialog, so that is the first thing the person is told about."""
        for clean, data in ((clean_transfer, {"guests": [], "at": ""}), (clean_hotel_stay, {"guests": [], "nights": 0})):
            with self.assertRaises(BadRequest) as caught:
                clean(data)
            self.assertEqual(str(caught.exception), "Add at least one guest.")


class AirportAndPortTests(BookingData):
    """Transfers say which airport and which port (there are several), from Master data lists."""

    def test_airport_and_port_are_required_for_their_ends(self):
        self.assertEqual(clean_transfer(trip())["airport"], "BORG EL ARAB")
        self.assertEqual(clean_transfer(trip(from_place="hotel", to_place="port", port_name="Dekheila"))["port_name"],
                         "Dekheila")
        self.assertEqual(clean_transfer(trip(from_place="hotel", to_place="port", port_name="X"))["airport"], "")
        self.assertEqual(clean_transfer(trip())["port_name"], "")
        with self.assertRaises(BadRequest) as caught:
            clean_transfer(trip(airport=" "))
        self.assertEqual(str(caught.exception), "Choose an airport.")
        with self.assertRaises(BadRequest) as caught:
            clean_transfer(trip(from_place="hotel", to_place="port"))
        self.assertEqual(str(caught.exception), "Choose a port.")

    def test_listed_and_searched(self):
        row = self.list("admin", "transfers")["bookings"][0]
        self.assertEqual((row["airport"], row["port_name"]), ("BORG EL ARAB", ""))
        self.assertEqual(self.list("viewer", "transfers", q="borg")["count"], 1)

    def test_airport_and_port_are_master_data_kinds_counted_by_transfers(self):
        # BORG EL ARAB and DEKHEILA are in Master data from BookingData
        _, data = self.call(self.login("admin"), "get", "/api/options/")
        used = {o["kind"]: o["used"] for o in data["options"] if o["kind"] in ("airport", "port")}
        self.assertEqual(used, {"airport": 1, "port": 0})


class CrewCityTests(CrewHelperTests):
    def test_crew_helper_gives_the_airport_city(self):
        on, off = self.call(self.login("admin"), "get", f"/api/vessels/{self.alex_vessel.id}/crew/")[1]["crew"]
        self.assertEqual((on["city"], off["city"]), ("Alexandria", "Alexandria"))

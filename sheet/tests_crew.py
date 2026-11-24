"""Crew members: uid, Needs hotel, broken visa; vessel date = sailing date; automatic draft bookings; alerts."""

from datetime import date, timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from . import finance
from .errors import BadRequest
from .models import ChangeRecord, Guest, HotelStay, Service, Transfer, Vessel
from .tests import ApiTestCase, allow
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


def seg(arrival_time):
    return {"flightNo": "MS 123", "airline": "EGYPTAIR", "arrivalCity": "Alexandria", "arrivalTime": arrival_time,
            "departureCity": "Alexandria", "departureTime": arrival_time}


def member(name, landing="15 NOV 10:00", **extra):
    flight = {"segments": [seg(landing)]} if landing else {"segments": []}
    return {"name": name, "flightStructured": flight, **extra}


class DraftBookingTests(ApiTestCase):
    def setUp(self):
        self.alex = self.login("alex")
        self.vessel = self.alex_vessel  # 13.11.2026, Alexandria

    def post_crew(self, on=(), off=()):
        payload = {"type": "Crew Change", "data": {"onSigners": list(on), "offSigners": list(off)}}
        status, _ = self.call(self.alex, "post", f"/api/vessels/{self.vessel.id}/services/", payload)
        self.assertEqual(status, 201)
        return Service.objects.filter(vessel=self.vessel, service_type="Crew Change").latest("id")

    def put_crew(self, service, on=(), off=()):
        payload = {"type": "Crew Change", "data": {"onSigners": list(on), "offSigners": list(off)}}
        return self.call(self.alex, "put", f"/api/services/{service.id}/", payload)[0]

    def saved(self, service):
        service.refresh_from_db()
        return service.data

    def transfers(self):
        return Transfer.objects.filter(vessel=self.vessel).order_by("id")

    def stays(self):
        return HotelStay.objects.filter(vessel=self.vessel).order_by("id")

    def test_every_member_gets_a_draft_transfer(self):
        self.post_crew(on=[member("J SMITH")], off=[member("A OFF", landing="14 NOV 05:00")])
        on, off = self.transfers()
        self.assertTrue(on.draft and off.draft)
        self.assertEqual((on.from_place, on.to_place), ("airport", "port"))
        self.assertEqual(timezone.localtime(on.at).strftime("%Y-%m-%d %H:%M"), "2026-11-15 10:00")
        self.assertEqual((off.from_place, off.to_place), ("port", "airport"))
        self.assertEqual(on.guests.get().name, "J SMITH")
        self.assertFalse(self.stays().exists())

    def test_needs_hotel_creates_draft_stay(self):
        service = self.post_crew(on=[member("J SMITH", needsHotel=True)], off=[member("A OFF", needsHotel=True)])
        on_stay, off_stay = self.stays()
        self.assertTrue(on_stay.draft)
        self.assertEqual((on_stay.hotel, on_stay.nights, on_stay.check_in), ("", 1, date(2026, 11, 15)))
        self.assertEqual(on_stay.guests.get().crew_uid, self.saved(service)["onSigners"][0]["uid"])
        self.assertEqual(off_stay.check_in, date(2026, 11, 13))

    def test_unparsed_flight_falls_back_to_vessel_date(self):
        self.post_crew(on=[member("J SMITH", landing="", needsHotel=True)])
        self.assertEqual(timezone.localtime(self.transfers().get().at).strftime("%Y-%m-%d %H:%M"), "2026-11-13 00:00")
        self.assertEqual(self.stays().get().check_in, date(2026, 11, 13))

    def test_resave_is_idempotent(self):
        service = self.post_crew(on=[member("J SMITH")], off=[member("A OFF")])
        data = self.saved(service)
        self.assertEqual(self.put_crew(service, data["onSigners"], data["offSigners"]), 200)
        self.assertEqual(self.transfers().count(), 2)

    def test_draft_follows_member(self):
        service = self.post_crew(on=[member("J SMITH", needsHotel=True)])
        renamed = {**self.saved(service)["onSigners"][0], "name": "JOHN SMITH",
                   "flightStructured": {"segments": [seg("16 NOV 09:30")]}}
        self.put_crew(service, [renamed])
        transfer = self.transfers().get()
        self.assertEqual(transfer.guests.get().name, "JOHN SMITH")
        self.assertEqual(timezone.localtime(transfer.at).strftime("%Y-%m-%d %H:%M"), "2026-11-16 09:30")
        self.assertEqual(self.stays().get().check_in, date(2026, 11, 16))

    def complete_stay(self, stay):
        allow("hotel", "NILE HOTEL")
        guest = stay.guests.get()
        payload = {"vessel": self.vessel.id, "hotel": "NILE HOTEL", "check_in": stay.check_in.isoformat(), "nights": 2,
                   "cost_per_night": 50, "revenue_per_night": 70,
                   "guests": [{"name": guest.name, "group": guest.group, "crew_uid": guest.crew_uid}]}
        self.assertEqual(self.call(self.alex, "put", f"/api/hotels/{stay.id}/", payload)[0], 200)

    def test_switch_off_or_remove_deletes_draft_only(self):
        service = self.post_crew(on=[member("J SMITH", needsHotel=True), member("B DRAFT", needsHotel=True)])
        completed = self.stays().first()
        self.complete_stay(completed)
        smith, _ = self.saved(service)["onSigners"]
        self.put_crew(service, [{**smith, "needsHotel": False}])  # B DRAFT removed, J SMITH's hotel switched off
        self.assertEqual(list(self.stays()), [completed])
        self.assertEqual(self.transfers().get().guests.get().name, "J SMITH")

    def test_dialog_save_keeps_link(self):
        service = self.post_crew(on=[member("J SMITH", needsHotel=True)])
        stay = self.stays().get()
        self.complete_stay(stay)
        stay.refresh_from_db()
        self.assertFalse(stay.draft)
        data = self.saved(service)
        self.put_crew(service, data["onSigners"])
        self.assertEqual(self.stays().count(), 1)
        self.assertEqual(stay.guests.get().crew_uid, data["onSigners"][0]["uid"])

    def test_same_name_two_members(self):
        self.post_crew(on=[member("JOHN DOE"), member("JOHN DOE")])
        self.assertEqual(self.transfers().count(), 2)

    def test_deleted_transfer_comes_back(self):
        service = self.post_crew(on=[member("J SMITH")])
        self.assertEqual(self.call(self.alex, "delete", f"/api/transfers/{self.transfers().get().id}/")[0], 200)
        self.put_crew(service, self.saved(service)["onSigners"])
        self.assertTrue(self.transfers().get().draft)

    def test_delete_service_drops_drafts_keeps_completed(self):
        service = self.post_crew(on=[member("J SMITH", needsHotel=True)])
        self.complete_stay(self.stays().get())
        self.assertEqual(self.call(self.alex, "delete", f"/api/services/{service.id}/")[0], 200)
        self.assertFalse(self.transfers().exists())
        self.assertEqual(self.stays().count(), 1)

    def test_history_records_drafts(self):
        self.post_crew(on=[member("J SMITH", needsHotel=True)])
        record = ChangeRecord.objects.filter(object_type="hotelstay", action="create").latest("id")
        self.assertEqual(record.username, "alex")

    def test_vessel_save_refreshes_drafts(self):
        self.post_crew(off=[member("A OFF", landing="", needsHotel=True)])
        payload = {"name": "ALEX SHIP", "date": "2026-11-13", "sailing_at": "2026-12-02T10:00"}
        self.assertEqual(self.call(self.alex, "put", f"/api/vessels/{self.vessel.id}/", payload)[0], 200)
        self.assertEqual(self.stays().get().check_in, date(2026, 12, 2))
        self.assertEqual(timezone.localtime(self.transfers().get().at).date(), date(2026, 12, 2))

    def test_legacy_booking_adopted_not_duplicated(self):
        service = self.post_crew(on=[member("J SMITH")])
        draft = self.transfers().get()
        draft.delete()  # as before this feature: a hand-made, completed transfer with an unlinked guest
        old = Transfer.objects.create(vessel=self.vessel, from_place="airport", to_place="port", at=timezone.now(),
                                      cost=1, revenue=2)
        Guest.objects.create(transfer=old, name="J SMITH", group="on")
        self.put_crew(service, self.saved(service)["onSigners"])
        self.assertEqual(list(self.transfers()), [old])
        self.assertEqual(old.guests.get().crew_uid, self.saved(service)["onSigners"][0]["uid"])


def landing_text(day):
    return f"{day:%d} {day:%b}".upper() + " 10:00"


class AlertTests(ApiTestCase):
    """Booking gaps once the vessel has sailed, and on-signers landing 2+ days before the vessel date."""

    def setUp(self):
        self.now = timezone.now()
        self.today = timezone.localdate()

    def alerts(self, user="admin"):
        status, data = self.call(self.login(user), "get", "/api/vessels/alerts/")
        self.assertEqual(status, 200)
        return data

    def missing_of(self, vessel, user="admin"):
        rows = [row for row in self.alerts(user)["missing"] if row["id"] == vessel.id]
        return rows[0]["missing"] if rows else []

    def sailed_vessel(self, sailing):
        vessel = Vessel.objects.create(name="GONE", date=self.today, port="alexandria", sailing_at=sailing,
                                       arrival_agent="A", sailing_agent="B")
        transfer = Transfer.objects.create(vessel=vessel, from_place="airport", to_place="port", at=self.now,
                                           draft=True)
        Guest.objects.create(transfer=transfer, name="J SMITH", group="on")
        return vessel

    def test_incomplete_booking_listed_after_sailing(self):
        vessel = self.sailed_vessel(self.now - timedelta(hours=1))
        self.assertIn("Transport: J SMITH", self.missing_of(vessel))

    def test_not_listed_before_sailing(self):
        vessel = self.sailed_vessel(self.now + timedelta(days=1))
        vessel.date = self.today + timedelta(days=1)
        vessel.save()
        self.assertEqual(self.missing_of(vessel), [])

    def test_completed_but_no_price_listed(self):
        vessel = self.sailed_vessel(self.now - timedelta(hours=1))
        stay = HotelStay.objects.create(vessel=vessel, hotel="NILE", check_in=self.today, nights=1,
                                        cost_per_night=10)
        Guest.objects.create(stay=stay, name="A OFF", group="off")
        vessel.transfers.update(draft=False, cost=1, revenue=2)
        self.assertEqual(self.missing_of(vessel), ["Hotel: A OFF"])

    def crew_vessel(self, lands_days_before, group="onSigners", visa=None, port="alexandria"):
        when = self.today + timedelta(days=1)
        vessel = Vessel.objects.create(name="EARLY", date=when, port=port)
        person = member("J SMITH", landing=landing_text(when - timedelta(days=lands_days_before)), uid="abcdef123456")
        if visa is not None:
            person["brokenVisa"] = visa
        Service.objects.create(vessel=vessel, service_type="Crew Change",
                               data={"onSigners": [], "offSigners": [], group: [person]})
        return vessel, when

    def test_early_arrival(self):
        vessel, when = self.crew_vessel(2)
        rows = [r for r in self.alerts()["early"] if r["id"] == vessel.id]
        self.assertEqual(rows, [{"id": vessel.id, "name": "EARLY", "date": when.isoformat(), "crew": "J SMITH",
                                 "lands": (when - timedelta(days=2)).isoformat()}])

    def test_one_day_early_or_off_signer_not_listed(self):
        self.crew_vessel(1)
        self.crew_vessel(3, group="offSigners")
        self.assertEqual(self.alerts()["early"], [])

    def test_broken_visa_zero_clears_early(self):
        self.crew_vessel(3, visa={"cost": 0})
        self.assertEqual(self.alerts()["early"], [])

    def test_early_port_scoped(self):
        self.crew_vessel(3)
        self.assertEqual(self.alerts("suezuser")["early"], [])
        self.assertEqual(len(self.alerts("alex")["early"]), 1)


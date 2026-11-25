"""Hotel / Transport typed on a crew member: cleaning, the drafts they make, the saved-bookings route, migration 0027."""

import importlib
from datetime import date

from django.apps import apps
from django.test import SimpleTestCase
from django.utils import timezone

from .errors import BadRequest
from .models import Guest, HotelStay, Service, Transfer
from .tests import ApiTestCase, allow, make_user
from .tests_crew import member
from .validators import clean_service_data


def crew(on=(), off=()):
    return clean_service_data("Crew Change", {"onSigners": list(on), "offSigners": list(off)})


class CleaningTests(SimpleTestCase):
    def test_keys_always_present_and_cleaned(self):
        m = crew(on=[{"name": "A", "needsTransport": 1}], off=[{"name": "B"}])
        on, off = m["onSigners"][0], m["offSigners"][0]
        self.assertIs(on["needsTransport"], True)
        self.assertIs(off["needsTransport"], False)
        self.assertEqual(on["hotel"], {"name": "", "checkIn": "", "checkOut": ""})
        self.assertEqual(on["transport"], {"from": "", "fromName": "", "to": "", "toName": "", "at": ""})

    def test_typed_values_kept(self):
        hotel = {"name": "NILE HOTEL", "checkIn": "2026-11-20", "checkOut": "2026-11-22", "junk": 1}
        transport = {"from": "airport", "fromName": "HBE", "to": "hotel", "toName": "NILE HOTEL",
                     "at": "2026-11-20T14:30"}
        m = crew(on=[{"name": "A", "hotel": hotel, "transport": transport}])["onSigners"][0]
        self.assertEqual(m["hotel"], {"name": "NILE HOTEL", "checkIn": "2026-11-20", "checkOut": "2026-11-22"})
        self.assertEqual(m["transport"], transport)

    def refused(self, message, **item):
        with self.assertRaisesMessage(BadRequest, message):
            crew(on=[{"name": "A", **item}])

    def test_bad_values_refused(self):
        self.refused("Enter a valid check-in date.", hotel={"checkIn": "20.11.2026"})
        self.refused("Enter a valid check-out date.", hotel={"checkOut": "2026-13-01"})
        self.refused("Check-out must be after check-in.", hotel={"checkIn": "2026-11-20", "checkOut": "2026-11-20"})
        self.refused("Nights must be", hotel={"checkIn": "2026-01-01", "checkOut": "2026-06-01"})
        self.refused("Choose where from and where to.", transport={"from": "beach"})
        self.refused("From and To must be different.", transport={"from": "port", "to": "port"})
        self.refused("Enter the date and time.", transport={"at": "tomorrow"})
        self.refused("Hotel name is too long", hotel={"name": "x" * 101})


class CrewBookingsTests(ApiTestCase):
    def setUp(self):
        self.alex = self.login("alex")
        self.vessel = self.alex_vessel  # 13.11.2026, Alexandria
        allow("hotel", "NILE HOTEL", "SEA HOTEL")
        allow("airport", "HBE")
        allow("port", "ALEX PORT")

    def send(self, on=(), off=(), service=None, client=None):
        payload = {"type": "Crew Change", "data": {"onSigners": list(on), "offSigners": list(off)}}
        if service is None:
            return self.call(client or self.alex, "post", f"/api/vessels/{self.vessel.id}/services/", payload)
        return self.call(client or self.alex, "put", f"/api/services/{service.id}/", payload)

    def post(self, on=(), off=()):
        status, body = self.send(on, off)
        self.assertEqual(status, 201, body)
        return Service.objects.filter(vessel=self.vessel, service_type="Crew Change").latest("id")

    def on_signer(self, service):
        service.refresh_from_db()
        return service.data["onSigners"][0]

    def transfers(self):
        return Transfer.objects.filter(vessel=self.vessel).order_by("id")

    def stays(self):
        return HotelStay.objects.filter(vessel=self.vessel).order_by("id")

    def test_transport_only_when_pressed(self):
        self.post(on=[member("J SMITH", needsTransport=False)], off=[member("A OFF", needsTransport=False)])
        self.assertFalse(self.transfers().exists())

    def test_pressed_with_nothing_typed_uses_the_flight(self):
        self.post(on=[member("J SMITH", needsTransport=True)])
        transfer = self.transfers().get()
        self.assertEqual((transfer.from_place, transfer.to_place, transfer.draft), ("airport", "port", True))
        self.assertEqual(timezone.localtime(transfer.at).strftime("%Y-%m-%d %H:%M"), "2026-11-15 10:00")

    def test_typed_transport_used(self):
        transport = {"from": "airport", "fromName": "HBE", "to": "hotel", "toName": "NILE HOTEL",
                     "at": "2026-11-16T08:15"}
        self.post(on=[member("J SMITH", needsTransport=True, transport=transport)])
        t = self.transfers().get()
        self.assertEqual((t.from_place, t.to_place, t.airport, t.hotel, t.port_name),
                         ("airport", "hotel", "HBE", "NILE HOTEL", ""))
        self.assertEqual(timezone.localtime(t.at).strftime("%Y-%m-%d %H:%M"), "2026-11-16 08:15")

    def test_typed_hotel_used(self):
        hotel = {"name": "NILE HOTEL", "checkIn": "2026-11-20", "checkOut": "2026-11-22"}
        self.post(on=[member("J SMITH", needsHotel=True, hotel=hotel)])
        stay = self.stays().get()
        self.assertEqual((stay.hotel, stay.check_in, stay.nights, stay.draft),
                         ("NILE HOTEL", date(2026, 11, 20), 2, True))

    def test_check_in_only_is_one_night(self):
        self.post(on=[member("J SMITH", needsHotel=True, hotel={"checkIn": "2026-11-21"})])
        stay = self.stays().get()
        self.assertEqual((stay.check_in, stay.nights), (date(2026, 11, 21), 1))

    def test_check_out_only_counts_from_the_automatic_check_in(self):
        self.post(on=[member("J SMITH", needsHotel=True, hotel={"checkOut": "2026-11-18"})])  # lands 15 NOV
        stay = self.stays().get()
        self.assertEqual((stay.check_in, stay.nights), (date(2026, 11, 15), 3))

    def test_editing_refreshes_the_draft(self):
        service = self.post(on=[member("J SMITH", needsHotel=True, needsTransport=True)])
        m = self.on_signer(service)
        m["hotel"] = {"name": "SEA HOTEL", "checkIn": "2026-11-17", "checkOut": "2026-11-20"}
        m["transport"] = {"from": "port", "fromName": "ALEX PORT", "to": "airport", "toName": "HBE",
                          "at": "2026-11-20T06:00"}
        self.assertEqual(self.send([m], service=service)[0], 200)
        stay, t = self.stays().get(), self.transfers().get()
        self.assertEqual((stay.hotel, stay.check_in, stay.nights), ("SEA HOTEL", date(2026, 11, 17), 3))
        self.assertEqual((t.from_place, t.port_name, t.to_place, t.airport), ("port", "ALEX PORT", "airport", "HBE"))
        self.assertEqual(Transfer.objects.count() + HotelStay.objects.count(), 2)

    def test_unpressing_deletes_the_draft(self):
        service = self.post(on=[member("J SMITH", needsHotel=True, needsTransport=True)])
        m = {**self.on_signer(service), "needsHotel": False, "needsTransport": False}
        self.send([m], service=service)
        self.assertFalse(self.transfers().exists() or self.stays().exists())

    def test_saved_or_closed_booking_never_changed(self):
        service = self.post(on=[member("J SMITH", needsTransport=True), member("B CLOSED", needsTransport=True)])
        saved, closed = self.transfers()
        Transfer.objects.filter(pk=saved.pk).update(draft=False, cost=5, revenue=9)
        Transfer.objects.filter(pk=closed.pk).update(acct_closed=True)
        service.refresh_from_db()
        on = service.data["onSigners"]
        moved = {"from": "airport", "fromName": "HBE", "to": "port", "toName": "ALEX PORT", "at": "2026-11-19T10:00"}
        self.send([{**on[0], "transport": moved}, {**on[1], "transport": moved, "needsTransport": False}],
                  service=service)
        self.assertEqual(list(self.transfers()), [saved, closed])
        for before in (saved, closed):
            after = Transfer.objects.get(pk=before.pk)
            self.assertEqual((after.at, after.airport), (before.at, ""))

    def test_names_must_be_in_master_data(self):
        status, body = self.send(on=[member("J SMITH", needsHotel=True, hotel={"name": "UNKNOWN HOTEL"})])
        self.assertEqual(status, 400, body)
        status, body = self.send(on=[member("J SMITH", needsTransport=True,
                                            transport={"from": "airport", "fromName": "NOWHERE", "to": "port"})])
        self.assertEqual(status, 400, body)

    def test_saved_name_off_the_list_stays_allowed(self):
        service = self.post(on=[member("J SMITH", needsHotel=True, hotel={"name": "SEA HOTEL"})])
        from .models import Option
        Option.objects.filter(kind="hotel", value="SEA HOTEL").delete()
        self.assertEqual(self.send([self.on_signer(service)], service=service)[0], 200)

    def test_user_without_money_edit_may_save_them(self):
        perms = ["services.edit", "vessels.edit", "money.view"]
        make_user("nomoney", ["alexandria"], permissions=perms, pages=["vessels"])
        client = self.login("nomoney")
        hotel = {"name": "NILE HOTEL", "checkIn": "2026-11-20", "checkOut": "2026-11-21"}
        status, body = self.send(on=[member("J SMITH", needsHotel=True, hotel=hotel)], client=client)
        self.assertEqual(status, 201, body)
        self.assertEqual(self.stays().get().hotel, "NILE HOTEL")

    def test_saved_route(self):
        service = self.post(on=[member("J SMITH", needsTransport=True, needsHotel=True), member("B", needsTransport=False)])
        Transfer.objects.update(draft=False)
        service.refresh_from_db()
        uid = service.data["onSigners"][0]["uid"]
        status, body = self.call(self.alex, "get", f"/api/services/{service.id}/crew-bookings/")
        self.assertEqual(status, 200)
        self.assertEqual(body["saved"], {uid: {"hotel": False, "transport": True}})
        self.assertEqual(self.call(self.login("suezuser"), "get", f"/api/services/{service.id}/crew-bookings/")[0], 404)


class MigrationTests(ApiTestCase):
    def test_members_with_a_transfer_get_transport_pressed(self):
        data = clean_service_data("Crew Change", {"onSigners": [{"name": "A"}, {"name": "B"}]})
        for m in data["onSigners"]:
            m.pop("needsTransport")
        service = Service.objects.create(vessel=self.alex_vessel, service_type="Crew Change", data=data)
        with_transfer = data["onSigners"][0]["uid"]
        t = Transfer.objects.create(vessel=self.alex_vessel, from_place="airport", to_place="port", at=timezone.now())
        Guest.objects.create(transfer=t, name="A", group="on", crew_uid=with_transfer)
        migration = importlib.import_module("sheet.migrations.0027_crew_transport")
        migration.press_transport(apps, None)
        service.refresh_from_db()
        a, b = service.data["onSigners"]
        self.assertEqual((a["needsTransport"], b["needsTransport"]), (True, False))

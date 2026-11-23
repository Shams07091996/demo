"""Accounting status (Open / Closed) on Calculations rows, set by read-only (accounting) and admins, and the lock."""

from datetime import datetime, timezone

from django.test import override_settings

from .accounting import LOCKED
from .models import ChangeRecord, Guest, HotelStay, Service, Transfer, Vessel, VesselDisposal
from .tests import NEEDED, ApiTestCase

WATER = {"type": "Fresh Water", "data": {"cost": "10", "costCurrency": "EGP"}}
AT = datetime(2026, 11, 13, 8, tzinfo=timezone.utc)


class AccountingTests(ApiTestCase):
    def setUp(self):
        self.viewer, self.alex = self.login("viewer"), self.login("alex")
        self.service = Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water",
                                              data=WATER["data"], status="completed")

    def close(self, client, kind, pk, closed=True):
        return self.call(client, "post", "/api/accounting/", {"kind": kind, "id": pk, "closed": closed})

    def refresh(self):
        self.service.refresh_from_db()
        return self.service

    def test_readonly_and_admin_can_close(self):
        status, body = self.close(self.viewer, "service", self.service.id)
        self.assertEqual((status, body), (200, {"ok": True, "closed": True}))
        self.assertTrue(self.refresh().acct_closed)
        status, _ = self.close(self.login("admin"), "service", self.service.id, False)
        self.assertEqual(status, 200)
        self.assertFalse(self.refresh().acct_closed)

    def test_port_user_cannot_close(self):
        status, _ = self.close(self.alex, "service", self.service.id)
        self.assertEqual(status, 403)
        self.assertFalse(self.refresh().acct_closed)

    def test_accounting_rights_and_scope(self):
        self.assertEqual(self.close(self.viewer, "invoice", self.service.id)[0], 400)
        self.assertEqual(self.close(self.viewer, "service", 999999)[0], 404)
        self.assertEqual(self.call(self.viewer, "post", "/api/accounting/",
                                   {"kind": "service", "id": self.service.id, "closed": "yes"})[0], 400)
        self.assertEqual(self.call(self.viewer, "post", "/api/accounting/",
                                   {"kind": "service", "id": "x", "closed": True})[0], 400)
        # a port user is refused before any lookup, even for a row of its own port
        self.assertEqual(self.close(self.login("suezuser"), "service", self.suez_service.id)[0], 403)

    def test_close_does_not_raise_version(self):
        before = self.refresh().version
        self.close(self.viewer, "service", self.service.id)
        self.assertEqual(self.refresh().version, before)
        record = ChangeRecord.objects.filter(object_type="service", object_id=self.service.id).order_by("id").last()
        self.assertEqual(record.changes, {"acct_closed": [False, True]})

    def test_closed_service_edit_and_delete_refused(self):
        self.close(self.viewer, "service", self.service.id)
        for client in (self.alex, self.login("admin")):
            status, body = self.call(client, "put", f"/api/services/{self.service.id}/", {**WATER, "status": "completed"})
            self.assertEqual((status, body["error"]), (400, LOCKED))
            status, body = self.call(client, "delete", f"/api/services/{self.service.id}/")
            self.assertEqual((status, body["error"]), (400, LOCKED))
        self.assertTrue(Service.objects.filter(pk=self.service.id).exists())

    def test_reopened_service_can_be_edited(self):
        self.close(self.viewer, "service", self.service.id)
        self.close(self.viewer, "service", self.service.id, False)
        status, _ = self.call(self.alex, "put", f"/api/services/{self.service.id}/", {**WATER, "status": "completed"})
        self.assertEqual(status, 200)

    def test_stale_service_save_after_close_is_refused(self):
        version = self.refresh().version  # the dialog opened with this version
        self.close(self.viewer, "service", self.service.id)
        status, body = self.call(self.alex, "put", f"/api/services/{self.service.id}/",
                                 {**WATER, "status": "completed", "version": version})
        self.assertEqual((status, body["error"]), (400, LOCKED))
        self.assertTrue(self.refresh().acct_closed)

    def test_closed_booking_edit_and_delete_refused(self):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="", check_in=AT, nights=1, acct_closed=True)
        Guest.objects.create(stay=stay, name="A")
        status, body = self.call(self.alex, "put", f"/api/hotels/{stay.id}/", {"nights": 2})
        self.assertEqual((status, body["error"]), (400, LOCKED))
        status, body = self.call(self.alex, "delete", f"/api/hotels/{stay.id}/")
        self.assertEqual((status, body["error"]), (400, LOCKED))
        trip = Transfer.objects.create(vessel=self.alex_vessel, from_place="airport", to_place="port", at=AT,
                                       acct_closed=True)
        status, body = self.call(self.alex, "delete", f"/api/transfers/{trip.id}/")
        self.assertEqual((status, body["error"]), (400, LOCKED))

    def test_closed_disposal_change_refused(self):
        VesselDisposal.objects.create(vessel=self.alex_vessel, garbage=2, acct_closed=True)
        for change in ({"garbage": "3"}, {"hidden": True}):
            status, body = self.call(self.alex, "put", f"/api/disposal/{self.alex_vessel.id}/", change)
            self.assertEqual((status, body["error"]), (400, LOCKED), change)

    def test_vessel_delete_refused_when_service_closed(self):
        self.close(self.viewer, "service", self.service.id)
        status, body = self.call(self.alex, "delete", f"/api/vessels/{self.alex_vessel.id}/")
        self.assertEqual((status, body["error"]), (400, LOCKED))
        self.assertTrue(Vessel.objects.filter(pk=self.alex_vessel.id).exists())

    def test_vessel_delete_refused_when_disposal_closed(self):
        vessel = Vessel.objects.create(name="EMPTY", date=self.alex_vessel.date, port="alexandria")
        disposal = VesselDisposal.objects.create(vessel=vessel, garbage=1)
        self.assertEqual(self.close(self.viewer, "disposal", disposal.id)[0], 200)
        status, body = self.call(self.alex, "delete", f"/api/vessels/{vessel.id}/")
        self.assertEqual((status, body["error"]), (400, LOCKED))

    def test_vessel_times_edit_allowed_when_closed(self):
        self.close(self.viewer, "service", self.service.id)
        status, body = self.call(self.alex, "put", f"/api/vessels/{self.alex_vessel.id}/",
                                 {**NEEDED, "name": "ALEX SHIP", "date": "2026-11-13", "arrival_at": "2026-11-13T06:00"})
        self.assertEqual(status, 200, body)

    def test_sync_never_touches_closed_booking(self):
        from . import crewbookings

        crew = {"onSigners": [{"name": "Ahmed Test", "rank": "AB", "needsHotel": True}], "offSigners": []}
        status, vessel = self.call(self.alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                                   {"type": "Crew Change", "data": crew})
        self.assertEqual(status, 201, vessel)
        stay = HotelStay.objects.get(vessel=self.alex_vessel, draft=True)
        HotelStay.objects.filter(pk=stay.pk).update(acct_closed=True)
        Service.objects.filter(service_type="Crew Change").update(data={"onSigners": [], "offSigners": []})
        crewbookings.sync(self.alex_vessel)
        self.assertTrue(HotelStay.objects.filter(pk=stay.pk).exists())

    @override_settings(RATE_LIMIT_WRITES_PER_USER=2, RATE_LIMIT_WRITES_PER_IP=100)
    def test_accounting_is_rate_limited(self):
        codes = [self.close(self.viewer, "service", self.service.id, i % 2 == 0)[0] for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])

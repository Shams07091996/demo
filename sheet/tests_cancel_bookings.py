"""Cancelled hotel stays and transfers, and cancelling a crew change's bookings with it."""

from datetime import date
from decimal import Decimal

from .models import Guest, HotelStay, Service, Vessel
from .tests_logistics import BookingData


class CancelledBookingTests(BookingData):
    def create(self, **extra):
        status, row = self.call(self.login("alex"), "post", "/api/hotels/", self.payload(**extra))
        self.assertEqual(status, 201, row)
        return row

    def test_booking_cancelled_saved_and_returned(self):
        row = self.create()
        self.assertIs(row["cancelled"], False)
        status, row = self.call(self.login("alex"), "put", f"/api/hotels/{row['id']}/",
                                self.payload(cancelled=True, cost_per_night="0", revenue_per_night="0"))
        self.assertEqual(status, 200, row)
        self.assertIs(row["cancelled"], True)
        self.assertTrue(HotelStay.objects.get(pk=row["id"]).cancelled)
        status, _ = self.call(self.login("alex"), "put", f"/api/hotels/{row['id']}/", self.payload(cancelled="yes"))
        self.assertEqual(status, 400)

    def test_put_without_cancelled_keeps_it(self):
        row = self.create(cancelled=True)
        status, row = self.call(self.login("alex"), "put", f"/api/hotels/{row['id']}/", self.payload())
        self.assertEqual(status, 200, row)
        self.assertIs(row["cancelled"], True)

    def test_cancelled_booking_raises_no_alert(self):
        vessel = Vessel.objects.create(name="GONE", date=date(2026, 1, 5), port="alexandria", arrival_agent="A",
                                       sailing_agent="B")
        stay = HotelStay.objects.create(vessel=vessel, hotel="HILTON", check_in=date(2026, 1, 5), nights=1)
        Guest.objects.create(stay=stay, name="J SMITH")

        def missing():
            rows = [r for r in self.call(self.login("admin"), "get", "/api/vessels/alerts/")[1]["missing"]
                    if r["id"] == vessel.id]
            return rows[0]["missing"] if rows else []

        self.assertIn("Hotel: J SMITH", missing())
        HotelStay.objects.filter(pk=stay.pk).update(cancelled=True)
        self.assertNotIn("Hotel: J SMITH", missing())

    def test_cancelled_booking_line_status(self):
        HotelStay.objects.filter(vessel=self.alex_vessel).delete()
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 13), nights=1,
                                        cost_per_night=Decimal("50"), cancelled=True)  # a cancellation fee
        rows = self.login("viewer").get("/api/calculations/", {"port": "alexandria"}).json()["rows"]
        line = next(r for r in rows if r["ref"] == {"kind": "hotel", "id": stay.id})
        self.assertEqual(line["status"], "cancelled")
        rows = self.login("viewer").get("/api/calculations/", {"port": "alexandria", "status": "cancelled"}).json()
        self.assertIn({"kind": "hotel", "id": stay.id}, [r["ref"] for r in rows["rows"]])


CREW = {"onSigners": [{"name": "Ahmed Test", "rank": "AB", "needsHotel": True}], "offSigners": []}


class CancelWithCrewChangeTests(BookingData):
    """Choosing Cancelled on a crew change can cancel its saved bookings in the same save."""

    def setUp(self):
        self.alex = self.login("alex")
        status, vessel = self.call(self.alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                                   {"type": "Crew Change", "data": CREW})
        self.assertEqual(status, 201, vessel)
        self.service = Service.objects.get(pk=vessel["services"][-1]["id"])
        # the person saves the draft hotel stay (it keeps the crew link), with a price
        self.stay = HotelStay.objects.get(vessel=self.alex_vessel, draft=True)
        HotelStay.objects.filter(pk=self.stay.pk).update(draft=False, hotel="HILTON", cost_per_night=Decimal("80"),
                                                         revenue_per_night=Decimal("100"))

    def bookings(self):
        status, body = self.call(self.alex, "get", f"/api/services/{self.service.id}/bookings/")
        self.assertEqual(status, 200, body)
        return body["bookings"]

    def cancel(self, refs, **extra):
        payload = {"type": "Crew Change", "data": self.service.data, "status": "cancelled",
                   "cancel_reason": "Owner cancelled", "cancel_bookings": refs, **extra}
        return self.call(self.alex, "put", f"/api/services/{self.service.id}/", payload)

    def test_saved_bookings_listed(self):
        self.assertEqual([(b["kind"], b["id"], b["cancelled"], b["closed"]) for b in self.bookings()],
                         [("hotel", self.stay.id, False, False)])  # the draft transfer is not listed
        self.assertIn("AHMED TEST", self.bookings()[0]["guests"])
        other = Service.objects.create(vessel=self.suez_vessel, service_type="Crew Change", data=CREW)
        self.assertEqual(self.call(self.alex, "get", f"/api/services/{other.id}/bookings/")[0], 404)

    def test_cancel_bookings_with_crew_change(self):
        status, body = self.cancel([{"kind": "hotel", "id": self.stay.id}])
        self.assertEqual(status, 200, body)
        stay = HotelStay.objects.get(pk=self.stay.pk)
        self.assertEqual((stay.cancelled, stay.cost_per_night, stay.revenue_per_night, stay.version),
                         (True, Decimal("0"), Decimal("0"), self.stay.version + 1))
        self.assertTrue(self.bookings()[0]["cancelled"])

    def test_untick_keeps_the_booking(self):
        status, body = self.cancel([])
        self.assertEqual(status, 200, body)
        self.assertFalse(HotelStay.objects.get(pk=self.stay.pk).cancelled)

    def test_cancel_bookings_refused(self):
        other = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 13), nights=1)
        for refs in ([{"kind": "hotel", "id": other.id}], [{"kind": "car", "id": self.stay.id}],
                     [{"kind": "hotel", "id": "x"}], "all", [{"kind": "hotel", "id": True}]):
            status, _ = self.cancel(refs)
            self.assertEqual(status, 400, refs)
        status, _ = self.cancel([{"kind": "hotel", "id": self.stay.id}], status="completed", cancel_reason="")
        self.assertEqual(status, 400)
        HotelStay.objects.filter(pk=self.stay.pk).update(acct_closed=True)
        status, body = self.cancel([{"kind": "hotel", "id": self.stay.id}])
        self.assertEqual((status, body["error"]), (400, "Accounting has closed this. Ask accounting to reopen it first."))
        self.assertEqual(Service.objects.get(pk=self.service.pk).status, "in_progress")  # nothing saved
        self.assertFalse(HotelStay.objects.get(pk=self.stay.pk).cancelled)

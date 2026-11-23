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


__all__ = ["CancelledBookingTests", "Service"]

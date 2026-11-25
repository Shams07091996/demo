"""Parcel extras (piece 2 of the HTML gaps): transfer type, receiving vessel, courier, payment, delivery status."""

from django.test import SimpleTestCase

from .constants import PERMISSION_KEYS, SERVICE_FIELDS
from .errors import BadRequest
from .models import Service
from .tests import ApiTestCase, make_user
from .validators import clean_service_data

ENTRY = {"awb": "A1", "cost": 10, "revenue": 20}


class ParcelFieldTests(SimpleTestCase):
    def test_table(self):
        keys = lambda t: [f["key"] for f in SERVICE_FIELDS[t]["fields"]]  # noqa: E731
        for t in ("Delivery Parcels", "Landing"):
            self.assertEqual(keys(t), ["transferType", "receivingVessel", "courier", "payment"])
        self.assertEqual(keys("Delivery Courier"), ["courier", "deliveryStatus", "payment"])

    def test_vessel_to_vessel(self):
        data = clean_service_data("Landing", {"entries": [ENTRY], "transferType": "Vessel-to-Vessel",
                                              "receivingVessel": "MSC LUNA", "payment": "Paid"})
        self.assertEqual((data["transferType"], data["receivingVessel"], data["courier"], data["payment"]),
                         ("Vessel-to-Vessel", "MSC LUNA", "", "Paid"))
        self.assertEqual(data["entries"][0]["awb"], "A1")

    def test_vessel_to_courier(self):
        data = clean_service_data("Delivery Parcels", {"transferType": "Vessel-to-Courier", "courier": "DHL"})
        self.assertEqual((data["courier"], data["receivingVessel"]), ("DHL", ""))

    def test_courier_service(self):
        data = clean_service_data("Delivery Courier", {"courier": "Aramex", "deliveryStatus": "Dispatched",
                                                       "payment": "Not Paid"})
        self.assertEqual((data["courier"], data["deliveryStatus"], data["payment"]), ("Aramex", "Dispatched", "Not Paid"))

    def refused(self, message, service_type="Landing", **raw):
        with self.assertRaisesMessage(BadRequest, message):
            clean_service_data(service_type, raw)

    def test_refusals(self):
        self.refused("Receiving vessel is only for Vessel-to-Vessel.", transferType="Vessel-to-Courier",
                     receivingVessel="X")
        self.refused("Receiving vessel is only for Vessel-to-Vessel.", receivingVessel="X")
        self.refused("Courier is only for Vessel-to-Courier.", transferType="Vessel-to-Vessel", courier="DHL")
        self.refused("Courier: choose one of DHL, FedEx, Aramex or Other.", "Delivery Courier", courier="UPS")
        self.refused("Transfer type: choose Vessel-to-Vessel or Vessel-to-Courier.", transferType="Ship")
        self.refused("Delivery status: choose one of Pending, Dispatched or Delivered.", "Delivery Courier",
                     deliveryStatus="Lost")

    def test_old_service_without_fields(self):
        data = clean_service_data("Delivery Parcels", {"entries": [{**ENTRY, "weight": 2}]})
        self.assertEqual((data["transferType"], data["payment"], data["entries"][0]["weight"]), ("", "", 2.0))


class ParcelApiTests(ApiTestCase):
    def test_saved_without_money_edit_keeps_money(self):
        stored = clean_service_data("Landing", {"entries": [ENTRY]})
        service = Service.objects.create(vessel=self.alex_vessel, service_type="Landing", data=stored)
        make_user("nomoney", "alexandria", permissions=[k for k in PERMISSION_KEYS if k != "money.edit"])
        uid = stored["entries"][0]["uid"]
        payload = {"type": "Landing", "data": {"entries": [{"uid": uid, "awb": "A1"}], "payment": "Paid",
                                               "transferType": "Vessel-to-Courier", "courier": "FedEx"}}
        status, body = self.call(self.login("nomoney"), "put", f"/api/services/{service.id}/", payload)
        self.assertEqual(status, 200, body)
        service.refresh_from_db()
        self.assertEqual((service.data["payment"], service.data["courier"], service.data["entries"][0]["cost"]),
                         ("Paid", "FedEx", 10.0))

"""The services' own detail fields (constants.SERVICE_FIELDS): cleaning, money line labels, the page context."""

import json
import re

from django.test import SimpleTestCase

from . import finance
from .constants import PERMISSION_KEYS, RATE_UNITS, SERVICE_FIELDS, SERVICE_TYPES
from .errors import BadRequest
from .models import Service
from .tests import ApiTestCase, make_user
from .validators import clean_service_data

NEW = ("Suez Canal Transit", "Surveyors Attendance", "Supply", "SIM Cards", "Tourism Tours")


class FieldTableTests(SimpleTestCase):
    def test_new_types_listed_before_cash_to_master(self):
        at = SERVICE_TYPES.index
        self.assertEqual([at(t) for t in NEW], list(range(at("Fresh Water") + 1, at("Cash to Master"))))
        for t in NEW:
            self.assertIn(t, SERVICE_FIELDS)
            self.assertIn(t, RATE_UNITS)
        self.assertEqual(RATE_UNITS["SIM Cards"], "unit")
        self.assertEqual(RATE_UNITS["Suez Canal Transit"], "service")

    def test_suez_fields(self):
        keys = [f["key"] for f in SERVICE_FIELDS["Suez Canal Transit"]["fields"]]
        self.assertEqual(keys, ["direction", "originPort", "destinationPort", "expectedTransit", "etaSuez",
                                "bookingRef", "canalAgent", "convoyNo", "pilotBoarding", "canalEntry", "canalExit",
                                "scaInvoice"])
        self.assertEqual(SERVICE_FIELDS["Suez Canal Transit"]["cost_label"], "SCA charges")
        self.assertEqual(SERVICE_FIELDS["Suez Canal Transit"]["cost_currency"], "USD")


class CleaningTests(SimpleTestCase):
    def test_every_field_present_unknown_dropped(self):
        data = clean_service_data("Suez Canal Transit", {"direction": "Northbound", "canalEntry": "2026-11-20T10:00",
                                                         "expectedTransit": "2026-11-21", "junk": 1, "cost": 5})
        self.assertNotIn("junk", data)
        self.assertEqual((data["direction"], data["canalEntry"], data["expectedTransit"], data["convoyNo"]),
                         ("Northbound", "2026-11-20T10:00", "2026-11-21", ""))
        self.assertEqual(data["cost"], 5.0)

    def test_numbers(self):
        data = clean_service_data("Surveyors Attendance", {"count": "3", "names": "A; B"})
        self.assertEqual((data["count"], data["names"]), (3.0, "A; B"))
        self.assertIsNone(clean_service_data("SIM Cards", {})["quantity"])

    def refused(self, service_type, message, **raw):
        with self.assertRaisesMessage(BadRequest, message):
            clean_service_data(service_type, raw)

    def test_refusals(self):
        self.refused("Surveyors Attendance", "Names is too long", names="x" * 501)
        self.refused("Surveyors Attendance", "Number of people", count="abc")
        self.refused("SIM Cards", "Number of cards", quantity=-1)
        self.refused("Tourism Tours", "Date: enter a valid date", tourDate="20.11.2026")
        self.refused("Suez Canal Transit", "Canal entry: enter a valid date and time", canalEntry="2026-11-20T10:00:00")
        self.refused("Suez Canal Transit", "Canal entry: enter a valid date and time", canalEntry="2026-11-20T10:00+02:00")
        self.refused("Suez Canal Transit", "Direction: choose Northbound or Southbound", direction="East")

    def test_old_services_unchanged(self):
        self.assertEqual(clean_service_data("Medical Treatment", {"patientName": "A"})["patientName"], "A")
        self.assertEqual(clean_service_data("Certificates", {"certName": "B"})["certName"], "B")
        self.assertEqual(clean_service_data("Fresh Water", {"quantity": 5})["quantity"], 5.0)

    def test_cash_to_master_reference(self):
        data = clean_service_data("Cash to Master", {"amount": 100, "percentage": 5, "reference": "R1",
                                                     "beneficiary": "Master"})
        self.assertEqual((data["reference"], data["beneficiary"], data["amount"]), ("R1", "Master", 100.0))


class LabelTests(SimpleTestCase):
    def label(self, service_type, raw):
        return finance.service_lines(service_type, clean_service_data(service_type, {**raw, "cost": 1}), 50)[0]["label"]

    def test_line_labels(self):
        self.assertEqual(self.label("Suez Canal Transit", {"direction": "Northbound"}), "Suez Canal Transit · Northbound")
        self.assertEqual(self.label("Surveyors Attendance", {"count": 3}), "Surveyors Attendance · 3 people")
        self.assertEqual(self.label("SIM Cards", {"quantity": 5}), "SIM Cards · 5 cards")
        self.assertEqual(self.label("Supply", {"description": "Provisions"}), "Supply · Provisions")
        self.assertEqual(self.label("Tourism Tours", {}), "Tourism Tours")
        self.assertEqual(self.label("Fresh Water", {"quantity": 5}), "Fresh Water · 5 t")
        self.assertEqual(self.label("Medical Treatment", {"patientName": "A"}), "Medical Treatment · A")


class ApiTests(ApiTestCase):
    def test_page_carries_the_table(self):
        html = self.login("alex").get("/").content.decode()
        found = re.search(r'<script id="service-fields-data" type="application/json">(.*?)</script>', html)
        self.assertEqual(json.loads(found[1])["Suez Canal Transit"]["fields"][0]["key"], "direction")

    def test_new_service_saved(self):
        payload = {"type": "Suez Canal Transit", "data": {"direction": "Southbound", "cost": 1000, "costCurrency": "USD"}}
        status, _ = self.call(self.login("alex"), "post", f"/api/vessels/{self.alex_vessel.id}/services/", payload)
        self.assertEqual(status, 201)
        self.assertEqual(Service.objects.get(service_type="Suez Canal Transit").data["direction"], "Southbound")

    def test_reference_saved_without_money_edit(self):
        stored = clean_service_data("Cash to Master", {"amount": 100, "percentage": 5})
        service = Service.objects.create(vessel=self.alex_vessel, service_type="Cash to Master", data=stored)
        make_user("nomoney", "alexandria", permissions=[k for k in PERMISSION_KEYS if k != "money.edit"])
        payload = {"type": "Cash to Master", "data": {"reference": "R9", "beneficiary": "Master"}}
        status, body = self.call(self.login("nomoney"), "put", f"/api/services/{service.id}/", payload)
        self.assertEqual(status, 200, body)
        service.refresh_from_db()
        self.assertEqual((service.data["reference"], service.data["amount"], service.data["percentage"]),
                         ("R9", 100.0, 5.0))

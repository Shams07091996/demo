"""The master receipt: the pre-filled text (GET) and the PDF made from the edited text (POST)."""

import json

from django.test import override_settings
from django.utils import timezone

from .models import ChangeRecord, Service
from .tests import ApiTestCase
from .validators import clean_service_data

EDITED = {"port": "Alexandria", "date": "20/11/2026", "vessel": "ALEX SHIP",
          "services": "Arrange 5 shore pass with cost $50"}


@override_settings(RATE_LIMIT_EXPORTS_PER_USER=20)
class ReceiptTests(ApiTestCase):
    def service(self, service_type, data, vessel=None):
        return Service.objects.create(vessel=vessel or self.alex_vessel, service_type=service_type,
                                      data=clean_service_data(service_type, data))

    def url(self, service):
        return f"/api/services/{service.id}/receipt/"

    def prefill(self, service, user="alex"):
        status, body = self.call(self.login(user), "get", self.url(service))
        self.assertEqual(status, 200, body)
        return body["receipt"]

    def post(self, client, service, payload):
        return client.post(self.url(service), data=json.dumps(payload), content_type="application/json",
                           HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)

    def test_prefill_single_usd(self):
        receipt = self.prefill(self.service("Medical Treatment", {"revenue": 120, "revenueCurrency": "USD"}))
        self.assertEqual(receipt["services"], "Medical Treatment with cost $120")
        self.assertEqual(receipt["port"], "Alexandria")
        self.assertEqual(receipt["vessel"], "ALEX SHIP")
        self.assertEqual(receipt["date"], timezone.localdate().strftime("%d/%m/%Y"))

    def test_prefill_entries_two_currencies(self):
        entries = [{"awb": "1", "revenue": 100, "revenueCurrency": "USD"},
                   {"awb": "2", "revenue": 20.5, "revenueCurrency": "USD"},
                   {"awb": "3", "revenue": 3000, "revenueCurrency": "EGP"}]
        receipt = self.prefill(self.service("Landing", {"entries": entries}))
        self.assertEqual(receipt["services"], "Landing with cost $120.50 and EGP 3,000")

    def test_prefill_no_revenue(self):
        self.assertEqual(self.prefill(self.service("Fresh Water", {}))["services"], "Fresh Water")
        self.assertEqual(self.prefill(self.service("Fresh Water", {"revenue": 0}))["services"], "Fresh Water")

    def test_prefill_others_uses_note(self):
        service = self.service("Others / Remarks", {"note": "Arrange 5 shore pass\nsecond line", "revenue": 50,
                                                    "revenueCurrency": "USD"})
        self.assertEqual(self.prefill(service)["services"], "Arrange 5 shore pass with cost $50")

    def test_prefill_cash_to_master(self):
        service = self.service("Cash to Master", {"amount": 1000, "amountCurrency": "USD", "percentage": 5})
        self.assertEqual(self.prefill(service)["services"], "Cash to Master with cost $50")

    def test_prefill_crew_change_includes_broken_visa(self):
        # Review finding: a broken-visa revenue is part of what the vessel is charged for the crew change.
        on = {"name": "A ON", "brokenVisa": {"revenue": 80, "revenueCurrency": "USD"}}
        service = self.service("Crew Change", {"onSigners": [on], "revenue": 200, "revenueCurrency": "USD"})
        self.assertEqual(self.prefill(service)["services"], "Crew Change with cost $280")

    def test_post_returns_pdf_and_history(self):
        service = self.service("Others / Remarks", {"note": "x"})
        response = self.post(self.login("alex"), service, EDITED)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"(Arrange 5 shore pass with cost $50)", response.content)
        self.assertTrue(response["Content-Disposition"].startswith('attachment; filename="Receipt ALEX SHIP'))
        self.assertEqual(ChangeRecord.objects.filter(action="receipt").count(), 1)

    def test_blank_services_refused(self):
        service = self.service("Fresh Water", {})
        response = self.post(self.login("alex"), service, {**EDITED, "services": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Write the services.")

    def test_too_long_refused(self):
        service = self.service("Fresh Water", {})
        client = self.login("alex")
        self.assertEqual(self.post(client, service, {**EDITED, "services": "x" * 2001}).status_code, 400)
        self.assertEqual(self.post(client, service, {**EDITED, "services": "\n".join(["x"] * 41)}).status_code, 400)
        self.assertEqual(self.post(client, service, {**EDITED, "vessel": "x" * 81}).status_code, 400)

    def test_other_port_not_found(self):
        service = self.service("Fresh Water", {})
        client = self.login("suezuser")
        self.assertEqual(self.call(client, "get", self.url(service))[0], 404)
        self.assertEqual(self.post(client, service, EDITED).status_code, 404)

    def test_anonymous_refused(self):
        from django.test import Client

        self.assertIn(Client().get(self.url(self.suez_service)).status_code, (401, 302))

    def test_rate_limited(self):
        service = self.service("Fresh Water", {})
        with override_settings(RATE_LIMIT_EXPORTS_PER_USER=2):
            client = self.login("alex")
            codes = [self.post(client, service, EDITED).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

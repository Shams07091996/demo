"""Exceptional conditions (A10) and alerting (A09): errors answer JSON with a reference; bursts raise one alert."""

import re
from unittest import mock

from django.core import mail
from django.test import Client, override_settings

from .tests import FAST_HASHER, ApiTestCase


@FAST_HASHER
class ErrorResponseTests(ApiTestCase):
    def test_unexpected_exception_in_an_api_view_answers_json_with_a_ref(self):
        alex = self.login("alex")
        with (
            mock.patch("sheet.listing.list_response", side_effect=RuntimeError("boom")),
            self.assertLogs("sheet.security", level="ERROR") as logs,
            self.assertLogs("django.request", level="ERROR"),
        ):
            response = alex.get("/api/vessels/")
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data["error"], "Something went wrong.")
        self.assertRegex(data["ref"], r"^[0-9a-f]{8}$")
        self.assertNotIn("boom", response.content.decode())
        self.assertTrue(any(data["ref"] in line for line in logs.output))

    def test_unknown_api_url_answers_json_404(self):
        response = self.login("alex").get("/api/nope/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("error", response.json())

    def test_unknown_page_answers_plain_html_404(self):
        response = Client().get("/nope/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response["Content-Type"].startswith("text/html"))
        text = response.content.decode()
        self.assertNotIn("Traceback", text)
        self.assertNotIn("Django", text)

    def test_unexpected_exception_outside_the_api_answers_plain_html_500_with_a_ref(self):
        client = Client(raise_request_exception=False)
        self.assertTrue(client.login(username="alex", password="correct-horse-battery"))
        with (
            mock.patch("sheet.listing.parse_filters", side_effect=RuntimeError("boom")),
            self.assertLogs("sheet.security", level="ERROR") as logs,
            self.assertLogs("django.request", level="ERROR"),
        ):
            response = client.get("/export.csv")
        self.assertEqual(response.status_code, 500)
        text = response.content.decode()
        self.assertNotIn("Traceback", text)
        self.assertNotIn("boom", text)
        ref = re.search(r"[0-9a-f]{8}", text.split("Reference", 1)[1]).group(0)
        self.assertTrue(any(ref in line for line in logs.output))


@FAST_HASHER
@override_settings(ALERT_THRESHOLD=10, RATE_LIMIT_WRITES_PER_USER=1000)
class AlertTests(ApiTestCase):
    def deny(self, client, times):
        for _ in range(times):
            self.assertEqual(self.call(client, "post", "/api/vessels/", {"name": "X", "date": "2026-11-13"})[0], 403)

    def test_ten_denied_requests_raise_exactly_one_alert(self):
        viewer = self.login("viewer")
        with self.assertLogs("sheet.alert", level="ERROR") as logs:
            self.deny(viewer, 11)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("denied", logs.output[0])

    def test_nine_denied_requests_raise_none(self):
        viewer = self.login("viewer")
        with self.assertNoLogs("sheet.alert", level="ERROR"):
            self.deny(viewer, 9)

    @override_settings(ADMINS=[("Security", "security@example.com")])
    def test_alert_is_mailed_when_admins_are_set(self):
        self.deny(self.login("viewer"), 10)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("denied", mail.outbox[0].subject)

    @override_settings(ADMINS=[])
    def test_no_mail_without_admins(self):
        self.deny(self.login("viewer"), 10)
        self.assertEqual(len(mail.outbox), 0)

    def test_server_errors_are_counted_too(self):
        alex = self.login("alex")
        with (
            mock.patch("sheet.listing.list_response", side_effect=RuntimeError("boom")),
            self.assertLogs("sheet.alert", level="ERROR") as logs,
            self.assertLogs("sheet.security", level="ERROR"),
            self.assertLogs("django.request", level="ERROR"),
        ):
            for _ in range(10):
                alex.get("/api/vessels/")
        self.assertIn("server_error", logs.output[0])

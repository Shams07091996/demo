"""API rate limits: writes and CSV exports are counted per user and per address (A06)."""

from unittest import mock

from django.db import DatabaseError
from django.test import TestCase, override_settings

from .tests import FAST_HASHER, NEEDED, ApiTestCase

LIMITS = override_settings(
    RATE_LIMIT_WRITES_PER_USER=3, RATE_LIMIT_WRITES_PER_IP=100, RATE_LIMIT_EXPORTS_PER_USER=3
)


@FAST_HASHER
@LIMITS
class RateLimitTests(ApiTestCase):
    def new_vessel(self, client, name="RATE"):
        return self.call(client, "post", "/api/vessels/", {**NEEDED, "name": name, "date": "2026-11-13", "port": "alexandria"})

    def test_fourth_write_by_one_user_is_refused(self):
        alex = self.login("alex")
        for _ in range(3):
            self.assertEqual(self.new_vessel(alex)[0], 201)
        status, data = self.new_vessel(alex)
        self.assertEqual(status, 429)
        self.assertIn("Too many requests", data["error"])

    def test_another_user_is_not_affected(self):
        alex = self.login("alex")
        for _ in range(4):
            self.new_vessel(alex)
        self.assertEqual(self.new_vessel(self.login("admin"))[0], 201)

    def test_reads_are_never_limited(self):
        alex = self.login("alex")
        for _ in range(10):
            self.assertEqual(alex.get("/api/vessels/").status_code, 200)
        self.assertEqual(self.new_vessel(alex)[0], 201)

    def test_per_address_limit(self):
        with override_settings(RATE_LIMIT_WRITES_PER_USER=100, RATE_LIMIT_WRITES_PER_IP=3):
            alex, admin = self.login("alex"), self.login("admin")
            self.new_vessel(alex)
            self.new_vessel(alex)
            self.new_vessel(admin)
            self.assertEqual(self.new_vessel(admin)[0], 429)

    def test_fourth_export_is_refused(self):
        alex = self.login("alex")
        for _ in range(3):
            self.assertEqual(alex.get("/export.csv").status_code, 200)
        response = alex.get("/export.csv")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many requests", response.json()["error"])

    def test_counter_failure_refuses_writes_and_allows_reads(self):
        alex = self.login("alex")
        broken = mock.MagicMock()
        for method in ("filter", "get", "create", "update", "get_or_create", "values_list"):
            getattr(broken, method).side_effect = DatabaseError("counter table is gone")
        with mock.patch("sheet.ratelimit.RateCounter.objects", broken):
            status, data = self.new_vessel(alex)
            self.assertEqual(status, 503)
            self.assertIn("error", data)
            self.assertEqual(alex.get("/api/vessels/").status_code, 200)
            self.assertEqual(alex.get("/export.csv").status_code, 200)


class CounterTidyTests(TestCase):
    @override_settings(ALERT_WINDOW_SECONDS=7200)
    def test_a_long_alert_window_survives_the_tidy(self):
        from datetime import timedelta

        from django.utils import timezone

        from . import ratelimit
        from .models import RateCounter

        RateCounter.objects.create(key="alert|denied", count=5, window_start=timezone.now() - timedelta(minutes=90))
        ratelimit.hit("write|user|1", ratelimit.window())
        self.assertEqual(RateCounter.objects.get(key="alert|denied").count, 5)

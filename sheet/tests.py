import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings

from config.database import build_database_settings

from . import finance, throttle
from .errors import BadRequest
from .models import (
    ExchangeRate,
    HotelStay,
    LoginAttempt,
    Option,
    PortClosure,
    Profile,
    Service,
    Ship,
    Transfer,
    Vessel,
)
from .validators import clean_service_data, clean_summary

PASSWORD = "correct-horse-battery"
# A new vessel needs an OPR and a POC from Master data (ApiTestCase lists these two for All ports).
NEEDED = {"opr": "TEST OPR", "poc": "TEST POC"}
VERSIONED_URL = re.compile(r"^/api/(vessels|services|hotels|transfers|closures)/(\d+)/$")
VERSIONED_MODELS = {"vessels": Vessel, "services": Service, "hotels": HotelStay, "transfers": Transfer,
                    "closures": PortClosure}
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])  # tests only


def pass_two_step(client, username):
    """Tests only: this signed-in client has passed the code step (as if it had typed a right code)."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from .twostep import SESSION_KEY

    user = User.objects.get(username=username)
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    device = device or TOTPDevice.objects.create(user=user, name="Authenticator", confirmed=True)
    session = client.session
    session[SESSION_KEY] = {"how": "code", "ref": device.pk}
    session.save()
    return client


def allow(kind, *values, port=""):
    """Put values in a Master data list (the API only accepts listed OPR / POC / agent / hotel / airport / port)."""
    for value in values:
        Option.objects.get_or_create(kind=kind, value=value, port=port)


def make_user(username, ports):
    """"admin": a superuser (an Admin, every port); a port key or a list of keys: a User of those ports (the first
    is the home port)."""
    if ports == "admin":
        user = User.objects.create_superuser(username, password=PASSWORD)
        Profile.objects.create(user=user)
        return user
    ports = [ports] if isinstance(ports, str) else list(ports)
    user = User.objects.create_user(username, password=PASSWORD)
    Profile.objects.create(user=user, home_port=ports[0], ports=ports)
    return user


@FAST_HASHER
class ApiTestCase(TestCase):
    """Base class: an Admin, a three-port User (viewer: Alexandria, Port Said, Damietta), two one-port Users and a
    vessel in two ports."""

    @classmethod
    def setUpTestData(cls):
        for name, ports in [("admin", "admin"), ("viewer", ["alexandria", "portsaid", "damietta"]), ("alex", "alexandria"),
                            ("suezuser", "suez")]:
            make_user(name, ports)
        allow("opr", NEEDED["opr"])
        allow("poc", NEEDED["poc"])
        # New vessels need a ship: `call` adds this one to a vessel POST that names none (tests_ships checks the rule).
        cls.test_ship = Ship.objects.create(name="TEST SHIP", imo="9321483", opr=NEEDED["opr"])
        cls.alex_vessel = Vessel.objects.create(name="ALEX SHIP", date=date(2026, 11, 13), port="alexandria")
        cls.suez_vessel = Vessel.objects.create(name="SUEZ SHIP", date=date(2026, 11, 13), port="suez")
        cls.suez_service = Service.objects.create(
            vessel=cls.suez_vessel, service_type="Fresh Water", data={"cost": 10, "costCurrency": "EGP"}
        )

    def login(self, username):
        client = Client(enforce_csrf_checks=True)
        self.assertTrue(client.login(username=username, password=PASSWORD))
        pass_two_step(client, username)
        client.get("/")  # sets the CSRF cookie
        return client

    def call(self, client, method, url, payload=None):
        """An API request. An update of a vessel / service / booking / closure that doesn't say which version it
        edits gets the current one (the edit-conflict check itself is tested in tests_conflicts_api)."""
        token = client.cookies["csrftoken"].value
        found = VERSIONED_URL.match(url)
        if found and method in ("put", "patch") and isinstance(payload, dict) and "version" not in payload:
            model = VERSIONED_MODELS[found[1]]
            current = model.objects.filter(pk=found[2]).values_list("version", flat=True).first()
            payload = {**payload, "version": current or 1}
        if method == "post" and url == "/api/vessels/" and isinstance(payload, dict) and "ship_id" not in payload:
            payload = {**payload, "ship_id": self.test_ship.id}
        kwargs = {"content_type": "application/json", "HTTP_X_CSRFTOKEN": token}
        if payload is not None:
            kwargs["data"] = json.dumps(payload)
        response = getattr(client, method)(url, **kwargs)
        return response.status_code, response.json() if response["Content-Type"].startswith(
            "application/json"
        ) else None


class FinanceTests(SimpleTestCase):
    def test_single_service_converts_usd_with_month_rate(self):
        data = {"revenue": 900, "revenueCurrency": "USD", "cost": 30000, "costCurrency": "EGP"}
        result = finance.compute("Fresh Water", data, 50)
        self.assertEqual((result["revenue_egp"], result["cost_egp"], result["profit_egp"]), (45000, 30000, 15000))
        self.assertFalse(result["rate_missing"])

    def test_override_rate_beats_month_rate(self):
        data = {"revenue": 10, "revenueCurrency": "USD", "exchangeRate": 60}
        self.assertEqual(finance.compute("Certificates", data, 50)["revenue_egp"], 600)

    def test_missing_rate_is_flagged_and_counted_one_to_one(self):
        result = finance.compute("Certificates", {"revenue": 10, "revenueCurrency": "USD"}, None)
        self.assertTrue(result["rate_missing"])
        self.assertEqual(result["revenue_egp"], 10)

    def test_multi_entry_sums_entries(self):
        data = {
            "entries": [
                {"cost": 100, "costCurrency": "EGP", "revenue": 10, "revenueCurrency": "USD"},
                {"cost": 50, "costCurrency": "EGP", "revenue": 0, "revenueCurrency": "EGP"},
            ],
            "exchangeRate": 60,
        }
        result = finance.compute("Delivery Courier", data, None)
        self.assertEqual((result["cost_egp"], result["revenue_egp"], result["profit_egp"]), (150, 600, 450))
        self.assertEqual(result["entries"][0]["profit_egp"], 500)

    def test_cash_to_master_revenue_is_part_of_the_amount(self):
        data = {"amount": 1000, "amountCurrency": "USD", "shareMode": "percent", "percentage": 5}
        result = finance.compute("Cash to Master", data, 50)
        self.assertEqual(result["revenue_egp"], 2500)  # 5% of 1000 USD
        self.assertEqual(result["to_master_egp"], 47500)  # the other 95%
        self.assertEqual(result["cost_egp"], 0)
        self.assertEqual(result["profit_egp"], 2500)
        self.assertEqual(result["revenue_egp"] + result["to_master_egp"], 1000 * 50)

    def test_cash_to_master_fixed_share_and_clamping(self):
        fixed = {"amount": 200, "amountCurrency": "EGP", "shareMode": "fixed", "fixedRevenue": 30}
        self.assertEqual(finance.compute("Cash to Master", fixed, None)["to_master_egp"], 170)
        too_big = {"amount": 200, "amountCurrency": "EGP", "shareMode": "fixed", "fixedRevenue": 999}
        result = finance.compute("Cash to Master", too_big, None)
        self.assertEqual((result["revenue_egp"], result["to_master_egp"]), (200, 0))  # can never exceed the amount

    def test_non_money_services_are_zero(self):
        self.assertEqual(finance.compute("Crew Change", {}, 50)["profit_egp"], 0)

    def test_garbage_numbers_are_zero(self):
        data = {"cost": "abc", "revenue": float("inf"), "revenueCurrency": "USD"}
        self.assertEqual(finance.compute("Fresh Water", data, 50)["profit_egp"], 0)


class ValidatorTests(SimpleTestCase):
    def test_currencies_are_sanitised_and_unknown_keys_dropped(self):
        cleaned = clean_service_data("Fresh Water", {"cost": "12.5", "revenue": "", "costCurrency": "BTC", "evil": 1})
        self.assertEqual((cleaned["cost"], cleaned["revenue"], cleaned["costCurrency"]), (12.5, None, "EGP"))
        self.assertNotIn("evil", cleaned)

    def test_bad_numbers_are_refused_not_dropped(self):
        for raw in ({"cost": "abc"}, {"revenue": "1e999"}, {"cost": -1}):
            with self.subTest(raw=raw), self.assertRaises(BadRequest):
                clean_service_data("Fresh Water", raw)

    def test_cash_percentage_outside_0_to_100_is_refused(self):
        with self.assertRaises(BadRequest):
            clean_service_data("Cash to Master", {"percentage": "500"})

    def test_too_many_entries_refused_and_non_dicts_dropped(self):
        with self.assertRaises(BadRequest):
            clean_service_data("Landing", {"entries": [{"awb": "x"}] * 101})
        cleaned = clean_service_data("Landing", {"entries": [{"awb": "x"}] * 99 + ["junk"]})
        self.assertEqual(len(cleaned["entries"]), 99)

    def test_crew_structured_data_is_kept_but_trimmed(self):
        raw = {
            "onSigners": [
                {
                    "name": "A" * 500,
                    "personalStructured": {"rank": "2/E", "x": "dropped"},
                    "flightStructured": {"segments": [{"flightNo": "TK1", "junk": "x"}]},
                }
            ]
        }
        member = clean_service_data("Crew Change", raw)["onSigners"][0]
        self.assertEqual(len(member["name"]), 120)
        self.assertEqual(member["personalStructured"], {"rank": "2/E"})
        self.assertEqual(member["flightStructured"]["segments"][0]["flightNo"], "TK1")
        self.assertNotIn("junk", member["flightStructured"]["segments"][0])

    def test_summary_keeps_only_known_fields(self):
        self.assertEqual(
            clean_summary({"Vendor Name": " ACME ", "Nope": "x", "Vendor Invoice": ""}), {"Vendor Name": "ACME"}
        )


class AccessTests(ApiTestCase):
    def test_anonymous_users_are_rejected(self):
        client = Client()
        self.assertEqual(client.get("/api/vessels/").status_code, 401)
        self.assertEqual(client.get("/export.csv").status_code, 401)
        self.assertEqual(client.get("/").status_code, 302)

    def test_port_user_only_sees_own_port_and_cannot_widen_it(self):
        alex = self.login("alex")
        _, data = self.call(alex, "get", "/api/vessels/?port=suez")
        self.assertEqual([v["name"] for v in data["vessels"]], ["ALEX SHIP"])

    def test_port_user_cannot_touch_other_ports(self):
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "get", f"/api/vessels/{self.suez_vessel.id}/")[0], 404)
        self.assertEqual(
            self.call(alex, "put", f"/api/vessels/{self.suez_vessel.id}/", {**NEEDED, "name": "x", "date": "2026-01-01"})[0], 404
        )
        self.assertEqual(self.call(alex, "delete", f"/api/vessels/{self.suez_vessel.id}/")[0], 404)
        self.assertEqual(
            self.call(alex, "post", f"/api/vessels/{self.suez_vessel.id}/services/", {"type": "Fresh Water"})[0], 404
        )
        self.assertEqual(
            self.call(alex, "put", f"/api/services/{self.suez_service.id}/", {"type": "Fresh Water"})[0], 404
        )
        self.assertEqual(self.call(alex, "delete", f"/api/services/{self.suez_service.id}/")[0], 404)
        self.assertTrue(Service.objects.filter(pk=self.suez_service.id).exists())

    def test_port_user_cannot_create_or_move_into_another_port(self):
        alex = self.login("alex")
        body = {**NEEDED, "name": "NEW", "date": "2026-11-13"}
        self.assertEqual(self.call(alex, "post", "/api/vessels/", {**body, "port": "suez"})[0], 403)
        status, vessel = self.call(alex, "post", "/api/vessels/", body)
        self.assertEqual((status, vessel["port"]), (201, "alexandria"))
        self.assertEqual(self.call(alex, "put", f"/api/vessels/{vessel['id']}/", {**body, "port": "suez"})[0], 403)
        self.assertEqual(Vessel.objects.get(pk=vessel["id"]).port, "alexandria")

    def test_users_cannot_do_admin_things(self):
        """Exchange rates, All-ports Master data and accounting belong to the Admins, whatever ports a User has."""
        for name in ("viewer", "alex"):
            user = self.login(name)
            self.assertEqual(self.call(user, "post", "/api/rates/", {"month": "2026-10", "rate": "50"})[0], 403)
            self.assertEqual(self.call(user, "get", "/api/history/")[0], 403)
            self.assertEqual(self.call(user, "post", "/api/accounting/",
                                       {"kind": "service", "id": self.suez_service.id, "closed": True})[0], 403)

    def test_only_admins_change_exchange_rates(self):
        """Rates are shared by every port, so a port user must not be able to change them."""
        rate = ExchangeRate.objects.create(month=date(2026, 11, 1), rate=50)
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "get", "/api/rates/")[0], 200)
        self.assertEqual(self.call(alex, "post", "/api/rates/", {"month": "2026-11", "rate": "1"})[0], 403)
        self.assertEqual(self.call(alex, "delete", f"/api/rates/{rate.id}/")[0], 403)
        rate.refresh_from_db()
        self.assertEqual(rate.rate, 50)
        admin = self.login("admin")
        self.assertEqual(self.call(admin, "post", "/api/rates/", {"month": "2026-11", "rate": "51"})[0], 200)
        self.assertEqual(self.call(admin, "delete", f"/api/rates/{rate.id}/")[0], 200)

    def test_admin_sees_all_ports_and_can_filter(self):
        admin = self.login("admin")
        self.assertEqual(len(self.call(admin, "get", "/api/vessels/")[1]["vessels"]), 2)
        self.assertEqual(len(self.call(admin, "get", "/api/vessels/?port=suez")[1]["vessels"]), 1)

    def test_new_users_have_no_port(self):
        """Least privilege: an account nobody gave a port can't do anything (an admin gives it ports)."""
        user = User.objects.create_user("fresh", password=PASSWORD)
        client = Client(enforce_csrf_checks=True)
        client.login(username="fresh", password=PASSWORD)
        pass_two_step(client, "fresh")
        client.get("/", follow=True)  # sent to the "no port yet" page, which sets the CSRF cookie
        self.assertEqual(self.call(client, "post", "/api/vessels/", {**NEEDED, "name": "X", "date": "2026-11-13"})[0], 403)
        self.assertEqual(self.call(client, "get", "/api/vessels/")[0], 403)
        self.assertEqual((user.profile.home_port, user.profile.ports), ("", []))


class RequestHardeningTests(ApiTestCase):
    def test_csrf_token_is_required_for_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="alex", password=PASSWORD)
        pass_two_step(client, "alex")
        response = client.post("/api/vessels/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_bad_json_is_a_400_not_a_crash(self):
        alex = self.login("alex")
        token = alex.cookies["csrftoken"].value
        for body in ["{not json", "[1,2]", "[" * 5000 + "]" * 5000, "\xff"]:
            response = alex.post("/api/vessels/", data=body, content_type="application/json", HTTP_X_CSRFTOKEN=token)
            self.assertEqual(response.status_code, 400, body[:20])

    def test_wrong_method_is_405(self):
        alex = self.login("alex")
        self.assertEqual(
            alex.put(
                "/api/vessels/", content_type="application/json", HTTP_X_CSRFTOKEN=alex.cookies["csrftoken"].value
            ).status_code,
            405,
        )

    def test_validation_errors(self):
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "post", "/api/vessels/", {**NEEDED, "name": "  ", "date": "2026-11-13"})[0], 400)
        self.assertEqual(self.call(alex, "post", "/api/vessels/", {**NEEDED, "name": "A", "date": "13/11/2026"})[0], 400)
        self.assertEqual(
            self.call(alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/", {"type": "Hacking", "data": {}})[
                0
            ],
            400,
        )

    def test_security_headers(self):
        alex = self.login("alex")
        page = alex.get("/")
        self.assertIn("script-src 'self'", page["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", page["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", page["Content-Security-Policy"])
        self.assertEqual(alex.get("/api/vessels/")["Cache-Control"], "no-store")
        self.assertEqual(page["X-Frame-Options"], "DENY")

    def test_page_has_no_third_party_scripts(self):
        html = self.login("alex").get("/").content.decode()
        self.assertNotIn("cdnjs", html)
        self.assertIn('name="csrf-token"', html)


class ServiceFlowTests(ApiTestCase):
    def test_service_lifecycle_and_totals(self):
        ExchangeRate.objects.create(month=date(2026, 11, 1), rate="50")
        alex = self.login("alex")
        url = f"/api/vessels/{self.alex_vessel.id}/services/"
        payload = {
            "type": "Fresh Water",
            "data": {"revenue": "900", "revenueCurrency": "USD", "cost": "30000", "costCurrency": "EGP"},
        }
        status, vessel = self.call(alex, "post", url, payload)
        self.assertEqual(status, 201)
        self.assertEqual(vessel["total_profit_egp"], 15000)
        service_id = vessel["services"][0]["id"]
        _, vessel = self.call(
            alex, "put", f"/api/services/{service_id}/", {"type": "Fresh Water", "data": {"revenue": "10", "cost": "5"}}
        )
        self.assertEqual(vessel["total_profit_egp"], 5)
        _, vessel = self.call(alex, "delete", f"/api/services/{service_id}/")
        self.assertEqual(vessel["services"], [])

    def test_vessel_summary_fields_round_trip(self):
        alex = self.login("alex")
        _, vessel = self.call(
            alex,
            "post",
            "/api/vessels/",
            {**NEEDED, "name": "S", "date": "2026-11-13", "summary": {"Vendor Name": "ACME", "bad": "x"}},
        )
        self.assertEqual(vessel["summary"], {"Vendor Name": "ACME"})

    def test_exchange_rate_rules(self):
        admin = self.login("admin")
        self.assertEqual(self.call(admin, "post", "/api/rates/", {"month": "2026-11", "rate": "-3"})[0], 400)
        self.assertEqual(self.call(admin, "post", "/api/rates/", {"month": "nope", "rate": "5"})[0], 400)
        self.assertEqual(self.call(admin, "post", "/api/rates/", {"month": "2026-11", "rate": "NaN"})[0], 400)
        status, data = self.call(admin, "post", "/api/rates/", {"month": "2026-11", "rate": "50.5"})
        self.assertEqual((status, data["rates"][0]["label"]), (200, "11.2026"))


class OptionTests(ApiTestCase):
    def test_port_user_options_are_private_to_their_port(self):
        alex, suez = self.login("alex"), self.login("suezuser")
        self.call(alex, "post", "/api/options/", {"kind": "opr", "value": "ALEX ONLY"})

        def values(client):
            return [o["value"] for o in self.call(client, "get", "/api/options/")[1]["options"]]

        self.assertIn("ALEX ONLY", values(alex))
        self.assertNotIn("ALEX ONLY", values(suez))

    def test_port_user_cannot_remove_shared_options(self):
        shared = Option.objects.filter(port="").first()
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "delete", f"/api/options/{shared.id}/")[0], 403)
        self.assertTrue(Option.objects.filter(pk=shared.id).exists())

    def test_admin_manages_shared_options_without_duplicates(self):
        admin = self.login("admin")
        for _ in range(2):
            self.call(admin, "post", "/api/options/", {"kind": "poc", "value": "NEWPOC"})
        self.assertEqual(Option.objects.filter(value="NEWPOC").count(), 1)
        self.assertEqual(self.call(admin, "post", "/api/options/", {"kind": "bad", "value": "x"})[0], 400)


class CsvTests(ApiTestCase):
    def test_formula_injection_is_neutralised(self):
        Vessel.objects.create(name='=HYPERLINK("http://evil")', opr="+cmd", date=date(2026, 11, 13), port="alexandria")
        admin = self.login("admin")
        text = admin.get("/export.csv").content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'+cmd", text)
        self.assertEqual(admin.get("/export.csv")["Cache-Control"], "no-store")

    def test_port_user_export_is_scoped(self):
        text = self.login("alex").get("/export.csv").content.decode("utf-8-sig")
        self.assertIn("ALEX SHIP", text)
        self.assertNotIn("SUEZ SHIP", text)


@FAST_HASHER
class LoginThrottleTests(TestCase):
    def setUp(self):
        make_user("alex", "alexandria")

    def attempt(self, username="alex", password="wrong"):
        return self.client.post("/login/", {"username": username, "password": password})

    def test_pair_is_locked_after_repeated_failures_even_with_the_right_password(self):
        for _ in range(throttle.MAX_PAIR_FAILURES):
            self.assertEqual(self.attempt().status_code, 200)
        locked = self.attempt(password=PASSWORD)
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Too many failed attempts", locked.content.decode())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_resets_the_counter(self):
        for _ in range(3):
            self.attempt()
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)
        self.client.logout()
        for _ in range(3):
            self.attempt()
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)

    def test_one_ip_cannot_spray_many_usernames(self):
        for i in range(throttle.MAX_IP_FAILURES):
            self.attempt(username=f"user{i}")
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 429)

    def test_lock_expires(self):
        for _ in range(throttle.MAX_PAIR_FAILURES):
            self.attempt()
        LoginAttempt.objects.update(window_start=LoginAttempt.objects.first().window_start - throttle.WINDOW * 2)
        self.assertEqual(self.attempt(password=PASSWORD).status_code, 302)


@FAST_HASHER
@override_settings(CLIENT_IP_META_KEY="HTTP_X_FORWARDED_FOR")
class ProxyIpTests(TestCase):
    """Behind a proxy the throttle must tell clients apart by the header, not lock everyone out together."""

    def setUp(self):
        make_user("alex", "alexandria")

    def attempt(self, forwarded, password="wrong"):
        return self.client.post("/login/", {"username": "alex", "password": password}, HTTP_X_FORWARDED_FOR=forwarded)

    def test_different_clients_are_throttled_separately(self):
        for _ in range(throttle.MAX_PAIR_FAILURES):
            self.attempt("203.0.113.9")
        self.assertEqual(self.attempt("203.0.113.9", PASSWORD).status_code, 429)
        self.assertEqual(self.attempt("198.51.100.4", PASSWORD).status_code, 302)

    def test_only_the_address_our_proxy_appended_is_trusted(self):
        # A client can prepend fake addresses; the real one is the last entry.
        for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"):
            self.attempt(f"{fake}, 203.0.113.9")
        self.assertEqual(self.attempt("6.6.6.6, 203.0.113.9", PASSWORD).status_code, 429)

    def test_malformed_header_falls_back_to_the_socket_address(self):
        for _ in range(throttle.MAX_PAIR_FAILURES):
            self.attempt("not-an-ip")
        self.assertEqual(self.attempt("also-bad", PASSWORD).status_code, 429)


class SeedCommandTests(TestCase):
    def test_refuses_to_run_in_production_mode(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())

    @FAST_HASHER
    @override_settings(DEBUG=True)
    def test_creates_random_passwords_by_default(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        self.assertNotIn("demo12345", out.getvalue())
        self.assertTrue(Vessel.objects.exists())

    @FAST_HASHER
    @override_settings(DEBUG=True)
    def test_seeds_reason_lists_and_closures(self):
        from .models import PortClosure

        call_command("seed_demo", stdout=StringIO())
        self.assertIn("PORT CLOSED", Option.objects.filter(kind="delay", port="").values_list("value", flat=True))
        self.assertIn("WEATHER", Option.objects.filter(kind="closure", port="").values_list("value", flat=True))
        self.assertEqual(sorted(PortClosure.objects.values_list("port", flat=True)), ["alexandria", "portsaid"])
        self.assertIsNone(PortClosure.objects.get(port="portsaid").end_at)


class PortCallTests(ApiTestCase):
    def create(self, client, **extra):
        payload = {**NEEDED, "name": "TIMED", "date": "2026-11-13", **extra}
        return self.call(client, "post", "/api/vessels/", payload)

    def test_times_and_agent_round_trip_in_cairo_time(self):
        allow("agent", "NILE AGENCY")
        allow("delay", "WEATHER")
        alex = self.login("alex")
        status, vessel = self.create(
            alex,
            arrival_agent="NILE AGENCY",
            delay_reason="WEATHER",  # berthed 2.5 hours after arrival
            arrival_at="2026-11-13T06:00",
            berthing_at="2026-11-13T08:30",
            ops_start_at="2026-11-13T09:00",
            ops_end_at="2026-11-13T15:00",
            sailing_at="2026-11-13T18:00",
        )
        self.assertEqual(status, 201)
        self.assertEqual(vessel["arrival_agent"], "NILE AGENCY")
        self.assertEqual(vessel["berthing_at"], "2026-11-13T08:30")
        self.assertEqual(vessel["durations"], {"ops_hours": 6.0, "berth_hours": 9.5, "port_hours": 12.0})
        self.assertEqual(vessel["status"], "sailed")
        stored = Vessel.objects.get(pk=vessel["id"])
        # Typed in Cairo time (UTC+2 in November) and stored in UTC.
        self.assertEqual(stored.berthing_at, datetime(2026, 11, 13, 6, 30, tzinfo=UTC))

    def test_status_follows_the_latest_milestone(self):
        alex = self.login("alex")
        self.assertEqual(self.create(alex)[1]["status"], "scheduled")
        self.assertEqual(self.create(alex, arrival_at="2026-11-13T06:00")[1]["status"], "arrived")
        self.assertEqual(
            self.create(alex, arrival_at="2026-11-13T06:00", berthing_at="2026-11-13T07:00")[1]["status"], "berthed"
        )
        started = self.create(alex, ops_start_at="2026-11-13T07:00")[1]
        self.assertEqual((started["status"], started["durations"]["ops_hours"]), ("operating", None))

    def test_milestones_must_be_in_a_sensible_order(self):
        alex = self.login("alex")
        late = self.create(alex, arrival_at="2026-11-13T10:00", sailing_at="2026-11-13T09:00")
        self.assertEqual(late[0], 400)
        self.assertIn("Sailed cannot be before arrived", late[1]["error"])
        self.assertEqual(self.create(alex, ops_start_at="2026-11-13T10:00", ops_end_at="2026-11-13T09:00")[0], 400)

    def test_operations_may_start_before_berthing(self):
        alex = self.login("alex")  # e.g. crew change at anchorage
        status, _ = self.create(alex, berthing_at="2026-11-13T12:00", ops_start_at="2026-11-13T08:00")
        self.assertEqual(status, 201)

    def test_bad_times_are_rejected(self):
        alex = self.login("alex")
        for bad in ["not a time", "2026-13-45T10:00", "1900-01-01T10:00"]:
            self.assertEqual(self.create(alex, arrival_at=bad)[0], 400, bad)

    def test_times_can_be_edited_and_cleared(self):
        alex = self.login("alex")
        _, vessel = self.create(alex, arrival_at="2026-11-13T06:00")
        _, updated = self.call(
            alex, "put", f"/api/vessels/{vessel['id']}/", {**NEEDED, "name": "TIMED", "date": "2026-11-13", "arrival_at": ""}
        )
        self.assertIsNone(updated["arrival_at"])


class AgentMasterDataTests(ApiTestCase):
    def test_agents_are_a_master_data_kind_with_usage_counts(self):
        admin = self.login("admin")
        self.call(admin, "post", "/api/options/", {"kind": "agent", "value": "NILE AGENCY"})
        Vessel.objects.create(name="A", date=date(2026, 11, 13), port="alexandria", arrival_agent="NILE AGENCY")
        Vessel.objects.create(name="B", date=date(2026, 11, 13), port="suez", arrival_agent="NILE AGENCY")
        _, data = self.call(admin, "get", "/api/options/")
        agent = next(o for o in data["options"] if o["kind"] == "agent")
        self.assertEqual((agent["value"], agent["used"]), ("NILE AGENCY", 2))

    def test_usage_counts_only_cover_vessels_the_user_can_see(self):
        admin, alex = self.login("admin"), self.login("alex")
        self.call(admin, "post", "/api/options/", {"kind": "agent", "value": "NILE AGENCY"})
        Vessel.objects.create(name="A", date=date(2026, 11, 13), port="alexandria", arrival_agent="NILE AGENCY")
        Vessel.objects.create(name="B", date=date(2026, 11, 13), port="suez", arrival_agent="NILE AGENCY")
        _, data = self.call(alex, "get", "/api/options/")
        self.assertEqual(next(o for o in data["options"] if o["kind"] == "agent")["used"], 1)


class PasswordChangeTests(ApiTestCase):
    URL = "/password/"

    def post(self, client, old, new):
        data = {"old_password": old, "new_password1": new, "new_password2": new}
        return client.post(self.URL, data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)

    def test_requires_login(self):
        self.assertEqual(Client().get(self.URL).status_code, 302)

    def test_rejects_wrong_old_password_and_weak_new_ones(self):
        client = self.login("alex")
        self.assertEqual(self.post(client, "wrong", "a-very-long-new-passphrase").status_code, 200)
        for weak in ["short1", "123456789012", "password1234"]:
            self.assertEqual(self.post(client, PASSWORD, weak).status_code, 200, weak)
        self.assertTrue(User.objects.get(username="alex").check_password(PASSWORD))

    def test_changes_the_password_and_keeps_the_user_signed_in(self):
        client = self.login("alex")
        new = "a-very-long-new-passphrase"
        self.assertEqual(self.post(client, PASSWORD, new).status_code, 302)
        self.assertTrue(User.objects.get(username="alex").check_password(new))
        self.assertEqual(client.get("/api/vessels/").status_code, 200)


@FAST_HASHER
class AdminLoginThrottleTests(TestCase):
    def test_admin_login_is_throttled_too(self):
        make_user("boss", "admin")
        url = f"/{settings.ADMIN_URL}login/"
        for _ in range(throttle.MAX_PAIR_FAILURES):
            self.client.post(url, {"username": "boss", "password": "wrong", "next": "/admin/"})
        locked = self.client.post(url, {"username": "boss", "password": PASSWORD, "next": "/admin/"})
        self.assertEqual(locked.status_code, 429)


@FAST_HASHER
class SecurityLogTests(TestCase):
    def test_logins_are_logged_without_passwords(self):
        make_user("alex", "alexandria")
        with self.assertLogs("sheet.security", level="INFO") as logs:
            self.client.post("/login/", {"username": "alex", "password": "my-secret-guess"})
            self.client.post("/login/", {"username": "alex", "password": PASSWORD})
        text = "\n".join(logs.output)
        self.assertIn("login failed", text)
        self.assertIn("login ok user=alex", text)
        self.assertNotIn("my-secret-guess", text)
        self.assertNotIn(PASSWORD, text)

    def test_log_injection_in_username_is_neutralised(self):
        with self.assertLogs("sheet.security", level="WARNING") as logs:
            self.client.post("/login/", {"username": "bob\nlogin ok user=admin", "password": "x"})
        self.assertEqual(len(logs.output[0].splitlines()), 1)

    def test_log_injection_in_audited_values_is_neutralised(self):
        make_user("alex", "alexandria")
        client = Client(enforce_csrf_checks=True)
        client.login(username="alex", password=PASSWORD)
        pass_two_step(client, "alex")
        client.get("/")
        with self.assertLogs("sheet.audit", level="INFO") as logs:
            client.post(
                "/api/options/",
                data=json.dumps({"kind": "opr", "value": "X\nINFO user=admin action=vessel.delete"}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            )
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(len(logs.output[0].splitlines()), 1)
        self.assertIn("action=option.create", logs.output[0])

    def test_changes_are_audited(self):
        make_user("alex", "alexandria")
        allow("opr", NEEDED["opr"])
        allow("poc", NEEDED["poc"])
        ship = Ship.objects.create(name="AUDITED", imo="")
        client = Client(enforce_csrf_checks=True)
        client.login(username="alex", password=PASSWORD)
        pass_two_step(client, "alex")
        client.get("/")
        with self.assertLogs("sheet.audit", level="INFO") as logs:
            token = client.cookies["csrftoken"].value
            client.post(
                "/api/vessels/",
                data=json.dumps({**NEEDED, "name": "AUDITED", "date": "2026-11-13", "ship_id": ship.id}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
            )
        self.assertIn("action=vessel.create", logs.output[0])


class SessionAndHeaderTests(ApiTestCase):
    def test_idle_timeout_is_configured(self):
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)

    def test_password_minimum_is_twelve_characters(self):
        lengths = [v["OPTIONS"]["min_length"] for v in settings.AUTH_PASSWORD_VALIDATORS if "OPTIONS" in v]
        self.assertEqual(lengths, [12])

    def test_extra_headers(self):
        page = self.login("alex").get("/")
        csp = page["Content-Security-Policy"]
        # No inline style attributes and no HTML strings: the browser refuses both.
        self.assertIn("style-src-attr 'none'", csp)
        self.assertNotIn("'unsafe-inline'", csp)
        self.assertIn("require-trusted-types-for 'script'", csp)
        self.assertIn("trusted-types 'none'", csp)
        self.assertNotIn("worker-src", csp)
        self.assertIn("style-src-elem 'self';", page["Content-Security-Policy"])
        self.assertEqual(page["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(page["Cache-Control"], "no-store")

    def test_admin_pages_have_a_csp_too(self):
        # The Django admin's own scripts build HTML from text, so no Trusted Types there; everything else stays strict.
        for page in (self.client.get(f"/{settings.ADMIN_URL}login/"), self.login("admin").get(f"/{settings.ADMIN_URL}")):
            csp = page["Content-Security-Policy"]
            for rule in ("default-src 'self'", "script-src 'self';", "style-src 'self';", "object-src 'none'",
                         "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"):
                self.assertIn(rule, csp)
            self.assertNotIn("unsafe-eval", csp)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
            self.assertNotIn("trusted-types", csp)

    def test_login_page_is_not_cached_either(self):
        self.assertIn("no-store", Client().get("/login/")["Cache-Control"])

    def test_csv_has_agent_and_milestones(self):
        Vessel.objects.create(
            name="CSV SHIP", date=date(2026, 11, 13), port="alexandria", arrival_agent="NILE", arrival_at="2026-11-13T04:30:00Z"
        )
        header, *rows = self.login("admin").get("/export.csv").content.decode("utf-8-sig").splitlines()
        self.assertIn("Arrival agent", header)
        self.assertIn("Sailed", header)
        row = next(r for r in rows if "CSV SHIP" in r)
        self.assertIn("NILE", row)
        self.assertIn("13.11.2026 06:30", row)  # stored as UTC, shown in Cairo time


class DatabaseSettingsTests(SimpleTestCase):
    BASE = Path("/app")

    def build(self, env, debug=False):
        return build_database_settings(env, debug=debug, base_dir=self.BASE)

    def test_sqlite_is_fine_for_development(self):
        self.assertIn("sqlite3", self.build({}, debug=True)["ENGINE"])

    def test_production_refuses_sqlite(self):
        with self.assertRaises(ImproperlyConfigured):
            self.build({})
        self.assertIn("sqlite3", self.build({"DJANGO_ALLOW_SQLITE": "1"})["ENGINE"])

    def test_postgres_connection_is_encrypted_by_default(self):
        config = self.build({"DJANGO_DB_NAME": "sheet", "DJANGO_DB_USER": "u", "DJANGO_DB_PASSWORD": "p"})
        self.assertIn("postgresql", config["ENGINE"])
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")
        self.assertNotIn("sslrootcert", config["OPTIONS"])

    def test_postgres_can_verify_the_server_certificate(self):
        config = self.build(
            {"DJANGO_DB_NAME": "sheet", "DJANGO_DB_SSLMODE": "verify-full", "DJANGO_DB_SSLROOTCERT": "/etc/ca.pem"}
        )
        self.assertEqual(config["OPTIONS"], {"sslmode": "verify-full", "sslrootcert": "/etc/ca.pem"})


class DebugDefaultTests(SimpleTestCase):
    """Production must fail closed: forgetting DJANGO_DEBUG may not switch on debug mode."""

    def load_settings(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean.update(env)
        code = "import config.settings as s; print('DEBUG=' + str(s.DEBUG))"
        return subprocess.run(
            [sys.executable, "-c", code], env=clean, cwd=settings.BASE_DIR, capture_output=True, text=True
        )

    def test_debug_is_off_when_not_set(self):
        result = self.load_settings()
        self.assertNotEqual(result.returncode, 0)  # no secret key -> refuses to start
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_debug_can_be_switched_on_explicitly(self):
        result = self.load_settings(DJANGO_DEBUG="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DEBUG=True", result.stdout)


class BulkAddRemovedTests(ApiTestCase):
    """Bulk add was removed (2026-11-18): no routes, no page."""

    def test_bulk_endpoints_are_gone(self):
        client = self.login("admin")
        for url in ("/api/vessels/bulk/", "/api/vessels/bulk/check/"):
            status, _ = self.call(client, "post", url, {"rows": []})
            self.assertEqual(status, 404, url)

    def test_page_has_no_bulk_add(self):
        html = self.login("admin").get("/").content.decode()
        self.assertNotIn("page-bulk", html)
        self.assertNotIn("nav-bulk", html)
        self.assertNotIn("qa-bulk", html)

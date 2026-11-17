"""Hardening from the OWASP 2025 walk (A01, A02, A04, A05, A07): cookies, proxy check, login answers."""

import os
import re
import subprocess
import sys

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core.checks import run_checks
from django.test import Client, SimpleTestCase, TestCase, override_settings

from .tests import FAST_HASHER, PASSWORD, make_user


def load_settings(code, **env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
    clean.update(env)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings as s; " + code],
        env=clean,
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
    )


PRODUCTION = {"DJANGO_SECRET_KEY": "x" * 60, "DJANGO_ALLOW_SQLITE": "1", "DJANGO_ALLOWED_HOSTS": "sheet.example.com"}


class HostCookieTests(SimpleTestCase):
    def test_production_cookies_carry_the_host_prefix(self):
        result = load_settings("print(s.SESSION_COOKIE_NAME, s.CSRF_COOKIE_NAME)", **PRODUCTION)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["__Host-sessionid", "__Host-csrftoken"])

    def test_development_keeps_plain_cookie_names(self):
        result = load_settings("print(s.SESSION_COOKIE_NAME, s.CSRF_COOKIE_NAME)", DJANGO_DEBUG="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["sessionid", "csrftoken"])


@FAST_HASHER
@override_settings(SESSION_COOKIE_NAME="__Host-sessionid", CSRF_COOKIE_NAME="__Host-csrftoken")
class RenamedCookieTests(TestCase):
    def test_an_old_sessionid_cookie_just_asks_for_sign_in(self):
        user = make_user("alex", "alexandria")
        old = SessionStore()
        old["_auth_user_id"] = str(user.pk)
        old["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        old["_auth_user_hash"] = user.get_session_auth_hash()
        old.save()
        client = Client()
        client.cookies["sessionid"] = old.session_key
        page = client.get("/")
        self.assertEqual(page.status_code, 302)
        self.assertTrue(page["Location"].startswith("/login/"))
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_sign_in_works_with_the_new_names(self):
        make_user("alex", "alexandria")
        client = Client(enforce_csrf_checks=True)
        client.get("/login/")
        token = client.cookies["__Host-csrftoken"].value
        answer = client.post("/login/", {"username": "alex", "password": PASSWORD, "csrfmiddlewaretoken": token})
        self.assertEqual(answer.status_code, 302)
        self.assertIn("__Host-sessionid", client.cookies)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)


class ProxyDeployCheckTests(SimpleTestCase):
    def ids(self):
        return [m.id for m in run_checks(include_deployment_checks=True) if m.id.startswith("sheet.")]

    @override_settings(BEHIND_PROXY=True, CLIENT_IP_META_KEY="")
    def test_proxy_without_client_ip_header_fails_the_deploy_check(self):
        self.assertIn("sheet.E001", self.ids())

    @override_settings(BEHIND_PROXY=True, CLIENT_IP_META_KEY="HTTP_X_FORWARDED_FOR")
    def test_proxy_with_client_ip_header_passes(self):
        self.assertNotIn("sheet.E001", self.ids())

    @override_settings(BEHIND_PROXY=False, CLIENT_IP_META_KEY="")
    def test_no_proxy_passes(self):
        self.assertNotIn("sheet.E001", self.ids())

    def test_settings_read_the_proxy_switch(self):
        result = load_settings("print(s.BEHIND_PROXY)", DJANGO_DEBUG="1", DJANGO_BEHIND_PROXY="1")
        self.assertEqual(result.stdout.strip(), "True", result.stderr)


@FAST_HASHER
class LoginEnumerationTests(TestCase):
    def answer(self, username, password):
        client = Client()
        response = client.post("/login/", {"username": username, "password": password})
        text = re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', "", response.content.decode())
        return response.status_code, text.replace(f'value="{username}"', 'value=""')  # the form echoes the name

    def test_unknown_user_and_wrong_password_get_the_same_answer(self):
        make_user("alex", "alexandria")
        self.assertEqual(self.answer("nobody-here", "wrong-password"), self.answer("alex", "wrong-password"))


@FAST_HASHER
class SessionRotationTests(TestCase):
    def test_signing_in_gives_a_new_session_key(self):
        make_user("alex", "alexandria")
        client = Client()
        client.get("/login/")
        session = client.session
        session["before"] = True
        session.save()
        before = session.session_key
        client.post("/login/", {"username": "alex", "password": PASSWORD})
        self.assertNotEqual(client.session.session_key, before)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)

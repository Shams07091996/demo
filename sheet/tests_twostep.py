"""Two-step login: password + a six-digit Authenticator code (TOTP)."""

import time
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core.checks import run_checks
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import throttle, twostep
from .models import ChangeRecord, LoginAttempt, Profile, RememberedComputer
from .tests import FAST_HASHER, PASSWORD, make_user, pass_two_step


def history(model_name, **filters):
    return list(ChangeRecord.objects.filter(object_type=model_name, **filters).order_by("id"))


@FAST_HASHER
class TwoStepModelTests(TestCase):
    def test_exempt_refused_for_admin_superuser_staff(self):
        admin = make_user("boss", "admin")
        with self.assertRaisesMessage(ValidationError, "Remove the two-step exception first."):
            admin.profile.two_step_exempt = True
            admin.profile.save()
        for flag in ("is_superuser", "is_staff"):
            user = make_user(f"u_{flag}", "readonly")
            setattr(user, flag, True)
            user.save()
            user.profile.two_step_exempt = True
            with self.assertRaisesMessage(ValidationError, "Remove the two-step exception first."):
                user.profile.save()
        viewer = make_user("plain", "readonly")
        viewer.profile.two_step_exempt = True
        viewer.profile.save()  # allowed
        self.assertTrue(Profile.objects.get(user=viewer).two_step_exempt)

    def test_new_profile_gets_setup_window(self):
        before = timezone.now()
        user = make_user("newbie", "readonly")
        window = user.profile.setup_until - before
        self.assertGreaterEqual(window, timedelta(hours=72) - timedelta(seconds=5))
        self.assertLessEqual(window, timedelta(hours=72) + timedelta(seconds=5))
        self.assertFalse(user.profile.two_step_exempt)
        self.assertFalse(user.profile.must_change_password)

    def test_device_history_has_no_key(self):
        user = make_user("dev", "readonly")
        device = TOTPDevice.objects.create(user=user, name="Authenticator", confirmed=False)
        device.confirmed = True
        device.save()
        records = history("totpdevice")
        self.assertEqual([r.action for r in records], ["create", "update"])
        for record in records:
            self.assertNotIn("key", record.changes)
            self.assertNotIn(device.key, str(record.changes))
        self.assertEqual(records[1].changes, {"confirmed": [False, True]})

    def test_wrong_code_writes_no_history(self):
        user = make_user("dev2", "readonly")
        device = TOTPDevice.objects.create(user=user, name="Authenticator", confirmed=True)
        before = ChangeRecord.objects.count()
        self.assertFalse(device.verify_token("000000") and device.verify_token("111111"))
        self.assertEqual(ChangeRecord.objects.count(), before)

    def test_remembered_history_has_no_hash(self):
        user = make_user("rem", "readonly")
        row = RememberedComputer.objects.create(
            user=user, token_hash="a" * 64, expires_at=timezone.now() + timedelta(days=30), ip="1.2.3.4", agent="X"
        )
        records = history("rememberedcomputer")
        self.assertEqual(len(records), 1)
        self.assertNotIn("token_hash", records[0].changes)
        self.assertNotIn("a" * 64, str(records[0].changes))
        row.last_used_at = timezone.now()
        row.save()
        self.assertEqual(len(history("rememberedcomputer")), 1)


def current_code(device):
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return f"{totp.token():06d}"


def wrong_code(device):
    return "000000" if current_code(device) != "000000" else "111111"


@FAST_HASHER
class SignInTests(TestCase):
    """The gate: nothing past the password alone."""

    def setUp(self):
        self.user = make_user("alex", "alexandria")
        self.device = TOTPDevice.objects.create(user=self.user, name="Authenticator", confirmed=True)

    def password_only(self, username="alex", client=None):
        client = client or Client()
        self.assertTrue(client.login(username=username, password=PASSWORD))
        return client

    def send_code(self, client, code, remember=False):
        data = {"code": code}
        if remember:
            data["remember"] = "on"
        return client.post("/login/code/", data)

    def test_api_is_401_until_code(self):
        client = self.password_only()
        response = client.get("/api/vessels/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Please log in again."})
        for url in ("/api/dashboard/", "/api/dashboard/jobs/", "/api/history/", "/api/calculations/"):
            self.assertEqual(client.get(url).status_code, 401, url)
        self.assertEqual(client.post("/api/vessels/", "{}", content_type="application/json").status_code, 401)

    def test_index_redirects_to_code(self):
        response = self.password_only().get("/")
        self.assertRedirects(response, "/login/code/", fetch_redirect_response=False)

    def test_export_401_until_code(self):
        self.assertEqual(self.password_only().get("/export.csv").status_code, 401)

    def test_admin_pages_redirect_until_verified(self):
        boss = make_user("boss", "admin")
        boss.is_staff = boss.is_superuser = True
        boss.save()
        TOTPDevice.objects.create(user=boss, name="Authenticator", confirmed=True)
        client = Client()
        response = client.post(f"/{settings.ADMIN_URL}login/", {"username": "boss", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        for url in ("", "auth/user/", "sheet/changerecord/", "otp_totp/totpdevice/"):
            page = client.get(f"/{settings.ADMIN_URL}{url}")
            self.assertRedirects(page, "/login/code/", fetch_redirect_response=False, msg_prefix=url)

    def test_logout_always_works(self):
        client = self.password_only()
        self.assertEqual(client.post("/logout/").status_code, 302)
        self.assertNotIn("_auth_user_id", client.session)

    def test_right_code_passes(self):
        client = self.password_only()
        before = client.session.session_key
        response = self.send_code(client, current_code(self.device))
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertNotEqual(client.session.session_key, before)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)

    def test_code_with_spaces_is_fine(self):
        client = self.password_only()
        code = current_code(self.device)
        self.send_code(client, f"{code[:3]} {code[3:]}")
        self.assertEqual(client.get("/api/vessels/").status_code, 200)

    def test_wrong_code_refused_and_counted(self):
        client = self.password_only()
        with self.assertLogs("sheet.security", level="WARNING") as logs:
            response = self.send_code(client, "12345x")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wrong code.")
        self.assertIn("two-step code wrong user=alex", "\n".join(logs.output))
        self.assertEqual(LoginAttempt.objects.filter(key__startswith="pair|").get().failures, 1)
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_code_cannot_be_used_twice(self):
        code = current_code(self.device)
        first = self.password_only()
        self.send_code(first, code)
        self.assertEqual(first.get("/api/vessels/").status_code, 200)
        second = self.password_only()
        self.send_code(second, code)
        self.assertEqual(second.get("/api/vessels/").status_code, 401)

    def test_five_wrong_codes_lock(self):
        client = self.password_only()
        for _ in range(throttle.MAX_PAIR_FAILURES):
            TOTPDevice.objects.filter(pk=self.device.pk).update(throttling_failure_count=0)  # skip django-otp's wait
            self.send_code(client, wrong_code(self.device))
        TOTPDevice.objects.filter(pk=self.device.pk).update(throttling_failure_count=0)
        self.assertEqual(self.send_code(client, current_code(self.device)).status_code, 429)
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_django_otp_wait_after_a_wrong_code(self):
        client = self.password_only()
        self.send_code(client, wrong_code(self.device))
        self.send_code(client, current_code(self.device))  # within the 1-second wait: refused
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_password_sign_in_clears_pass(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device))
        self.assertEqual(client.get("/api/vessels/").status_code, 200)
        self.password_only(client=client)  # a password sign-in on top of a passed session
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_exempt_user_goes_straight_in(self):
        viewer = make_user("viewer", "readonly")
        viewer.profile.two_step_exempt = True
        viewer.profile.save()
        client = self.password_only("viewer")
        with self.assertLogs("sheet.security", level="INFO") as logs:
            self.assertEqual(client.get("/api/vessels/").status_code, 200)
        self.assertIn("two-step exempt sign-in user=viewer", "\n".join(logs.output))
        Profile.objects.filter(user=viewer).update(two_step_exempt=False)  # exception removed: the session ends
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_exempt_flag_ignored_for_superuser(self):
        Profile.objects.filter(user=self.user).update(two_step_exempt=True)  # past the model's own check
        User.objects.filter(pk=self.user.pk).update(is_superuser=True)
        self.assertEqual(self.password_only().get("/api/vessels/").status_code, 401)

    def test_remember_skips_code_for_30_days(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device), remember=True)
        cookie = client.cookies[settings.REMEMBER_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(int(cookie["max-age"]), 30 * 24 * 3600)
        row = RememberedComputer.objects.get()
        self.assertNotEqual(row.token_hash, cookie.value)
        client.post("/logout/")
        self.assertEqual(client.cookies[settings.REMEMBER_COOKIE_NAME].value, cookie.value)  # logout keeps it
        self.password_only(client=client)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)
        self.assertContains(client.get("/"), "Forget this computer")

    def test_remember_expires(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device), remember=True)
        client.post("/logout/")
        self.password_only(client=client)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)
        RememberedComputer.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(client.get("/api/vessels/").status_code, 401)  # the session that used it ends too
        self.password_only(client=client)
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_remembered_cookie_of_other_user_is_ignored(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device), remember=True)
        token = client.cookies[settings.REMEMBER_COOKIE_NAME].value
        other = make_user("suez", "suez")
        TOTPDevice.objects.create(user=other, name="Authenticator", confirmed=True)
        thief = Client()
        thief.cookies[settings.REMEMBER_COOKIE_NAME] = token
        self.password_only("suez", client=thief)
        self.assertEqual(thief.get("/api/vessels/").status_code, 401)

    def test_unticked_box_remembers_nothing(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device))
        self.assertFalse(RememberedComputer.objects.exists())
        self.assertNotContains(client.get("/"), "Forget this computer")

    def test_forget_removes_row_and_cookie(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device), remember=True)
        self.assertEqual(client.get("/login/forget/").status_code, 405)
        response = client.post("/login/forget/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertFalse(RememberedComputer.objects.exists())
        self.assertEqual(client.cookies[settings.REMEMBER_COOKIE_NAME].value, "")

    def test_reset_ends_live_sessions(self):
        client = self.password_only()
        self.send_code(client, current_code(self.device), remember=True)
        twostep.reset(self.user)
        self.assertFalse(RememberedComputer.objects.exists())
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertRedirects(client.get("/"), "/login/setup/", fetch_redirect_response=False)

    def test_code_page_is_csp_safe(self):
        page = self.password_only().get("/login/code/")
        self.assertIn("script-src 'self'", page["Content-Security-Policy"])
        text = page.content.decode()
        self.assertNotIn("<script", text)
        self.assertNotIn("style=", text)
        self.assertIn('autocomplete="one-time-code"', text)


@FAST_HASHER
class SetupTests(TestCase):
    def setUp(self):
        self.user = make_user("viewer", "readonly")
        self.client.login(username="viewer", password=PASSWORD)

    def test_setup_shows_qr_and_confirms(self):
        self.assertRedirects(self.client.get("/"), "/login/setup/", fetch_redirect_response=False)
        page = self.client.get("/login/setup/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'src="data:image/svg+xml')
        device = TOTPDevice.objects.get(user=self.user)
        self.assertFalse(device.confirmed)
        self.assertContains(page, twostep.secret_text(device))
        self.assertNotIn("<script", page.content.decode())
        with self.assertLogs("sheet.security", level="INFO") as logs:
            response = self.client.post("/login/setup/", {"code": current_code(device)})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertIn("two-step setup done user=viewer", "\n".join(logs.output))
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(self.client.get("/api/vessels/").status_code, 200)

    def test_wrong_setup_code_keeps_it_unconfirmed(self):
        self.client.get("/login/setup/")
        device = TOTPDevice.objects.get(user=self.user)
        page = self.client.post("/login/setup/", {"code": wrong_code(device)})
        self.assertContains(page, "Wrong code.")
        device.refresh_from_db()
        self.assertFalse(device.confirmed)

    def test_setup_same_secret_on_reload(self):
        first = self.client.get("/login/setup/").content
        second = self.client.get("/login/setup/").content
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 1)
        self.assertEqual(first.split(b'name="csrfmiddlewaretoken"')[0], second.split(b'name="csrfmiddlewaretoken"')[0])
        device = TOTPDevice.objects.get(user=self.user)
        self.assertIn(twostep.secret_text(device).encode(), second)

    def test_setup_refused_after_window(self):
        Profile.objects.filter(user=self.user).update(setup_until=timezone.now() - timedelta(seconds=1))
        self.assertRedirects(self.client.get("/"), "/login/blocked/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/login/setup/"), "/login/blocked/", fetch_redirect_response=False)
        page = self.client.get("/login/blocked/")
        self.assertContains(page, "Ask an administrator to reset your two-step login.")
        self.assertFalse(TOTPDevice.objects.exists())
        self.assertEqual(self.client.get("/api/vessels/").status_code, 401)

    def test_setup_refused_while_device_confirmed(self):
        TOTPDevice.objects.create(user=self.user, name="Authenticator", confirmed=True)
        self.assertRedirects(self.client.get("/login/setup/"), "/login/code/", fetch_redirect_response=False)

    def test_secret_not_in_logs_or_history(self):
        with self.assertLogs("sheet.security", level="INFO") as logs:
            self.client.get("/login/setup/")
            device = TOTPDevice.objects.get(user=self.user)
            self.client.post("/login/setup/", {"code": current_code(device)})
            self.client.get("/api/vessels/")
        secret = twostep.secret_text(device).replace(" ", "")
        for text in ("\n".join(logs.output), str(list(ChangeRecord.objects.values_list("changes", flat=True)))):
            self.assertNotIn(device.key, text)
            self.assertNotIn(secret, text)


NEW_PASSWORD = "a-very-long-new-passphrase"


def make_superuser(username="boss"):
    boss = make_user(username, "admin")
    boss.is_staff = boss.is_superuser = True
    boss.save()
    return boss


def admin_client(username="boss"):
    client = Client()
    client.force_login(User.objects.get(username=username))
    return pass_two_step(client, username)


@FAST_HASHER
class ForcedPasswordTests(TestCase):
    def setUp(self):
        self.alex = make_user("alex", "alexandria")
        make_superuser()
        self.admin = admin_client()

    def admin_sets_password(self, user):
        url = f"/{settings.ADMIN_URL}auth/user/{user.pk}/password/"
        response = self.admin.post(url, {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD, "usable_password": "true"})
        self.assertEqual(response.status_code, 302, response.content[:2000])

    def change_own(self, client, old, new=NEW_PASSWORD + "-2"):
        return client.post("/password/", {"old_password": old, "new_password1": new, "new_password2": new})

    def test_password_set_by_other_forces_change(self):
        self.admin_sets_password(self.alex)
        self.assertTrue(Profile.objects.get(user=self.alex).must_change_password)

    def test_new_account_from_admin_forces_change(self):
        url = f"/{settings.ADMIN_URL}auth/user/add/"
        data = {
            "username": "newbie",
            "password1": NEW_PASSWORD,
            "password2": NEW_PASSWORD,
            "usable_password": "true",
            "profile-TOTAL_FORMS": "1",
            "profile-INITIAL_FORMS": "0",
            "profile-MIN_NUM_FORMS": "0",
            "profile-MAX_NUM_FORMS": "1",
            "profile-0-role": "readonly",
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin.post(url, data)
        self.assertEqual(response.status_code, 302, response.content[:3000])
        newbie = User.objects.get(username="newbie")
        self.assertTrue(Profile.objects.get(user=newbie).must_change_password)

    def test_forced_change_blocks_everything_else(self):
        self.admin_sets_password(self.alex)
        client = Client()
        client.login(username="alex", password=NEW_PASSWORD)  # no Authenticator yet
        self.assertRedirects(client.get("/"), "/password/", fetch_redirect_response=False)
        self.assertRedirects(client.get("/login/setup/"), "/password/", fetch_redirect_response=False)
        self.assertEqual(client.get("/api/vessels/").status_code, 401)
        page = client.get("/password/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, ">Cancel<")
        self.assertEqual(self.change_own(client, NEW_PASSWORD).status_code, 302)
        self.assertFalse(Profile.objects.get(user=self.alex).must_change_password)
        self.assertRedirects(client.get("/"), "/login/setup/", fetch_redirect_response=False)  # then the setup

    def test_code_before_forced_change(self):
        device = TOTPDevice.objects.create(user=self.alex, name="Authenticator", confirmed=True)
        self.admin_sets_password(self.alex)
        client = Client()
        client.login(username="alex", password=NEW_PASSWORD)
        self.assertRedirects(client.get("/"), "/login/code/", fetch_redirect_response=False)
        self.assertRedirects(client.get("/password/"), "/login/code/", fetch_redirect_response=False)
        client.post("/login/code/", {"code": current_code(device)})
        self.assertRedirects(client.get("/"), "/password/", fetch_redirect_response=False)

    def test_own_change_clears_flag(self):
        Profile.objects.filter(user=self.alex).update(must_change_password=True)
        client = Client()
        client.force_login(self.alex)
        pass_two_step(client, "alex")
        self.assertEqual(self.change_own(client, PASSWORD).status_code, 302)
        self.assertFalse(Profile.objects.get(user=self.alex).must_change_password)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)

    def test_remembered_removed_on_password_change(self):
        RememberedComputer.objects.create(
            user=self.alex, token_hash="b" * 64, expires_at=timezone.now() + timedelta(days=30)
        )
        self.alex.set_password(NEW_PASSWORD)
        self.alex.save()
        self.assertFalse(RememberedComputer.objects.exists())

    def test_command_password_does_not_force(self):
        self.alex.set_password(NEW_PASSWORD)
        self.alex.save()  # no request: a command at the server
        User.objects.create_user("cmd", password=NEW_PASSWORD)
        self.assertFalse(Profile.objects.get(user=self.alex).must_change_password)
        self.assertFalse(Profile.objects.filter(user__username="cmd", must_change_password=True).exists())

    def test_saving_without_password_change_keeps_flag(self):
        Profile.objects.filter(user=self.alex).update(must_change_password=True)
        self.alex.first_name = "Alex"
        self.alex.save()
        self.assertTrue(Profile.objects.get(user=self.alex).must_change_password)


@FAST_HASHER
class AdminPagesTests(TestCase):
    def setUp(self):
        self.alex = make_user("alex", "alexandria")
        self.device = TOTPDevice.objects.create(user=self.alex, name="Authenticator", confirmed=True)
        RememberedComputer.objects.create(
            user=self.alex, token_hash="c" * 64, expires_at=timezone.now() + timedelta(days=30)
        )
        make_superuser()
        self.admin = admin_client()

    def users_url(self, suffix=""):
        return f"/{settings.ADMIN_URL}auth/user/{suffix}"

    def reset_by_action(self, client):
        data = {"action": "reset_two_step", "_selected_action": [self.alex.pk]}
        return client.post(self.users_url(), data)

    def test_reset_action_superuser_only(self):
        staff = make_user("staff", "readonly")
        staff.is_staff = True
        staff.save()
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
        staff_client = admin_client("staff")
        self.assertNotContains(staff_client.get(self.users_url()), "reset_two_step")
        self.reset_by_action(staff_client)
        self.assertTrue(TOTPDevice.objects.filter(user=self.alex).exists())

        Profile.objects.filter(user=self.alex).update(setup_until=timezone.now() - timedelta(days=9))
        self.assertContains(self.admin.get(self.users_url()), "reset_two_step")
        with self.assertLogs("sheet.security", level="INFO"):
            self.assertEqual(self.reset_by_action(self.admin).status_code, 302)
        self.assertFalse(TOTPDevice.objects.filter(user=self.alex).exists())
        self.assertFalse(RememberedComputer.objects.filter(user=self.alex).exists())
        self.assertTrue(twostep.setup_open(Profile.objects.get(user=self.alex)))
        deleted = history("totpdevice", action="delete").pop()
        self.assertEqual(deleted.username, "boss")

    def test_reset_command(self):
        Profile.objects.filter(user=self.alex).update(setup_until=timezone.now() - timedelta(days=9))
        out = StringIO()
        call_command("reset_two_step", "alex", stdout=out)
        self.assertIn("alex", out.getvalue())
        self.assertFalse(TOTPDevice.objects.filter(user=self.alex).exists())
        self.assertTrue(twostep.setup_open(Profile.objects.get(user=self.alex)))
        self.assertEqual(history("totpdevice", action="delete").pop().username, "system")
        with self.assertRaises(CommandError):
            call_command("reset_two_step", "nobody")

    def test_device_admin_hides_key(self):
        for url in ("otp_totp/totpdevice/", f"otp_totp/totpdevice/{self.device.pk}/change/"):
            page = self.admin.get(f"/{settings.ADMIN_URL}{url}")
            self.assertEqual(page.status_code, 200, url)
            text = page.content.decode()
            self.assertNotIn(self.device.key, text)
            self.assertNotIn(twostep.secret_text(self.device).replace(" ", ""), text)
            self.assertNotIn("qrcode", text.lower())
        self.assertEqual(self.admin.get(f"/{settings.ADMIN_URL}otp_totp/totpdevice/add/").status_code, 403)
        user_page = self.admin.get(self.users_url(f"{self.alex.pk}/change/")).content.decode()
        self.assertNotIn(self.device.key, user_page)

    def test_staff_cannot_edit_two_step_fields(self):
        staff = make_user("staff", "readonly")
        staff.is_staff = True
        staff.save()
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
        page = admin_client("staff").get(self.users_url(f"{self.alex.pk}/change/")).content.decode()
        self.assertNotIn('name="profile-0-two_step_exempt"', page)
        self.assertNotIn('name="profile-0-must_change_password"', page)
        boss_page = self.admin.get(self.users_url(f"{self.alex.pk}/change/")).content.decode()
        self.assertIn('name="profile-0-two_step_exempt"', boss_page)
        self.assertNotIn('name="profile-0-setup_until', boss_page)  # only a reset opens a window

    def test_removing_exception_opens_window(self):
        Profile.objects.filter(user=self.alex).update(
            two_step_exempt=True, setup_until=timezone.now() - timedelta(days=9)
        )
        profile = Profile.objects.get(user=self.alex)
        profile.two_step_exempt = False
        profile.save()
        self.assertTrue(twostep.setup_open(Profile.objects.get(user=self.alex)))

    def test_make_exempt_superuser_refused(self):
        Profile.objects.filter(user=self.alex).update(two_step_exempt=True)
        page = self.admin.get(self.users_url(f"{self.alex.pk}/change/"))
        form = page.context["adminform"].form
        data = {k: v for k, v in form.initial.items() if v is not None and k not in ("password", "groups", "user_permissions", "last_login", "date_joined")}
        data.update(
            {
                "is_superuser": "on",
                "is_active": "on",
                "date_joined_0": "2026-11-18",
                "date_joined_1": "10:00:00",
                "profile-TOTAL_FORMS": "1",
                "profile-INITIAL_FORMS": "1",
                "profile-MIN_NUM_FORMS": "0",
                "profile-MAX_NUM_FORMS": "1",
                "profile-0-id": str(self.alex.profile.pk),
                "profile-0-user": str(self.alex.pk),
                "profile-0-role": "alexandria",
                "profile-0-two_step_exempt": "on",
            }
        )
        response = self.admin.post(self.users_url(f"{self.alex.pk}/change/"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remove the two-step exception first.")
        self.assertFalse(User.objects.get(pk=self.alex.pk).is_superuser)

    def test_deploy_warning_fewer_than_two_superusers(self):
        def ids():
            checks = run_checks(include_deployment_checks=True, databases=["default"])
            return [m.id for m in checks if m.id.startswith("sheet.")]

        self.assertIn("sheet.W002", ids())  # boss has no confirmed Authenticator, and is the only superuser
        self.assertNotIn("sheet.W002", [m.id for m in run_checks(include_deployment_checks=True)])  # no --database
        TOTPDevice.objects.create(user=User.objects.get(username="boss"), name="Authenticator", confirmed=True)
        self.assertIn("sheet.W002", ids())  # one key holder is not enough
        second = make_superuser("boss2")
        TOTPDevice.objects.create(user=second, name="Authenticator", confirmed=True)
        self.assertNotIn("sheet.W002", ids())


KEY = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # base32, 20 bytes


@FAST_HASHER
@override_settings(DEBUG=True)
class SeedDemoTwoStepTests(TestCase):
    def test_seed_demo_two_step_key(self):
        call_command("seed_demo", "--password", NEW_PASSWORD, "--two-step-key", KEY, stdout=StringIO())
        devices = TOTPDevice.objects.filter(confirmed=True)
        self.assertEqual(devices.count(), User.objects.count())
        self.assertTrue(all(twostep.secret_text(d).replace(" ", "") == KEY for d in devices))
        call_command("seed_demo", "--two-step-key", KEY, stdout=StringIO())  # again: no second device
        self.assertEqual(TOTPDevice.objects.count(), User.objects.count())

    def test_seed_demo_refuses_a_short_or_bad_key(self):
        for bad in ("JBSWY3DP", "not base32 at all!!"):
            with self.assertRaises(CommandError):
                call_command("seed_demo", "--two-step-key", bad, stdout=StringIO())

    def test_seed_demo_without_key_leaves_setup_to_people(self):
        call_command("seed_demo", stdout=StringIO())
        self.assertFalse(TOTPDevice.objects.exists())


@FAST_HASHER
class ReviewFindingsTests(TestCase):
    """Found by the final review (2026-11-18)."""

    def setUp(self):
        self.user = make_user("viewer", "readonly")

    def setup_device(self, client):
        client.get("/login/setup/")
        device = TOTPDevice.objects.get(user=self.user)
        code = current_code(device)
        client.post("/login/setup/", {"code": code})
        return device, code

    def test_setup_code_cannot_be_used_again(self):
        first = Client()
        first.login(username="viewer", password=PASSWORD)
        _, code = self.setup_device(first)
        self.assertEqual(first.get("/api/vessels/").status_code, 200)
        second = Client()
        second.login(username="viewer", password=PASSWORD)
        second.post("/login/code/", {"code": code})
        self.assertEqual(second.get("/api/vessels/").status_code, 401)

    def test_setup_closes_the_window(self):
        client = Client()
        client.login(username="viewer", password=PASSWORD)
        self.setup_device(client)
        self.assertIsNone(Profile.objects.get(user=self.user).setup_until)
        TOTPDevice.objects.filter(user=self.user).delete()  # a device gone without a reset: no new setup
        other = Client()
        other.login(username="viewer", password=PASSWORD)
        self.assertRedirects(other.get("/"), "/login/blocked/", fetch_redirect_response=False)

    def test_deleting_a_device_in_admin_is_a_full_reset(self):
        device = TOTPDevice.objects.create(user=self.user, name="Authenticator", confirmed=True)
        RememberedComputer.objects.create(
            user=self.user, token_hash="d" * 64, expires_at=timezone.now() + timedelta(days=30)
        )
        Profile.objects.filter(user=self.user).update(setup_until=None)
        make_superuser()
        admin = admin_client()
        url = f"/{settings.ADMIN_URL}otp_totp/totpdevice/{device.pk}/delete/"
        self.assertEqual(admin.post(url, {"post": "yes"}).status_code, 302)
        self.assertFalse(RememberedComputer.objects.filter(user=self.user).exists())
        self.assertTrue(twostep.setup_open(Profile.objects.get(user=self.user)))

    def test_remembered_needs_a_device(self):
        device = TOTPDevice.objects.create(user=self.user, name="Authenticator", confirmed=True)
        client = Client()
        client.login(username="viewer", password=PASSWORD)
        client.post("/login/code/", {"code": current_code(device), "remember": "on"})
        client.post("/logout/")
        client.login(username="viewer", password=PASSWORD)
        self.assertEqual(client.get("/api/vessels/").status_code, 200)  # remembered
        TOTPDevice.objects.filter(pk=device.pk).delete()  # removed behind the app's back
        self.assertEqual(client.get("/api/vessels/").status_code, 401)

    def test_password_rehash_at_sign_in_keeps_remembered_computers(self):
        RememberedComputer.objects.create(
            user=self.user, token_hash="e" * 64, expires_at=timezone.now() + timedelta(days=30)
        )
        with override_settings(
            PASSWORD_HASHERS=[
                "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",  # forces a re-hash of the MD5 hash
                "django.contrib.auth.hashers.MD5PasswordHasher",
            ]
        ):
            self.assertTrue(Client().login(username="viewer", password=PASSWORD))
        self.assertTrue(User.objects.get(pk=self.user.pk).password.startswith("pbkdf2_sha1$"))  # it was re-hashed
        self.assertTrue(RememberedComputer.objects.filter(user=self.user).exists())

    def test_forced_change_refuses_the_same_password(self):
        Profile.objects.filter(user=self.user).update(must_change_password=True)
        client = Client()
        client.login(username="viewer", password=PASSWORD)
        data = {"old_password": PASSWORD, "new_password1": PASSWORD, "new_password2": PASSWORD}
        page = client.post("/password/", data)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Choose a password different from the current one.")
        self.assertTrue(Profile.objects.get(user=self.user).must_change_password)

    def test_must_change_reachable_when_window_is_over(self):
        Profile.objects.filter(user=self.user).update(
            must_change_password=True, setup_until=timezone.now() - timedelta(days=1)
        )
        client = Client()
        client.login(username="viewer", password=PASSWORD)
        self.assertRedirects(client.get("/"), "/password/", fetch_redirect_response=False)
        self.assertEqual(client.get("/password/").status_code, 200)

    def test_staff_direct_post_of_reset_does_nothing(self):
        device = TOTPDevice.objects.create(user=self.user, name="Authenticator", confirmed=True)
        staff = make_user("staff", "readonly")
        staff.is_staff = True
        staff.save()
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
        data = {"action": "reset_two_step", "_selected_action": [self.user.pk]}
        admin_client("staff").post(f"/{settings.ADMIN_URL}auth/user/", data)
        self.assertTrue(TOTPDevice.objects.filter(pk=device.pk).exists())

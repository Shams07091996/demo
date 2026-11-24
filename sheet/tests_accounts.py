"""The Accounts page: superusers add people, change their name / role and turn them off or on."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import accounts
from .constants import ROLES
from .errors import BadRequest
from .models import EXEMPT_REFUSED, Profile, RememberedComputer
from .tests import ApiTestCase

GOOD_PASSWORD = "Long-enough-pass-42"


def remembered(user):
    return RememberedComputer.objects.create(user=user, token_hash=f"{user.pk:064d}",
                                             expires_at=timezone.now() + timedelta(days=30))


class AccountRulesTests(ApiTestCase):
    def new(self, **extra):
        return accounts.create_account({"username": "newbie", "first_name": "Nora", "role": "damietta",
                                        "password": GOOD_PASSWORD, **extra})

    def refused(self, message=None, **extra):
        with self.assertRaises(BadRequest) as caught:
            self.new(**extra)
        if message:
            self.assertEqual(str(caught.exception), message)
        return str(caught.exception)

    def test_create_sets_role(self):
        user = self.new()
        user.refresh_from_db()
        self.assertEqual(user.profile.role, "damietta")
        self.assertEqual(user.first_name, "Nora")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.check_password(GOOD_PASSWORD))
        self.assertIsNotNone(user.profile.setup_until)

    def test_username_rules(self):
        for bad in ("", "ab", "a" * 31, "a b", "ali@x"):
            self.refused(username=bad)
        self.assertEqual(self.new(username="a.b_c-1").username, "a.b_c-1")

    def test_username_unique_ignoring_case_and_spaces(self):
        for taken in ("ALEX", " alex "):
            self.refused(accounts.TAKEN, username=taken)
        self.assertEqual(User.objects.filter(username__iexact="alex").count(), 1)

    def test_password_rules(self):
        for bad in ("Qz9!kp", "123456789012345", "password1234"):
            message = self.refused(password=bad)
            self.assertNotIn(bad, message)
        # like the username (a 12+ character password can only be "like" a longer username)
        self.refused(username="harbourmaster", password="harbourmaster1")
        self.assertFalse(User.objects.filter(username__in=["newbie", "harbourmaster"]).exists())

    def test_name_too_long_refused(self):
        self.refused(first_name="x" * 151)
        self.refused(last_name="x" * 151)

    def test_unknown_role_refused(self):
        self.refused(role="captain")
        self.refused(role="")

    def test_update_role_names_and_active(self):
        alex = User.objects.get(username="alex")
        remembered(alex)
        accounts.update_account(alex, {"role": "suez", "first_name": "A"})
        alex.refresh_from_db()
        self.assertEqual((alex.profile.role, alex.first_name, alex.last_name), ("suez", "A", ""))
        accounts.update_account(alex, {"active": False})
        alex.refresh_from_db()
        self.assertFalse(alex.is_active)
        self.assertEqual((alex.profile.role, alex.first_name), ("suez", "A"))
        self.assertFalse(RememberedComputer.objects.filter(user=alex).exists())
        accounts.update_account(alex, {"active": True})
        alex.refresh_from_db()
        self.assertTrue(alex.is_active)

    def test_extra_keys_ignored(self):
        user = self.new(is_superuser=True, is_staff=True)
        self.assertFalse(user.is_staff or user.is_superuser)
        accounts.update_account(user, {"password": "Another-long-pass-77", "username": "renamed", "is_superuser": True,
                                       "is_staff": True})
        user.refresh_from_db()
        self.assertEqual(user.username, "newbie")
        self.assertTrue(user.check_password(GOOD_PASSWORD))
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_superuser_and_staff_read_only(self):
        boss = User.objects.create_superuser("boss", password=GOOD_PASSWORD)
        clerk = User.objects.create_user("clerk", password=GOOD_PASSWORD, is_staff=True)
        for user in (boss, clerk):
            with self.assertRaises(BadRequest) as caught:
                accounts.update_account(user, {"active": False, "first_name": "X", "role": "suez"})
            self.assertEqual(str(caught.exception), accounts.LOCKED_ACCOUNT)
            user.refresh_from_db()
            self.assertTrue(user.is_active)
            self.assertEqual(user.first_name, "")

    def test_admin_role_refused_when_exempt(self):
        alex = User.objects.get(username="alex")
        Profile.objects.filter(user=alex).update(two_step_exempt=True)
        with self.assertRaises(BadRequest) as caught:
            accounts.update_account(alex, {"role": "admin"})
        self.assertEqual(str(caught.exception), EXEMPT_REFUSED)
        self.assertEqual(Profile.objects.get(user=alex).role, "alexandria")

    def test_two_step_states(self):
        alex = User.objects.get(username="alex")
        profile = Profile.objects.get(user=alex)
        state = lambda: accounts.account_to_dict(User.objects.get(pk=alex.pk))["two_step"]  # noqa: E731
        Profile.objects.filter(pk=profile.pk).update(setup_until=timezone.now() + timedelta(hours=5))
        self.assertEqual(state(), "waiting")
        Profile.objects.filter(pk=profile.pk).update(setup_until=timezone.now() - timedelta(hours=1))
        self.assertEqual(state(), "expired")
        Profile.objects.filter(pk=profile.pk).update(setup_until=None)
        self.assertEqual(state(), "expired")
        TOTPDevice.objects.create(user=alex, name="Authenticator", confirmed=True)
        self.assertEqual(state(), "set_up")
        Profile.objects.filter(pk=profile.pk).update(two_step_exempt=True)
        self.assertEqual(state(), "exempt")

    def test_list_order_and_roles(self):
        User.objects.filter(username="admin").update(is_active=False)
        data = accounts.list_response()
        names = [a["username"] for a in data["accounts"]]
        self.assertEqual(names, sorted(n for n in names if n != "admin") + ["admin"])
        self.assertEqual(data["roles"], [list(r) for r in ROLES])
        self.assertNotIn("password", data["accounts"][0])

    def test_user_without_profile(self):
        plain = User.objects.create_user("plain", password=GOOD_PASSWORD)
        root = User.objects.create_superuser("root", password=GOOD_PASSWORD)
        before = Profile.objects.count()
        rows = {a["username"]: a for a in accounts.list_response()["accounts"]}
        self.assertEqual((rows["plain"]["role"], rows["root"]["role"]), ("readonly", "admin"))
        self.assertEqual(Profile.objects.count(), before)
        accounts.update_account(plain, {"role": "suez"})
        self.assertEqual(Profile.objects.get(user=plain).role, "suez")
        self.assertFalse(Profile.objects.filter(user=root).exists())

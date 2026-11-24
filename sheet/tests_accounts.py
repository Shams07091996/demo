"""The Accounts page: Admins (superusers) add people, change their names / ports and turn them off or on."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import accounts
from .errors import BadRequest
from .models import ChangeRecord, Port, Profile, RememberedComputer
from .tests import PASSWORD, ApiTestCase

GOOD_PASSWORD = "Long-enough-pass-42"


def remembered(user):
    return RememberedComputer.objects.create(user=user, token_hash=f"{user.pk:064d}",
                                             expires_at=timezone.now() + timedelta(days=30))


class AccountRulesTests(ApiTestCase):
    def new(self, **extra):
        return accounts.create_account({"username": "newbie", "first_name": "Nora", "home_port": "damietta",
                                        "password": GOOD_PASSWORD, **extra})

    def refused(self, message=None, **extra):
        with self.assertRaises(BadRequest) as caught:
            self.new(**extra)
        if message:
            self.assertEqual(str(caught.exception), message)
        return str(caught.exception)

    def test_create_sets_ports(self):
        user = self.new(ports=["suez", "damietta", "suez"])
        user.refresh_from_db()
        self.assertEqual((user.profile.home_port, user.profile.ports), ("damietta", ["damietta", "suez"]))
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

    def test_bad_ports_refused(self):
        self.refused(home_port="captain")
        self.refused(home_port="")
        self.refused(home_port=None)
        self.refused(ports="suez")
        self.refused(ports=[1])
        self.refused(ports=["nowhere"])
        self.refused(ports=["suez"] * 51)

    def test_turned_off_port_only_if_already_given(self):
        Port.objects.filter(key="suez").update(active=False)
        self.refused(ports=["suez"])
        self.refused(home_port="suez")
        suezuser = User.objects.get(username="suezuser")
        accounts.update_account(suezuser, {"home_port": "suez", "ports": ["suez", "damietta"]})
        self.assertEqual(Profile.objects.get(user=suezuser).ports, ["suez", "damietta"])

    def test_update_ports_names_and_active(self):
        alex = User.objects.get(username="alex")
        remembered(alex)
        accounts.update_account(alex, {"home_port": "suez", "ports": ["alexandria"], "first_name": "A"})
        alex.refresh_from_db()
        self.assertEqual((alex.profile.home_port, alex.profile.ports, alex.first_name, alex.last_name),
                         ("suez", ["suez", "alexandria"], "A", ""))
        accounts.update_account(alex, {"active": False})
        alex.refresh_from_db()
        self.assertFalse(alex.is_active)
        self.assertEqual((alex.profile.home_port, alex.first_name), ("suez", "A"))
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
                accounts.update_account(user, {"active": False, "first_name": "X", "home_port": "suez"})
            self.assertEqual(str(caught.exception), accounts.LOCKED_ACCOUNT)
            user.refresh_from_db()
            self.assertTrue(user.is_active)
            self.assertEqual(user.first_name, "")

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

    def test_list_order_and_ports(self):
        User.objects.filter(username="admin").update(is_active=False)
        data = accounts.list_response()
        names = [a["username"] for a in data["accounts"]]
        self.assertEqual(names, sorted(n for n in names if n != "admin") + ["admin"])
        self.assertEqual(data["ports"][0], ["alexandria", "Alexandria", True])
        rows = {a["username"]: a for a in data["accounts"]}
        self.assertEqual((rows["viewer"]["home_port"], rows["viewer"]["ports"]),
                         ("alexandria", ["alexandria", "portsaid", "damietta"]))
        self.assertNotIn("password", data["accounts"][0])

    def test_user_without_profile(self):
        plain = User.objects.create_user("plain", password=GOOD_PASSWORD)
        root = User.objects.create_superuser("root", password=GOOD_PASSWORD)
        before = Profile.objects.count()
        rows = {a["username"]: a for a in accounts.list_response()["accounts"]}
        self.assertEqual((rows["plain"]["home_port"], rows["plain"]["ports"]), ("", []))
        self.assertEqual(Profile.objects.count(), before)
        accounts.update_account(plain, {"home_port": "suez"})
        self.assertEqual(Profile.objects.get(user=plain).ports, ["suez"])
        self.assertFalse(Profile.objects.filter(user=root).exists())


class AccountApiTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        boss = User.objects.create_superuser("boss", password=PASSWORD)
        Profile.objects.create(user=boss)

    def body(self, **extra):
        return {"username": "newbie", "first_name": "Nora", "last_name": "Adel", "home_port": "damietta",
                "password": GOOD_PASSWORD, **extra}

    def test_only_admins(self):
        alex = User.objects.get(username="alex")
        for name in ("viewer", "alex"):
            client = self.login(name)
            self.assertEqual(self.call(client, "get", "/api/accounts/")[0], 403)
            self.assertEqual(self.call(client, "post", "/api/accounts/", self.body())[0], 403)
            self.assertEqual(self.call(client, "put", f"/api/accounts/{alex.id}/", {"home_port": "suez"})[0], 403)
        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertEqual(Profile.objects.get(user=alex).ports, ["alexandria"])
        status, data = self.call(self.login("boss"), "get", "/api/accounts/")
        self.assertEqual(status, 200)
        self.assertIn("alex", [a["username"] for a in data["accounts"]])

    def test_create_via_api(self):
        boss = self.login("boss")
        with self.captureOnCommitCallbacks(execute=True):
            status, data = self.call(boss, "post", "/api/accounts/", self.body())
        self.assertEqual(status, 201, data)
        self.assertNotIn("password", data)
        self.assertEqual((data["username"], data["home_port"], data["ports"], data["two_step"]),
                         ("newbie", "damietta", ["damietta"], "waiting"))
        user = User.objects.get(username="newbie")
        self.assertTrue(Profile.objects.get(user=user).must_change_password)
        records = ChangeRecord.objects.filter(object_type="user", object_id=user.id)
        self.assertTrue(records.exists())
        self.assertFalse(any(GOOD_PASSWORD in str(r.changes) for r in ChangeRecord.objects.all()))
        status, data = self.call(boss, "post", "/api/accounts/", self.body(username="NEWBIE"))
        self.assertEqual((status, data["error"]), (400, accounts.TAKEN))

    def test_update_via_api(self):
        boss = self.login("boss")
        alex = User.objects.get(username="alex")
        status, data = self.call(boss, "put", f"/api/accounts/{alex.id}/",
                                 {"home_port": "suez", "ports": [], "first_name": "Ali", "active": False})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["ports"], data["first_name"], data["active"]), (["suez"], "Ali", False))
        me = User.objects.get(username="boss")
        status, data = self.call(boss, "put", f"/api/accounts/{me.id}/", {"active": False})
        self.assertEqual((status, data["error"]), (400, accounts.LOCKED_ACCOUNT))
        self.assertEqual(self.call(boss, "put", "/api/accounts/999999/", {"active": False})[0], 404)

    def test_turned_off_session_stops_at_once(self):
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "get", "/api/vessels/")[0], 200)
        alex_id = User.objects.get(username="alex").id
        self.assertEqual(self.call(self.login("boss"), "put", f"/api/accounts/{alex_id}/", {"active": False})[0], 200)
        self.assertEqual(self.call(alex, "get", "/api/vessels/")[0], 401)

    def test_port_change_applies_next_request(self):
        alex = self.login("alex")
        ports = lambda: {v["port"] for v in self.call(alex, "get", "/api/vessels/")[1]["vessels"]}  # noqa: E731
        self.assertEqual(ports(), {"alexandria"})
        alex_id = User.objects.get(username="alex").id
        self.assertEqual(self.call(self.login("boss"), "put", f"/api/accounts/{alex_id}/",
                                   {"home_port": "suez", "ports": []})[0], 200)
        self.assertEqual(ports(), {"suez"})

    def test_nav_only_for_admins(self):
        for name in ("boss", "admin"):
            page = self.login(name).get("/").content.decode()
            self.assertIn('data-page="accounts"', page)
            self.assertIn('id="page-accounts"', page)
        for name in ("alex", "viewer"):
            page = self.login(name).get("/").content.decode()
            self.assertNotIn('data-page="accounts"', page)
            self.assertNotIn('id="page-accounts"', page)

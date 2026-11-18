"""Two-step login: password + a six-digit Authenticator code (TOTP)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import ChangeRecord, Profile, RememberedComputer
from .tests import FAST_HASHER, make_user


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

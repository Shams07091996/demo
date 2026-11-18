"""Port closures (their own page, per port), the delay reason rule's helper and the new Master data lists."""

from datetime import datetime, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .constants import OPTION_KIND_KEYS, is_delayed
from .models import ChangeRecord, PortClosure, Vessel


def cairo(text):
    """'2026-11-13T08:00' as an aware Cairo datetime."""
    return timezone.make_aware(datetime.fromisoformat(text))


class DelayHelperTests(SimpleTestCase):
    def test_is_delayed(self):
        arrived = cairo("2026-11-13T08:00")
        self.assertFalse(is_delayed(arrived, arrived + timedelta(hours=2)))
        self.assertTrue(is_delayed(arrived, arrived + timedelta(hours=2, minutes=1)))
        self.assertFalse(is_delayed(None, arrived))
        self.assertFalse(is_delayed(arrived, None))

    def test_option_kinds_include_delay_and_closure(self):
        self.assertIn("delay", OPTION_KIND_KEYS)
        self.assertIn("closure", OPTION_KIND_KEYS)


class ClosureModelTests(TestCase):
    def test_closure_saved_with_open_end(self):
        closure = PortClosure.objects.create(port="alexandria", start_at=cairo("2026-11-13T06:00"), reason="WEATHER")
        closure.refresh_from_db()
        self.assertIsNone(closure.end_at)
        self.assertEqual(closure.notes, "")

    def test_closure_changes_are_in_history(self):
        closure = PortClosure.objects.create(port="suez", start_at=cairo("2026-11-13T06:00"), reason="WEATHER")
        closure.reason = "FOG"
        closure.save()
        closure.delete()
        actions = list(
            ChangeRecord.objects.filter(object_type="portclosure").order_by("id").values_list("action", flat=True)
        )
        self.assertEqual(actions, ["create", "update", "delete"])

    def test_vessel_delay_reason_defaults_to_empty(self):
        vessel = Vessel.objects.create(name="X", date=datetime(2026, 11, 13).date())
        self.assertEqual(vessel.delay_reason, "")

"""The Operation app's tables: terminals (per port) and vessel visits, tracked in the History."""

import io
from datetime import datetime

from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from sheet.constants import OPTION_KIND_KEYS
from sheet.models import ChangeRecord

from .models import Terminal, Visit


def cairo(text):
    """'2026-11-20T07:00' as an aware Cairo datetime."""
    return timezone.make_aware(datetime.fromisoformat(text))


def terminal(name="AICT - ALX", port="alexandria", berths=("40/1", "40/2"), **extra):
    values = {"code": "EGAIT", "quay_length": 350, "cranes": 2, **extra}
    return Terminal.objects.create(name=name, port=port, berths=list(berths), **values)


class ModelTests(TestCase):
    def test_terminal_and_visit_saved(self):
        aict = terminal()
        visit = Visit.objects.create(terminal=aict, vessel_name="EGYCROWN", shipping_line="MAERSK",
                                     eta=cairo("2026-11-21T08:00"), planned_berth="40/1")
        aict.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(aict.berths, ["40/1", "40/2"])
        self.assertTrue(aict.active)
        self.assertEqual((visit.vessel_name, visit.planned_berth, visit.version), ("EGYCROWN", "40/1", 1))
        self.assertIsNone(visit.atb)

    def test_changes_are_in_history(self):
        visit = Visit.objects.create(terminal=terminal(), vessel_name="ROZA", shipping_line="ARKAS",
                                     eta=cairo("2026-11-21T08:00"))
        visit.vessel_name = "ROZA II"
        visit.save()
        record = ChangeRecord.objects.filter(object_type="visit", action="update").get()
        self.assertEqual(record.changes["vessel_name"], ["ROZA", "ROZA II"])
        self.assertEqual(record.port, "alexandria")
        self.assertTrue(ChangeRecord.objects.filter(object_type="terminal", action="create").exists())

    def test_line_is_a_master_data_kind(self):
        self.assertIn("line", OPTION_KIND_KEYS)

    def test_terminal_in_use_cannot_be_deleted(self):
        aict = terminal()
        Visit.objects.create(terminal=aict, vessel_name="ROZA", shipping_line="ARKAS", eta=cairo("2026-11-21T08:00"))
        with self.assertRaises(ProtectedError):
            aict.delete()

    def test_no_missing_migration(self):
        out = io.StringIO()
        try:
            call_command("makemigrations", "operation", check=True, dry_run=True, stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"A model change has no migration:\n{out.getvalue()}")

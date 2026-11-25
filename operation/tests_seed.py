"""seed_demo's Operation data: the workbook's terminals, the shipping lines, and visits around today."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from sheet.models import Option, Profile

from .figures import status
from .models import Terminal, Visit

TERMINALS = {
    "ACCHCO - ALX": ("EGALY", 500, 4, ["23", "24", "25"]),
    "AICT - ALX": ("EGAIT", 350, 2, ["40/1", "40/2"]),
    "ACCHCO - DKH": ("EGEDK", 1000, 8, ["96/1", "96/2", "96/3", "96/4"]),
    "AICT - DKH": ("EGACT", 500, 3, ["98/1", "98/2"]),
    "TMT - ALX": ("TMT", 1200, 4, ["27", "28"]),
}


@override_settings(DEBUG=True)
class SeedTests(TestCase):
    def test_operation_demo_data(self):
        call_command("seed_demo", stdout=StringIO())
        for name, (code, quay, cranes, berths) in TERMINALS.items():
            terminal = Terminal.objects.get(name=name)
            self.assertEqual((terminal.port, terminal.code, terminal.quay_length, terminal.cranes, terminal.berths),
                             ("alexandria", code, quay, cranes, berths))
        self.assertEqual(Terminal.objects.get(name="PSD EAST").port, "portsaid")
        lines = set(Option.objects.filter(kind="line", port="").values_list("value", flat=True))
        self.assertEqual(lines, {"ARKAS", "MAERSK", "SOC", "ICR", "CUL", "MCL"})
        statuses = [status(v) for v in Visit.objects.all()]
        self.assertEqual(statuses.count("Completed"), 7)
        self.assertGreaterEqual(statuses.count("Working"), 1)
        self.assertGreaterEqual(statuses.count("Planned"), 1)
        alex, viewer, marine = (Profile.objects.get(user__username=n) for n in ("alex", "viewer", "marine"))
        self.assertTrue(alex.sees("op_live") and alex.can("operation.edit") and alex.can("operation.delete"))
        self.assertTrue(viewer.sees("op_vessels") and viewer.sees("op_charts"))
        self.assertFalse(viewer.can("operation.edit") or viewer.can("operation.delete"))
        self.assertFalse(marine.sees("op_live"))
        call_command("seed_demo", stdout=StringIO())  # a second run adds nothing
        self.assertEqual(Terminal.objects.count(), 6)

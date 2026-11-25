"""Every model change has its migration in git (a missing one shows up here, not on the user's database)."""

import io

from django.core.management import call_command
from django.test import TestCase


class MigrationsUpToDateTests(TestCase):
    def test_no_missing_migration(self):
        out = io.StringIO()
        try:
            call_command("makemigrations", "sheet", check=True, dry_run=True, stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"A model change has no migration:\n{out.getvalue()}")

"""Supply chain: the Python packages installed in production are locked to exact versions and file hashes."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
PINNED = re.compile(r"^[A-Za-z0-9_.\-\[\]]+==\S+")


def normalise(name):
    return re.sub(r"[-_.]+", "-", name.split("[")[0]).strip().lower()


def lock_entries():
    """Each requirement of requirements.txt with its continuation lines joined: (requirement, [hashes])."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8").replace("\\\n", " ")
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement, *rest = line.split()
        entries.append((requirement, [part for part in rest if part.startswith("--hash=sha256:")]))
    return entries


class LockedRequirementsTests(SimpleTestCase):
    def test_requirements_are_pinned_with_hashes(self):
        entries = lock_entries()
        self.assertTrue(entries)
        for requirement, hashes in entries:
            with self.subTest(requirement=requirement):
                self.assertRegex(requirement, PINNED)
                self.assertTrue(hashes, f"{requirement} has no --hash=sha256:")

    def test_every_direct_requirement_is_in_the_lock(self):
        pinned = {normalise(requirement.split("==")[0]) for requirement, _ in lock_entries()}
        direct = [
            re.split(r"[<>=!~;\s]", line.strip(), maxsplit=1)[0]
            for line in (ROOT / "requirements.in").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(direct)
        for name in direct:
            with self.subTest(name=name):
                self.assertIn(normalise(name), pinned)
        # psycopg[binary] needs its binary package locked too.
        self.assertIn("psycopg-binary", pinned)

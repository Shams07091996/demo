"""Front-end safety rules checked on the source files themselves."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC_JS = Path(settings.BASE_DIR) / "sheet" / "static" / "sheet"
TOOLS = Path(settings.BASE_DIR) / "tools"
EVAL = re.compile(r"\beval\s*\(|\bFunction\s*\(")


def script_files():
    yield from STATIC_JS.rglob("*.js")
    yield from STATIC_JS.rglob("*.mjs")
    yield from (p for p in TOOLS.glob("*.js"))


class NoEvalTests(SimpleTestCase):
    def test_no_eval_or_new_function_in_any_script(self):
        offenders = [
            f"{path.relative_to(settings.BASE_DIR)}: {match.group(0)}"
            for path in script_files()
            for match in EVAL.finditer(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])

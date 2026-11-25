"""Every page's Excel file has the page's table headings, in the page's order (read from the front end's files), so
the two cannot drift apart. Buttons-only columns (Summary, Delete, the row's action) are not in the file."""

import re
from pathlib import Path

from django.test import SimpleTestCase

from operation import visits

from . import dataexport

JS = Path(__file__).parent / "static/sheet/js"
TEMPLATE = Path(__file__).parent / "templates/sheet/index.html"


def _array(text, name):
    """The source of `const NAME = [ ... ];`."""
    return re.search(rf"const {name} = \[([\s\S]*?)\n\](?:\.filter\(Boolean\))?;", text).group(1)


def titles(file, name):
    return re.findall(r"title: '([^']+)'", _array((JS / file).read_text(encoding="utf-8"), name))


def heads_statement(file):
    """The quoted headings of `const heads = [...]` (permission keys and the empty action heading left out)."""
    text = (JS / file).read_text(encoding="utf-8")
    statement = re.search(r"const heads = \[([\s\S]*?)\];", text).group(1)
    return [s for s in re.findall(r"'([^']*)'", statement) if s and "." not in s]


def vessels_heads():
    """The Vessels table's headings in index.html (the button columns Summary / Delete left out)."""
    html = TEMPLATE.read_text(encoding="utf-8")
    head = re.search(r"<thead>([\s\S]*?)</thead>", html[html.index('id="tbody"') - 3000:]).group(1)
    names = [re.sub(r"<[^>]+>", "", th).strip() for th in re.findall(r"<th[^>]*>([\s\S]*?)</th>", head)]
    return [n for n in names if n and n != "Summary"]


FRONT = {
    "vessels": vessels_heads,
    "hotels": lambda: titles("pages/bookings.js", "HOTEL_COLUMNS"),
    "transfers": lambda: titles("pages/bookings.js", "TRANSFER_COLUMNS"),
    "closures": lambda: titles("pages/closures.js", "COLUMNS"),
    "disposal": lambda: heads_statement("pages/disposal.js"),
    "calculations": lambda: titles("pages/calculations.js", "COLUMNS"),
    "services": lambda: heads_statement("pages/services.js"),
}


class PageHeadingTests(SimpleTestCase):
    def test_every_page_export_has_the_page_headings(self):
        self.assertEqual(set(FRONT), set(dataexport.PAGES))
        for page, read in FRONT.items():
            self.assertEqual([heading for heading, _rule in dataexport.COLUMNS[page]], read(), page)

    def test_split_columns_belong_to_a_page_column(self):
        for page, heading in dataexport.SPLIT:
            self.assertIn(heading, [h for h, _rule in dataexport.COLUMNS[page]])

    def test_vessel_data_export_has_the_page_headings(self):
        text = (JS / "pages/opVessels.js").read_text(encoding="utf-8")
        front = re.findall(r"\[(?:'\w+'|null), '([^']+)'", _array(text, "COLUMNS"))
        self.assertEqual(visits.EXPORT_HEAD, front)

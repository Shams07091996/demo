"""The standard-library .xlsx writer: parts, typed cells, styles, charts."""

import io
import re
import zipfile
from xml.etree import ElementTree

from django.test import SimpleTestCase

from . import xlsx


def open_parts(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def two_sheets():
    chart = xlsx.Chart(kind="bar", title="Revenue", categories=(2, 4, 0), series=[("Revenue", 2, 4, 1)],
                       anchor=(4, 1))
    first = xlsx.Sheet(name="By line", rows=[[xlsx.Bold("Title")], ["Line", "Revenue"], ["MSK", 10.0],
                                              ["ARK", 5.5], ["CMA", 1.0]], widths=[20, 14], charts=[chart])
    second = xlsx.Sheet(name="Notes", rows=[["only text"]], widths=[30], charts=[])
    return xlsx.build([first, second])


class XlsxTests(SimpleTestCase):
    def test_parts_present_and_parse(self):
        parts = open_parts(two_sheets())
        for name in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
                     "xl/styles.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml",
                     "xl/worksheets/_rels/sheet1.xml.rels", "xl/drawings/drawing1.xml",
                     "xl/drawings/_rels/drawing1.xml.rels", "xl/charts/chart1.xml"):
            self.assertIn(name, parts)
        self.assertNotIn("xl/drawings/drawing2.xml", parts)
        self.assertNotIn("xl/worksheets/_rels/sheet2.xml.rels", parts)
        for name, text in parts.items():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(text)  # noqa: S314 -- our own output; raises on malformed XML

    def test_numbers_are_numbers(self):
        sheet = xlsx.Sheet(name="S", rows=[["A", 3, 12.5, xlsx.Hours(1.25), xlsx.Money(7)]], widths=[], charts=[])
        xml = open_parts(xlsx.build([sheet]))["xl/worksheets/sheet1.xml"]
        cells = dict(re.findall(r'<c r="([A-Z]+1)"([^>]*)>', xml))
        for ref, value in (("B1", "3"), ("C1", "12.5"), ("D1", "1.25"), ("E1", "7")):
            self.assertIn(f'<c r="{ref}"', xml)
            self.assertNotIn("inlineStr", cells[ref])
            self.assertRegex(xml, rf'<c r="{ref}"[^>]*><v>{re.escape(value)}</v></c>')
        styles = {ref: re.search(r's="(\d+)"', attrs).group(1) for ref, attrs in cells.items() if ref != "A1"}
        self.assertEqual(len({styles["B1"], styles["C1"], styles["D1"]}), 3)
        self.assertEqual(styles["C1"], styles["E1"])  # a plain float is money

    def test_text_escaped_and_never_formula(self):
        sheet = xlsx.Sheet(name="S", rows=[["<b>x</b>", "=1+1", "@SUM(A1)", '-2+3"']], widths=[], charts=[])
        xml = open_parts(xlsx.build([sheet]))["xl/worksheets/sheet1.xml"]
        self.assertIn("<t>&lt;b&gt;x&lt;/b&gt;</t>", xml)
        self.assertEqual(xml.count('t="inlineStr"'), 4)
        self.assertNotIn("<f>", xml)

    def test_bold_heading_style(self):
        parts = open_parts(xlsx.build([xlsx.Sheet(name="S", rows=[[xlsx.Bold("Title")]], widths=[], charts=[])]))
        style = int(re.search(r'<c r="A1" s="(\d+)"', parts["xl/worksheets/sheet1.xml"]).group(1))
        xfs = re.findall(r"<xf [^>]*/>|<xf [^>]*>.*?</xf>", parts["xl/styles.xml"].split("<cellXfs")[1])
        font = int(re.search(r'fontId="(\d+)"', xfs[style]).group(1))
        fonts = re.findall(r"<font>.*?</font>", parts["xl/styles.xml"])
        self.assertIn("<b/>", fonts[font])

    def test_chart_refers_to_its_sheet(self):
        chart_xml = open_parts(two_sheets())["xl/charts/chart1.xml"]
        self.assertIn("'By line'!$B$3:$B$5", chart_xml)
        self.assertIn("'By line'!$A$3:$A$5", chart_xml)
        self.assertIn('<c:barDir val="bar"/>', chart_xml)
        for kind, marker in (("column", '<c:barDir val="col"/>'), ("line", "<c:lineChart>")):
            chart = xlsx.Chart(kind=kind, title="T", categories=(0, 1, 0), series=[("V", 0, 1, 1)], anchor=(3, 0))
            data = xlsx.build([xlsx.Sheet(name="S", rows=[["a", 1], ["b", 2]], widths=[], charts=[chart])])
            self.assertIn(marker, open_parts(data)["xl/charts/chart1.xml"])

    def test_safe_sheet_name(self):
        name = xlsx.safe_sheet_name("a/b:c*d?[e]" * 3)
        self.assertLessEqual(len(name), 31)
        self.assertFalse(set(name) & set("[]:*?/\\"))

    def test_line_chart_straight_lines(self):
        # Excel smooths a line series without <c:smooth val="0"/>: the curve then dips below zero between months.
        chart = xlsx.Chart(kind="line", title="T", categories=(0, 2, 0), series=[("V", 0, 2, 1), ("W", 0, 2, 1)],
                           anchor=(3, 0))
        data = xlsx.build([xlsx.Sheet(name="S", rows=[["a", 0], ["b", 0], ["c", 9]], widths=[], charts=[chart])])
        self.assertEqual(open_parts(data)["xl/charts/chart1.xml"].count('</c:val><c:smooth val="0"/></c:ser>'), 2)

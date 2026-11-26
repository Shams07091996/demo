"""The standard-library .xlsx writer: parts, typed cells, styles, charts."""

import io
import re
import zipfile
from xml.etree import ElementTree

from django.test import SimpleTestCase

from . import xlsx


def open_parts(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {name: archive.read(name) if name.startswith("xl/media/") else archive.read(name).decode("utf-8")
            for name in archive.namelist()}


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

    def test_escape_sequence_text_shown_as_typed(self):
        # Excel decodes _xHHHH_ in strings: "_x0041_" would show as "A" unless its underscore is escaped.
        sheet = xlsx.Sheet(name="S", rows=[["_x0041_ and _x003D_1"]], widths=[], charts=[])
        xml = open_parts(xlsx.build([sheet]))["xl/worksheets/sheet1.xml"]
        self.assertIn("<t>_x005F_x0041_ and _x005F_x003D_1</t>", xml)


class DateCellTests(SimpleTestCase):
    def cells(self, *values):
        parts = open_parts(xlsx.build([xlsx.Sheet("S", [list(values)])]))
        return parts["xl/worksheets/sheet1.xml"], parts["xl/styles.xml"]

    def test_day_cell(self):
        from datetime import date

        sheet, styles = self.cells(xlsx.Day(date(2026, 11, 24)))
        self.assertIn(f'<c r="A1" s="{xlsx.DAY}"><v>46350</v></c>', sheet)
        self.assertIn('formatCode="dd/mm/yyyy"', styles)

    def test_moment_cell_in_cairo_time(self):
        from datetime import UTC, datetime

        sheet, styles = self.cells(xlsx.Moment(datetime(2026, 11, 24, 8, 0, tzinfo=UTC)))
        value = float(re.search(r'<c r="A1" s="(\d+)"><v>([^<]+)</v>', sheet).group(2))
        self.assertAlmostEqual(value, 46350 + 10 / 24, places=6)  # Cairo is UTC+2 in November
        self.assertIn(f's="{xlsx.MOMENT}"', sheet)
        self.assertIn('formatCode="dd/mm/yyyy hh:mm"', styles)

    def test_empty_day_and_moment(self):
        sheet, _ = self.cells(xlsx.Day(None), xlsx.Moment(None), "x")
        self.assertNotIn('r="A1"', sheet)
        self.assertNotIn('r="B1"', sheet)

    def test_style_counts_match(self):
        styles = open_parts(xlsx.build([xlsx.Sheet("S", [["x"]])]))["xl/styles.xml"]
        for tag, child in (("numFmts", "numFmt"), ("cellXfs", "xf")):
            block = re.search(rf"<{tag} count=\"(\d+)\">(.*?)</{tag}>", styles)
            self.assertEqual(int(block.group(1)), block.group(2).count(f"<{child} "), tag)


class NumberCellTests(SimpleTestCase):
    def test_number_cell_has_general_format(self):
        sheet = open_parts(xlsx.build([xlsx.Sheet("S", [[xlsx.Number(1234), xlsx.Number(48.6512), xlsx.Number(None)]])]))
        sheet = sheet["xl/worksheets/sheet1.xml"]
        self.assertIn('<c r="A1"><v>1234</v></c>', sheet)  # no thousands separator, no 2-decimal rounding on show
        self.assertIn('<c r="B1"><v>48.6512</v></c>', sheet)
        self.assertNotIn('r="C1"', sheet)


def tiny_png(width=2, height=3):
    """A valid PNG header (signature + IHDR) of the given size; the rest is not needed to read the size."""
    import struct
    import zlib
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk


def tiny_jpeg(width=640, height=480):
    """SOI, an APP0 segment, then a SOF0 segment with the size."""
    import struct
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


class PictureTests(SimpleTestCase):
    def test_png_size(self):
        self.assertEqual(xlsx.picture_size(tiny_png(2, 3)), (2, 3))

    def test_jpeg_size(self):
        self.assertEqual(xlsx.picture_size(tiny_jpeg(640, 480)), (640, 480))

    def test_unreadable_size_is_skipped(self):
        self.assertIsNone(xlsx.picture_size(b"\x89PNG\r\n\x1a\n"))
        self.assertIsNone(xlsx.picture_size(b"\xff\xd8\xff\xe0\x00"))
        self.assertIsNone(xlsx.picture_size(b"GIF89a"))
        self.assertIsNone(xlsx.picture_size(b""))

    def test_picture_in_workbook(self):
        picture = xlsx.Picture(data=tiny_png(), kind="png", width=200, height=100, anchor=(0, 2))
        sheet = xlsx.Sheet(name="ACCHCO", rows=[["Title"]], pictures=[picture])
        parts = open_parts(xlsx.build([sheet]))
        self.assertEqual(parts["xl/media/image1.png"], tiny_png())
        self.assertIn("<xdr:pic>", parts["xl/drawings/drawing1.xml"])
        self.assertIn('cx="1905000" cy="952500"', parts["xl/drawings/drawing1.xml"])
        self.assertIn('Extension="png"', parts["[Content_Types].xml"])
        self.assertIn('<drawing r:id="rId1"/>', parts["xl/worksheets/sheet1.xml"])
        self.assertIn("../media/image1.png", parts["xl/drawings/_rels/drawing1.xml.rels"])
        for name, text in parts.items():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(text)  # noqa: S314 -- our own output

    def test_chart_and_picture_share_drawing(self):
        chart = xlsx.Chart(kind="bar", title="T", categories=(1, 2, 0), series=[("V", 1, 2, 1)], anchor=(4, 1))
        pictures = [xlsx.Picture(data=tiny_jpeg(), kind="jpeg", width=64, height=48, anchor=(0, 5))]
        sheet = xlsx.Sheet(name="S", rows=[["a", 1], ["b", 2]], charts=[chart], pictures=pictures)
        parts = open_parts(xlsx.build([sheet]))
        rels = parts["xl/drawings/_rels/drawing1.xml.rels"]
        self.assertIn('Id="rId1"', rels)
        self.assertIn("../charts/chart1.xml", rels)
        self.assertIn('Id="rId2"', rels)
        self.assertIn("../media/image1.jpeg", rels)
        self.assertIn('r:embed="rId2"', parts["xl/drawings/drawing1.xml"])
        self.assertIn('Extension="jpeg"', parts["[Content_Types].xml"])
        self.assertNotIn("xl/drawings/drawing2.xml", parts)

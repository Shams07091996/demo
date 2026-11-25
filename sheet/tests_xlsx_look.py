"""The page look of the Excel files (xlsx.table_sheet): title line, styled header, borders, fitted widths, frozen
header with filter arrows, status cells coloured like the page's pills, a bold totals row."""

import re
from datetime import date
from xml.etree import ElementTree

from django.test import SimpleTestCase

from . import xlsx
from .tests_xlsx import open_parts

NS = {"m": xlsx.MAIN}


def table():
    rows = [["MSC AURORA", xlsx.Day(date(2026, 11, 3)), 2, xlsx.Money(10.0), xlsx.Status("Completed", "done")],
            ["A VERY LONG VESSEL NAME THAT GOES ON", xlsx.Day(date(2026, 11, 4)), 1, xlsx.Money(10.0),
             xlsx.Status("Cancelled", "cancel")]]
    return xlsx.table_sheet("Hotels", "Hotels", "01/11/2026 – 30/11/2026", ["Vessel", "Check-in", "Nights", "Cost",
                                                                            "Status"],
                            rows, total=["Total", None, 3, xlsx.Money(20.0), None])


def parts_of(*sheets):
    return open_parts(xlsx.build(list(sheets)))


def cell_style(sheet_xml, ref):
    return int(re.search(rf'<c r="{ref}"(?: s="(\d+)")?', sheet_xml).group(1) or 0)


def xf(styles, index):
    xfs = re.search(r"<cellXfs count=\"\d+\">(.*?)</cellXfs>", styles).group(1)
    return re.findall(r"<xf [^>]*?/?>", xfs)[index]


def pick(styles, tag, index):
    block = re.search(rf"<{tag}s count=\"\d+\">(.*?)</{tag}s>", styles).group(1)
    return re.findall(rf"<{tag}\b[^>]*/>|<{tag}\b[^>]*>.*?</{tag}>", block)[index]


def attr(element, name):
    return int(re.search(rf'{name}="(\d+)"', element).group(1))


class TableSheetTests(SimpleTestCase):
    def setUp(self):
        self.parts = parts_of(table())
        self.sheet = self.parts["xl/worksheets/sheet1.xml"]
        self.styles = self.parts["xl/styles.xml"]

    def test_layout_title_filters_header_rows_total(self):
        rows = table().rows
        self.assertEqual(rows[0], [xlsx.Title("Hotels")])
        self.assertEqual(rows[1], ["01/11/2026 – 30/11/2026"])
        self.assertEqual(rows[3], ["Vessel", "Check-in", "Nights", "Cost", "Status"])
        self.assertEqual(rows[-1][0], "Total")

    def test_header_frozen_with_filter_arrows(self):
        self.assertIn('<pane ySplit="4" topLeftCell="A5" activePane="bottomLeft" state="frozen"/>', self.sheet)
        self.assertIn('<autoFilter ref="A4:E6"/>', self.sheet)
        self.assertIn("_xlnm._FilterDatabase", self.parts["xl/workbook.xml"])
        self.assertIn("'Hotels'!$A$4:$E$6", self.parts["xl/workbook.xml"])

    def test_header_bold_on_the_header_colour_with_a_line_under(self):
        header = xf(self.styles, cell_style(self.sheet, "A4"))
        self.assertIn("<b/>", pick(self.styles, "font", attr(header, "fontId")))
        self.assertIn(xlsx.HEADER_FILL, pick(self.styles, "fill", attr(header, "fillId")))
        self.assertIn('<bottom style="medium">', pick(self.styles, "border", attr(header, "borderId")))

    def test_body_cells_have_thin_lines_and_keep_their_format(self):
        day = xf(self.styles, cell_style(self.sheet, "B5"))
        self.assertIn('numFmtId="165"', day)
        self.assertIn('<bottom style="thin">', pick(self.styles, "border", attr(day, "borderId")))
        self.assertIn('numFmtId="4"', xf(self.styles, cell_style(self.sheet, "D5")))

    def test_status_cells_coloured_like_the_pills(self):
        done = xf(self.styles, cell_style(self.sheet, "E5"))
        cancel = xf(self.styles, cell_style(self.sheet, "E6"))
        self.assertIn(xlsx.TONES["done"][0], pick(self.styles, "fill", attr(done, "fillId")))
        self.assertIn(xlsx.TONES["cancel"][0], pick(self.styles, "fill", attr(cancel, "fillId")))
        self.assertIn("<strike/>", pick(self.styles, "font", attr(cancel, "fontId")))
        self.assertIn("<t>Completed</t>", self.sheet)

    def test_total_row_bold_with_a_line_over(self):
        total = xf(self.styles, cell_style(self.sheet, "D7"))
        self.assertIn("<b/>", pick(self.styles, "font", attr(total, "fontId")))
        self.assertIn('<top style="medium">', pick(self.styles, "border", attr(total, "borderId")))
        self.assertIn('numFmtId="4"', total)

    def test_title_is_large_and_bold(self):
        title = xf(self.styles, cell_style(self.sheet, "A1"))
        font = pick(self.styles, "font", attr(title, "fontId"))
        self.assertIn("<b/>", font)
        self.assertIn('<sz val="14"/>', font)

    def test_widths_fit_the_contents(self):
        widths = table().widths
        self.assertGreater(widths[0], widths[2])  # the long vessel name vs. "Nights"
        self.assertGreaterEqual(widths[1], 11)  # dd/mm/yyyy
        self.assertLessEqual(max(widths), 60)
        self.assertGreaterEqual(min(widths), 8)

    def test_every_style_count_matches_and_the_parts_parse(self):
        for tag, child in (("numFmts", "numFmt"), ("fonts", "font"), ("fills", "fill"), ("borders", "border"),
                           ("cellXfs", "xf")):
            block = re.search(rf"<{tag} count=\"(\d+)\">(.*?)</{tag}>", self.styles)
            self.assertEqual(int(block.group(1)), len(re.findall(rf"<{child}[ >/]", block.group(2))), tag)
        for name, text in self.parts.items():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(text.encode("utf-8"))  # noqa: S314 -- our own output

    def test_worksheet_children_in_schema_order(self):
        root = ElementTree.fromstring(self.sheet.encode("utf-8"))  # noqa: S314 -- our own output
        names = [child.tag.split("}")[1] for child in root]
        self.assertEqual(names, ["sheetViews", "cols", "sheetData", "autoFilter"])

    def test_empty_table_still_has_header_and_filter(self):
        sheet = xlsx.table_sheet("Hotels", "Hotels", "", ["Vessel"], [])
        xml = parts_of(sheet)["xl/worksheets/sheet1.xml"]
        self.assertIn('<autoFilter ref="A4:A4"/>', xml)

    def test_old_sheets_unchanged(self):
        xml = parts_of(xlsx.Sheet("S", [["x", 1]]))["xl/worksheets/sheet1.xml"]
        self.assertNotIn("<pane", xml)
        self.assertNotIn("autoFilter", xml)
        self.assertIn(f'<c r="B1" s="{xlsx.WHOLE}"><v>1</v></c>', xml)


class PriceCellTests(SimpleTestCase):
    def test_price_is_a_number_shown_with_its_currency(self):
        sheet = xlsx.table_sheet("S", "S", "x", ["Cost"], [[xlsx.Price(1234.5, "USD")], [xlsx.Price(10, "LE")]])
        parts = parts_of(sheet)
        xml, styles = parts["xl/worksheets/sheet1.xml"], parts["xl/styles.xml"]
        self.assertRegex(xml, r'<c r="A5" s="\d+"><v>1234.5</v></c>')
        self.assertIn('formatCode="&quot;USD &quot;#,##0.00"', styles)
        self.assertIn('formatCode="&quot;LE &quot;#,##0.00"', styles)
        usd, le = xf(styles, cell_style(xml, "A5")), xf(styles, cell_style(xml, "A6"))
        self.assertNotEqual(attr(usd, "numFmtId"), attr(le, "numFmtId"))

    def test_odd_currency_falls_back_to_plain_money(self):
        xml = parts_of(xlsx.Sheet("S", [[xlsx.Price(5, '"; X')]]))["xl/worksheets/sheet1.xml"]
        self.assertIn(f'<c r="A1" s="{xlsx.MONEY}"><v>5</v></c>', xml)


class WrapTests(SimpleTestCase):
    def test_a_two_line_cell_wraps(self):
        parts = parts_of(xlsx.table_sheet("S", "S", "x", ["Item", "Other"], [["Fresh Water\nnote", "one line"]]))
        xml, styles = parts["xl/worksheets/sheet1.xml"], parts["xl/styles.xml"]
        two = re.search(r"<cellXfs[^>]*>(.*?)</cellXfs>", styles).group(1)
        xfs = re.findall(r"<xf [^>]*?(?:/>|>.*?</xf>)", two)
        self.assertIn('wrapText="1"', xfs[cell_style(xml, "A5")])
        self.assertNotIn('wrapText="1"', xfs[cell_style(xml, "B5")])

"""A small .xlsx writer (Office Open XML) with the standard library only: sheets of typed cells and native charts.

An .xlsx file is a zip of XML parts: the workbook, one part per sheet, a style sheet, and per sheet with charts a
drawing that places DrawingML chart parts. Excel draws the charts from the sheet's own cells (no cached values).

The page look (`table_sheet`): a title line, the filters line, then the table with a bold header on the page's
header colour, thin row lines, columns sized to fit, the header frozen with filter arrows, status cells coloured like
the page's pills and a bold totals row. Colours are the light theme's tokens (app.css).

Safety: every text is an inline string, escaped, with characters XML cannot hold removed; text never becomes a formula
(no <f> element is ever written), whatever it starts with. Numbers are written as numbers.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.sax.saxutils import escape

from django.utils import timezone

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
CT = "application/vnd.openxmlformats-officedocument"

# Cell styles (cellXfs positions): 0 normal, 1 bold, 2 whole number, 3 money, 4 hours, 5 day, 6 day and time.
NORMAL, BOLD, WHOLE, MONEY, HOURS, DAY, MOMENT = range(7)
_EPOCH = datetime(1899, 12, 30)  # Excel's day 0 (it counts 1900 as a leap year; every date after Feb 1900 is right)
CHART_COLS, CHART_ROWS = 8, 18
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_BAD_NAME = re.compile(r"[\[\]:*?/\\]")
_CURRENCY = re.compile(r"[A-Z]{2,4}")


@dataclass(frozen=True)
class Bold:
    text: str


@dataclass(frozen=True)
class Money:
    value: float


@dataclass(frozen=True)
class Hours:
    value: float | None


@dataclass(frozen=True)
class Number:
    """A number shown exactly as stored (General format: no thousands separator, no rounding on show), as other
    programs and Excel's own CSV save need it. None: an empty cell."""

    value: float | int | None


@dataclass(frozen=True)
class Day:
    """A calendar date, shown dd/mm/yyyy (a real Excel date). None: an empty cell."""

    value: date | None


@dataclass(frozen=True)
class Moment:
    """A date and time, shown dd/mm/yyyy hh:mm in Cairo time (an aware value is converted first). None: empty."""

    value: datetime | None


@dataclass(frozen=True)
class Status:
    """A status word coloured like the page's pill: tone is a key of TONES."""

    text: str
    tone: str


@dataclass(frozen=True)
class Price:
    """An amount shown with its currency, as the page shows it ("USD 1,234.50"); still a number in Excel. A currency
    that is not 2-4 capital letters is shown as plain money."""

    value: float
    currency: str


@dataclass(frozen=True)
class Title:
    """The big bold first line of a table sheet."""

    text: str


@dataclass
class Chart:
    kind: str  # "bar" (horizontal bars), "column" or "line"
    title: str
    categories: tuple  # (first_row, last_row, col), 0-based
    series: list  # [(name, first_row, last_row, col)]
    anchor: tuple  # (col, row), 0-based


@dataclass
class Sheet:
    name: str
    rows: list
    widths: list = field(default_factory=list)
    charts: list = field(default_factory=list)
    looks: dict = field(default_factory=dict)  # row index (0-based) -> "header" | "body" | "total" | "muted"
    freeze: int = 0  # rows kept on screen when scrolling (the title lines and the header)
    filter: tuple | None = None  # (header row, last row, columns), 0-based: the filter arrows


# The light theme (app.css): header row on --surface2 with --muted text, lines in --line; pills are the status
# colour at ~16 % over white (fill) with the colour itself as text.
HEADER_FILL, HEADER_TEXT, LINE, STRONG_LINE = "FFEEF0F2", "FF1B1D20", "FFE3E7EC", "FF9AA1AB"
TONES = {
    "progress": ("FFEFE6D6", "FF9A5B00"),  # In progress / Working
    "done": ("FFDBEAE1", "FF1B7A43"),  # Completed / Closed
    "cancel": ("FFEDEDED", "FF646A73"),  # Cancelled (struck through)
    "info": ("FFDEE8FC", "FF2563EB"),  # Planned / Open
    "muted": ("FFEDEDED", "FF646A73"),
}
MIN_WIDTH, MAX_WIDTH = 8, 60


def safe_sheet_name(name):
    return _BAD_NAME.sub("", str(name)).strip()[:31] or "Sheet"


def _text(value):
    return escape(_BAD_XML.sub("", str(value)))


def _attr(value):
    return escape(_BAD_XML.sub("", str(value)), {'"': "&quot;"})


def _col(index):
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _number(value):
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _serial(value):
    """Excel's serial number of a date (whole days) or a date and time (with the fraction of the day)."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value).replace(tzinfo=None)
        delta = value - _EPOCH
        return delta.days + delta.seconds / 86400 + delta.microseconds / 86400e6
    return (value - _EPOCH.date()).days


def _content(value):
    """(number format id, bold, tone, xml after the style) of a non-empty cell, or None for an empty one."""
    if value is None:
        return None
    if isinstance(value, Number):
        return None if value.value is None else (0, False, None, f"><v>{_number(value.value)}</v></c>")
    if isinstance(value, Day | Moment):
        if value.value is None:
            return None
        return (165 if isinstance(value, Day) else 166, False, None, f"><v>{_number(_serial(value.value))}</v></c>")
    if isinstance(value, Price):
        fmt = f'"{value.currency} "#,##0.00' if _CURRENCY.fullmatch(str(value.currency)) else 4
        return (fmt, False, None, f"><v>{_number(value.value)}</v></c>")
    if isinstance(value, Hours | Money):
        if value.value is None:
            return None
        return (164 if isinstance(value, Hours) else 4, False, None, f"><v>{_number(value.value)}</v></c>")
    if isinstance(value, int) and not isinstance(value, bool):
        return (3, False, None, f"><v>{value}</v></c>")
    if isinstance(value, float):
        return (4, False, None, f"><v>{_number(value)}</v></c>")
    bold, tone = False, None
    if isinstance(value, Bold | Title):
        bold, text = True, value.text
    elif isinstance(value, Status):
        tone, text = value.tone, value.text
    elif isinstance(value, bool):
        text = "Yes" if value else "No"
    else:
        text = value
    text = str(text).replace("_x", "_x005F_x")  # Excel decodes _xHHHH_ in strings; escape it to show what was typed
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return (0, bold, tone, f' t="inlineStr"><is><t{space}>{_text(text)}</t></is></c>')


# The fixed cell styles of a sheet without a look (NORMAL, BOLD, WHOLE, MONEY, HOURS, DAY, MOMENT).
_PLAIN = {(0, False): NORMAL, (0, True): BOLD, (3, False): WHOLE, (4, False): MONEY, (164, False): HOURS,
          (165, False): DAY, (166, False): MOMENT}


class _Styles:
    """The workbook's fonts, fills, borders and cell formats; the first seven formats are the fixed ones."""

    def __init__(self):
        self.fonts = ["<font><sz val=\"11\"/><name val=\"Calibri\"/></font>",
                      "<font><b/><sz val=\"11\"/><name val=\"Calibri\"/></font>"]
        self.fills = ['<fill><patternFill patternType="none"/></fill>',
                      '<fill><patternFill patternType="gray125"/></fill>']
        self.borders = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
        self.formats = {}  # format code -> id (164.. are fixed below; currencies from 167)
        self.xfs = [(0, 0, 0, 0), (0, 1, 0, 0), (3, 0, 0, 0), (4, 0, 0, 0), (164, 0, 0, 0), (165, 0, 0, 0),
                    (166, 0, 0, 0)]

    @staticmethod
    def _add(items, xml):
        if xml not in items:
            items.append(xml)
        return items.index(xml)

    def font(self, bold=False, size=11, color=None, strike=False):
        xml = ("<font>" + ("<b/>" if bold else "") + ("<strike/>" if strike else "") + f'<sz val="{size}"/>'
               + (f'<color rgb="{color}"/>' if color else "") + '<name val="Calibri"/></font>')
        return self._add(self.fonts, xml)

    def fill(self, rgb):
        return self._add(self.fills, f'<fill><patternFill patternType="solid"><fgColor rgb="{rgb}"/>'
                                     f'<bgColor indexed="64"/></patternFill></fill>')

    def border(self, top="thin", bottom="thin", top_color=LINE, bottom_color=LINE):
        side = f'<left style="thin"><color rgb="{LINE}"/></left><right style="thin"><color rgb="{LINE}"/></right>'
        return self._add(self.borders, f'<border>{side}<top style="{top}"><color rgb="{top_color}"/></top>'
                                       f'<bottom style="{bottom}"><color rgb="{bottom_color}"/></bottom>'
                                       f"<diagonal/></border>")

    def xf(self, fmt, font, fill, border):
        if isinstance(fmt, str):
            fmt = self.formats.setdefault(fmt, 167 + len(self.formats))
        key = (fmt, font, fill, border)
        if key not in self.xfs:
            self.xfs.append(key)
        return self.xfs.index(key)

    def look(self, look, fmt, bold, tone):
        """The cell format of one cell of a row with a look."""
        if look == "title":
            return self.xf(fmt, self.font(bold=True, size=14), 0, 0)
        if look == "muted":
            return self.xf(fmt, self.font(size=10, color=TONES["muted"][1]), 0, 0)
        if look == "header":
            return self.xf(fmt, self.font(bold=True, color=HEADER_TEXT), self.fill(HEADER_FILL),
                           self.border(bottom="medium", bottom_color=STRONG_LINE))
        if look == "total":
            return self.xf(fmt, self.font(bold=True), 0, self.border(top="medium", top_color=STRONG_LINE))
        if tone in TONES:
            fill, color = TONES[tone]
            return self.xf(fmt, self.font(bold=True, color=color, strike=tone == "cancel"), self.fill(fill),
                           self.border())
        return self.xf(fmt, self.font(bold=bold) if bold else 0, 0, self.border())

    def xml(self):
        xfs = "".join(f'<xf numFmtId="{fmt}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0"'
                      + (' applyNumberFormat="1"' if fmt else "") + (' applyFont="1"' if font else "")
                      + (' applyFill="1"' if fill else "") + (' applyBorder="1"' if border else "") + "/>"
                      for fmt, font, fill, border in self.xfs)
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{MAIN}">'
                f'<numFmts count="{3 + len(self.formats)}"><numFmt numFmtId="164" formatCode="0.0"/>'
                '<numFmt numFmtId="165" formatCode="dd/mm/yyyy"/>'
                '<numFmt numFmtId="166" formatCode="dd/mm/yyyy hh:mm"/>'
                + "".join(f'<numFmt numFmtId="{i}" formatCode="{_attr(code)}"/>' for code, i in self.formats.items())
                + "</numFmts>"
                f'<fonts count="{len(self.fonts)}">{"".join(self.fonts)}</fonts>'
                f'<fills count="{len(self.fills)}">{"".join(self.fills)}</fills>'
                f'<borders count="{len(self.borders)}">{"".join(self.borders)}</borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(self.xfs)}">{xfs}</cellXfs>'
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def _cell(ref, value, styles=None, look=None):
    """One <c> element, or "" for an empty cell (a styled row's empty cells keep their lines and colour)."""
    content = _content(value)
    if look and look not in ("title", "muted"):
        fmt, bold, tone, body = content or (0, False, None, "/>")
        style = styles.look(look, fmt, bold, tone)
        return f'<c r="{ref}" s="{style}"{body if content else "/>"}'
    if content is None:
        return ""
    fmt, bold, tone, body = content
    if look:
        style = styles.look(look, fmt, bold, tone)
    elif isinstance(fmt, str):
        style = styles.xf(fmt, 0, 0, 0)
    else:
        style = _PLAIN.get((fmt, bold), NORMAL)
    if isinstance(value, Number):
        style = NORMAL
    return f'<c r="{ref}"' + (f' s="{style}"' if style else "") + body


def _sheet_xml(sheet, has_drawing, styles):
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(sheet.widths) if w)
    width = max((len(row) for row in sheet.rows), default=0)
    rows = []
    for r, row in enumerate(sheet.rows, 1):
        look = sheet.looks.get(r - 1)
        cells = list(row) + [None] * (width - len(row)) if look in ("header", "body", "total") else row
        xml = "".join(_cell(f"{_col(c)}{r}", value, styles, look) for c, value in enumerate(cells))
        rows.append(f'<row r="{r}">{xml}</row>')
    view = ""
    if sheet.freeze:
        view = (f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{sheet.freeze}" '
                f'topLeftCell="A{sheet.freeze + 1}" activePane="bottomLeft" state="frozen"/>'
                f'<selection pane="bottomLeft"/></sheetView></sheetViews>')
    auto = f'<autoFilter ref="{_filter_ref(sheet.filter)}"/>' if sheet.filter else ""
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{MAIN}" xmlns:r="{REL}">'
            + view + (f"<cols>{cols}</cols>" if cols else "") + f"<sheetData>{''.join(rows)}</sheetData>"
            + auto + ('<drawing r:id="rId1"/>' if has_drawing else "") + "</worksheet>")


def _filter_ref(spec, absolute=False):
    first, last, columns = spec
    sign = "$" if absolute else ""
    return f"{sign}A{sign}{first + 1}:{sign}{_col(max(columns, 1) - 1)}{sign}{max(last, first) + 1}"


def _shown(value):
    """How many characters a cell needs on screen (for the column width)."""
    if isinstance(value, Day):
        return 10 if value.value else 0
    if isinstance(value, Moment):
        return 16 if value.value else 0
    if isinstance(value, Price):
        return len(value.currency) + 1 + len(f"{value.value:,.2f}")
    if isinstance(value, Number | Hours | Money):
        value = value.value
        if value is None:
            return 0
    if isinstance(value, bool):
        return 3
    if isinstance(value, int | float):
        return len(f"{value:,.2f}") if isinstance(value, float) else len(f"{value:,}")
    if isinstance(value, Bold | Status | Title):
        value = value.text
    return max((len(line) for line in str(value).splitlines()), default=0) if value is not None else 0


def fit_widths(rows):
    """Column widths that fit the longest value of each column (header included), within MIN_WIDTH..MAX_WIDTH."""
    columns = max((len(row) for row in rows), default=0)
    return [min(MAX_WIDTH, max(MIN_WIDTH, max((_shown(row[c]) for row in rows if c < len(row)), default=0) + 3))
            for c in range(columns)]


def table_sheet(name, title, subtitle, head, rows, total=None):
    """A page's table with the page look: title, filters line, empty line, header, rows, optional totals row."""
    rows = [list(row) for row in rows]
    layout = [[Title(title)], [subtitle] if subtitle else [], [], list(head), *rows]
    looks = {3: "header", 1: "muted", 0: "title"}
    looks.update({4 + i: "body" for i in range(len(rows))})
    if total:
        layout.append(list(total))
        looks[len(layout) - 1] = "total"
    return Sheet(name, layout, widths=fit_widths([head, *rows, *([total] if total else [])]), looks=looks, freeze=4,
                 filter=(3, 3 + len(rows), len(head)))


def _quoted(sheet_name):
    return "'" + sheet_name.replace("'", "''") + "'"


def _ref(sheet_name, first_row, last_row, col):
    return f"{_quoted(sheet_name)}!${_col(col)}${first_row + 1}:${_col(col)}${last_row + 1}"


def _chart_xml(sheet_name, chart):
    cats = _ref(sheet_name, *chart.categories)
    series = "".join(
        f'<c:ser><c:idx val="{i}"/><c:order val="{i}"/><c:tx><c:v>{_text(name)}</c:v></c:tx>'
        + ('<c:marker><c:symbol val="circle"/></c:marker>' if chart.kind == "line" else "")
        + f"<c:cat><c:strRef><c:f>{_text(cats)}</c:f></c:strRef></c:cat>"
        f"<c:val><c:numRef><c:f>{_text(_ref(sheet_name, first, last, col))}</c:f></c:numRef></c:val>"
        + ('<c:smooth val="0"/>' if chart.kind == "line" else "")  # straight lines: a smoothed curve dips below 0
        + "</c:ser>"
        for i, (name, first, last, col) in enumerate(chart.series)
    )
    axes_ids = '<c:axId val="1"/><c:axId val="2"/>'
    if chart.kind == "line":
        plot = (f'<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>{series}'
                f'<c:marker val="1"/>{axes_ids}</c:lineChart>')
    else:
        direction = "bar" if chart.kind == "bar" else "col"
        plot = (f'<c:barChart><c:barDir val="{direction}"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
                f'{series}<c:gapWidth val="80"/>{axes_ids}</c:barChart>')
    cat_pos, val_pos = ("l", "b") if chart.kind == "bar" else ("b", "l")
    orientation = "maxMin" if chart.kind == "bar" else "minMax"  # horizontal bars read top-down, like the table
    axes = (f'<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="{orientation}"/></c:scaling>'
            f'<c:delete val="0"/><c:axPos val="{cat_pos}"/><c:numFmt formatCode="General" sourceLinked="0"/>'
            f'<c:tickLblPos val="low"/><c:crossAx val="2"/><c:crosses val="autoZero"/><c:auto val="1"/>'
            f'<c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>'
            f'<c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
            f'<c:axPos val="{val_pos}"/><c:majorGridlines/><c:numFmt formatCode="#,##0" sourceLinked="0"/>'
            f'<c:tickLblPos val="nextTo"/><c:crossAx val="1"/><c:crosses val="autoZero"/>'
            f'<c:crossBetween val="between"/></c:valAx>')
    legend = '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>' if len(chart.series) > 1 else ""
    title = (f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{_text(chart.title)}</a:t></a:r></a:p>'
             f'</c:rich></c:tx><c:overlay val="0"/></c:title>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<c:chartSpace xmlns:c="{C_NS}" xmlns:a="{A_NS}" xmlns:r="{REL}"><c:chart>{title}'
            f'<c:autoTitleDeleted val="0"/><c:plotArea><c:layout/>{plot}{axes}</c:plotArea>{legend}'
            f'<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart></c:chartSpace>')


def _drawing_xml(charts):
    anchors = []
    for i, chart in enumerate(charts, 1):
        col, row = chart.anchor
        anchors.append(
            f"<xdr:twoCellAnchor><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row>"
            f"<xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to><xdr:col>{col + CHART_COLS}</xdr:col>"
            f"<xdr:colOff>0</xdr:colOff><xdr:row>{row + CHART_ROWS}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
            f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{i + 1}" name="Chart {i}"/>'
            f'<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            f'</xdr:xfrm><a:graphic><a:graphicData uri="{C_NS}"><c:chart xmlns:c="{C_NS}" r:id="rId{i}"/>'
            f"</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>"
        )
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<xdr:wsDr xmlns:xdr="{DRAWING_NS}" xmlns:a="{A_NS}" xmlns:r="{REL}">{"".join(anchors)}</xdr:wsDr>')


def _rels(targets):
    """targets: [(type suffix, target)] -> a .rels part with rId1.. in order."""
    items = "".join(f'<Relationship Id="rId{i}" Type="{REL}/{kind}" Target="{target}"/>'
                    for i, (kind, target) in enumerate(targets, 1))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{PKG_REL}">{items}</Relationships>')


def build(sheets):
    """The workbook as .xlsx bytes. Sheet names are made safe and unique."""
    names, seen = [], set()
    for sheet in sheets:
        name = safe_sheet_name(sheet.name)
        base, n = name, 2
        while name.casefold() in seen:
            suffix = f" ({n})"
            name, n = base[:31 - len(suffix)] + suffix, n + 1
        seen.add(name.casefold())
        names.append(name)

    parts = {}
    overrides = [("/xl/workbook.xml", f"{CT}.spreadsheetml.sheet.main+xml"),
                 ("/xl/styles.xml", f"{CT}.spreadsheetml.styles+xml")]
    drawing_no = chart_no = 0
    styles = _Styles()
    for i, (sheet, name) in enumerate(zip(sheets, names, strict=True), 1):
        parts[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheet, bool(sheet.charts), styles)
        overrides.append((f"/xl/worksheets/sheet{i}.xml", f"{CT}.spreadsheetml.worksheet+xml"))
        if not sheet.charts:
            continue
        drawing_no += 1
        parts[f"xl/worksheets/_rels/sheet{i}.xml.rels"] = _rels([("drawing", f"../drawings/drawing{drawing_no}.xml")])
        parts[f"xl/drawings/drawing{drawing_no}.xml"] = _drawing_xml(sheet.charts)
        overrides.append((f"/xl/drawings/drawing{drawing_no}.xml", f"{CT}.drawing+xml"))
        chart_targets = []
        for chart in sheet.charts:
            chart_no += 1
            parts[f"xl/charts/chart{chart_no}.xml"] = _chart_xml(name, chart)
            overrides.append((f"/xl/charts/chart{chart_no}.xml", f"{CT}.drawingml.chart+xml"))
            chart_targets.append(("chart", f"../charts/chart{chart_no}.xml"))
        parts[f"xl/drawings/_rels/drawing{drawing_no}.xml.rels"] = _rels(chart_targets)

    sheet_list = "".join(f'<sheet name="{_attr(name)}" sheetId="{i}" r:id="rId{i}"/>'
                         for i, name in enumerate(names, 1))
    filters = "".join(
        f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
        f"{_text(_quoted(name))}!{_filter_ref(sheet.filter, absolute=True)}</definedName>"
        for i, (sheet, name) in enumerate(zip(sheets, names, strict=True)) if sheet.filter)
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{sheet_list}</sheets>'
                                + (f"<definedNames>{filters}</definedNames>" if filters else "") + "</workbook>")
    parts["xl/_rels/workbook.xml.rels"] = _rels(
        [("worksheet", f"worksheets/sheet{i}.xml") for i in range(1, len(sheets) + 1)] + [("styles", "styles.xml")])
    parts["xl/styles.xml"] = styles.xml()
    parts["_rels/.rels"] = _rels([("officeDocument", "xl/workbook.xml")])
    types = "".join(f'<Override PartName="{p}" ContentType="{t}"/>' for p, t in overrides)
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'<Default Extension="xml" ContentType="application/xml"/>{types}</Types>')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", parts.pop("[Content_Types].xml"))  # first, by convention
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()

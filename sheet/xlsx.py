"""A small .xlsx writer (Office Open XML) with the standard library only: sheets of typed cells and native charts.

An .xlsx file is a zip of XML parts: the workbook, one part per sheet, a style sheet, and per sheet with charts a
drawing that places DrawingML chart parts. Excel draws the charts from the sheet's own cells (no cached values).

Safety: every text is an inline string, escaped, with characters XML cannot hold removed; text never becomes a formula
(no <f> element is ever written), whatever it starts with. Numbers are written as numbers.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
CT = "application/vnd.openxmlformats-officedocument"

# Cell styles (cellXfs positions): 0 normal, 1 bold, 2 whole number, 3 money, 4 hours.
NORMAL, BOLD, WHOLE, MONEY, HOURS = range(5)
CHART_COLS, CHART_ROWS = 8, 18
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_BAD_NAME = re.compile(r"[\[\]:*?/\\]")


@dataclass(frozen=True)
class Bold:
    text: str


@dataclass(frozen=True)
class Money:
    value: float


@dataclass(frozen=True)
class Hours:
    value: float | None


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


def _cell(ref, value):
    """One <c> element, or "" for an empty cell."""
    if value is None:
        return ""
    if isinstance(value, Bold):
        style, text = BOLD, value.text
    elif isinstance(value, Hours | Money):
        if value.value is None:
            return ""
        return f'<c r="{ref}" s="{HOURS if isinstance(value, Hours) else MONEY}"><v>{_number(value.value)}</v></c>'
    elif isinstance(value, bool):
        style, text = NORMAL, "Yes" if value else "No"
    elif isinstance(value, int):
        return f'<c r="{ref}" s="{WHOLE}"><v>{value}</v></c>'
    elif isinstance(value, float):
        return f'<c r="{ref}" s="{MONEY}"><v>{_number(value)}</v></c>'
    else:
        style, text = NORMAL, value
    text = str(text)
    space = ' xml:space="preserve"' if text != text.strip() else ""
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{ref}"{style_attr} t="inlineStr"><is><t{space}>{_text(text)}</t></is></c>'


def _sheet_xml(sheet, has_drawing):
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(sheet.widths) if w)
    rows = []
    for r, row in enumerate(sheet.rows, 1):
        cells = "".join(_cell(f"{_col(c)}{r}", value) for c, value in enumerate(row))
        rows.append(f'<row r="{r}">{cells}</row>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{MAIN}" xmlns:r="{REL}">'
            + (f"<cols>{cols}</cols>" if cols else "") + f"<sheetData>{''.join(rows)}</sheetData>"
            + ('<drawing r:id="rId1"/>' if has_drawing else "") + "</worksheet>")


def _ref(sheet_name, first_row, last_row, col):
    quoted = sheet_name.replace("'", "''")
    return f"'{quoted}'!${_col(col)}${first_row + 1}:${_col(col)}${last_row + 1}"


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


STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{MAIN}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
)


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
    for i, (sheet, name) in enumerate(zip(sheets, names, strict=True), 1):
        parts[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(sheet, bool(sheet.charts))
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
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{sheet_list}</sheets></workbook>')
    parts["xl/_rels/workbook.xml.rels"] = _rels(
        [("worksheet", f"worksheets/sheet{i}.xml") for i in range(1, len(sheets) + 1)] + [("styles", "styles.xml")])
    parts["xl/styles.xml"] = STYLES
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

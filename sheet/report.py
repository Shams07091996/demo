"""The management workbook's tables, for a date range and port: one source for each figure, no new money maths.

Money comes from the Calculations rows (calculations.rows_for: services, hotel stays, transfers, garbage & sludge),
so the Summary equals the Calculations page's totals. Counts follow the Dashboard (a Crew Change is one service and
one job; arrival and sailing are one job each). Every table is {"head", "rows", "total"}; a sheet is
{"title", "tables", "notes"}. Plain values only: xlsx turns floats into money cells and ints into counts.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from . import calculations, crewbookings, moneyaccess, xlsx
from . import dashboard as dashboard_figures
from . import ports as port_table
from .access import scoped_closures, scoped_vessels
from .constants import SERVICE_STATUSES, SERVICE_TYPES, is_delayed
from .xlsx import Bold, Hours

NO_LINE, NO_AGENT_LABEL = "(no line)", "(no agent)"
MONEY_HEAD = ["Revenue (EGP)", "Cost (EGP)", "Profit (EGP)"]
KIND_NAMES = {"Hotel stay": "Hotels", "Transfer": "Transport"}
# Calculations rows that belong to a page: a person without it gets the workbook without those lines.
ROW_PAGES = {"Hotel stay": "hotels", "Transfer": "transport", "Garbage & Sludge": "disposal"}
SERVICE_ORDER = [*SERVICE_TYPES, "Hotels", "Transport", "Garbage & Sludge"]


@dataclass
class Range:
    date_from: date
    date_to: date
    port: str | None


def _months(r):
    year, month = r.date_from.year, r.date_from.month
    while (year, month) <= (r.date_to.year, r.date_to.month):
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


class _Group:
    """Vessels, services and money of one group of vessels (a port, a month, a line...)."""

    def __init__(self):
        self.vessels = self.services = 0
        self.revenue = self.cost = self.profit = 0.0

    def add(self, vessel, money):
        self.vessels += 1
        self.services += vessel["services_count"]
        revenue, cost, profit = money
        self.revenue += revenue
        self.cost += cost
        self.profit += profit

    def row(self, *labels):
        return [*labels, self.vessels, self.services, round(self.revenue, 2), round(self.cost, 2),
                round(self.profit, 2)]


def _sheet(title, tables, notes=()):
    return {"title": title, "tables": tables, "notes": list(notes)}


def _table(head, rows, total=None):
    return {"head": head, "rows": rows, "total": total}


def _grouped(vessels, money, key):
    groups = {}
    for vessel in vessels:
        groups.setdefault(key(vessel), _Group()).add(vessel, money[vessel["id"]])
    return groups


def _money_by_vessel(rows):
    money = {}
    for row in rows:
        revenue, cost, profit = money.get(row["vessel"]["id"], (0.0, 0.0, 0.0))
        money[row["vessel"]["id"]] = (revenue + row["revenue_egp"], cost + row["cost_egp"],
                                      profit + row["profit_egp"])
    return money


def _totals(rows):
    return [round(sum(r[key] for r in rows), 2) for key in ("revenue_egp", "cost_egp", "profit_egp")]


def _summary(vessels, money, rows, profile):
    groups = _grouped(vessels, money, lambda v: v["port"])
    table = _table(["Port", "Vessels", "Services", *MONEY_HEAD],
                   [groups[key].row(label) for key, label in port_table.ordered() if key in groups],
                   ["Total", len(vessels), sum(v["services_count"] for v in vessels), *_totals(rows)])
    if not moneyaccess.views(profile):  # the notes are about money
        return _sheet("Summary", [table])
    extras = [name for name, page in (("hotels", "hotels"), ("transport", "transport"),
                                      ("garbage & sludge", "disposal")) if profile.sees(page)]
    notes = [f"Money includes {', '.join(extras[:-1])} and {extras[-1]}." if len(extras) > 1
             else f"Money includes {extras[0]}."] if extras else []
    rate_missing = sum(1 for r in rows if r["rate_missing"])
    price_missing = sum(1 for r in rows if r.get("price_missing"))
    if rate_missing:
        notes.append(f"{rate_missing} money lines used USD 1:1 (no exchange rate for that month).")
    if price_missing:
        notes.append(f"{price_missing} garbage / sludge lines had no price.")
    return _sheet("Summary", [table], notes)


def _by_month(vessels, money, rows, r):
    groups = _grouped(vessels, money, lambda v: v["date"][:7])
    table_rows = [(groups.get(month) or _Group()).row(month) for month in _months(r)]
    total = ["Total", len(vessels), sum(v["services_count"] for v in vessels), *_totals(rows)]
    return _sheet("By month", [_table(["Month", "Vessels", "Services", *MONEY_HEAD], table_rows, total)])


def _by_line(vessels, money, profile):
    lines = _grouped(vessels, money, lambda v: v["opr"] or NO_LINE)
    # Ranked by revenue only for people who may see it; otherwise by vessels (the order would show the money).
    rank = (lambda name: -lines[name].revenue) if moneyaccess.views(profile) else (lambda name: -lines[name].vessels)
    order = sorted(lines, key=lambda name: (rank(name), name.casefold()))
    first = _table(["Line", "Vessels", "Services", *MONEY_HEAD], [lines[name].row(name) for name in order])
    pairs = _grouped(vessels, money, lambda v: (v["opr"] or NO_LINE, v["port"]))
    second = _table(["Line", "Port", "Vessels", "Services", *MONEY_HEAD],
                    [pairs[(name, key)].row(name, label) for name in order for key, label in port_table.ordered()
                     if (name, key) in pairs])
    return _sheet("By line", [first, second])


def _by_service(rows):
    groups = {}
    for row in rows:
        name = KIND_NAMES.get(row["kind"], row["kind"])
        entry = groups.setdefault(name, [0, 0.0, 0.0, 0.0])
        entry[0] += 1
        entry[1] += row["revenue_egp"]
        entry[2] += row["cost_egp"]
        entry[3] += row["profit_egp"]
    table_rows = [[name, groups[name][0], *(round(x, 2) for x in groups[name][1:])]
                  for name in SERVICE_ORDER if name in groups]
    total = ["Total", len(rows), *_totals(rows)]
    return _sheet("Profit by service", [_table(["Service", "Lines", *MONEY_HEAD], table_rows, total)])


def _agents(profile, r):
    params = {"from": r.date_from.isoformat(), "to": r.date_to.isoformat(), "port": r.port or ""}
    figures = dashboard_figures.response(profile, params)
    types = figures["service_types"]
    rows = [[a["agent"] or NO_AGENT_LABEL, a["arrivals"], a["sailings"], *(a["by_type"].get(t, 0) for t in types),
             a["total"]] for a in figures["agents"]]
    return _sheet("Agents", [_table(["Agent", "Arrivals", "Sailings", *types, "Total"], rows)])


def _average(values):
    return Hours(round(sum(values) / len(values), 1) if values else None)


class _Times:
    """Waiting (arrival → berthing), at berth (berthing → sailing) and in port (arrival → sailing) of some vessels."""

    PAIRS = (("arrival_at", "berthing_at"), ("berthing_at", "sailing_at"), ("arrival_at", "sailing_at"))

    def __init__(self):
        self.hours = [[], [], []]
        self.with_times = self.delayed = self.vessels = 0

    def add(self, vessel):
        self.vessels += 1
        found = False
        for hours, (start, end) in zip(self.hours, self.PAIRS, strict=True):
            start, end = getattr(vessel, start), getattr(vessel, end)
            if start and end:
                hours.append((end - start).total_seconds() / 3600)
                found = True
        self.with_times += found
        self.delayed += is_delayed(vessel.arrival_at, vessel.berthing_at)

    def row(self, label):
        return [label, self.with_times, *(_average(h) for h in self.hours), self.delayed]


def _ports_perf(objects, r):
    head = ["Vessels with times", "Avg waiting (h)", "Avg at berth (h)", "Avg in port (h)", "Delayed vessels"]
    ports, months, reasons, berths = {}, {month: _Times() for month in _months(r)}, {}, {}
    for vessel in objects:
        ports.setdefault(vessel.port, _Times()).add(vessel)
        if vessel.terminal or vessel.berth:
            berths.setdefault((vessel.port, vessel.terminal, vessel.berth), _Times()).add(vessel)
        months[f"{vessel.date:%Y-%m}"].add(vessel)
        if vessel.delay_reason:
            reasons[vessel.delay_reason] = reasons.get(vessel.delay_reason, 0) + 1
    by_reason = sorted(reasons.items(), key=lambda item: (-item[1], item[0].casefold()))
    order = {key: i for i, (key, _) in enumerate(port_table.ordered())}
    calls = sorted(berths.items(), key=lambda item: (order.get(item[0][0], len(order)), item[0][1].casefold(),
                                                     item[0][2].casefold()))
    return _sheet("Port performance", [
        _table(["Port", *head], [ports[key].row(label) for key, label in port_table.ordered() if key in ports]),
        _table(["Month", *head], [times.row(month) for month, times in months.items()]),
        _table(["Delay reason", "Vessels"], [list(item) for item in by_reason]),
        _table(["Port", "Terminal", "Berth", "Vessels", *head[1:]],
               [[port_table.label(port), terminal or "-", berth or "-", times.vessels, *times.row("")[2:]]
                for (port, terminal, berth), times in calls]),
    ], ["Averages count only vessels that have both times."])


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _closures(profile, r, now):
    start, end = _day_start(r.date_from), _day_start(r.date_to + timedelta(days=1))
    closures = scoped_closures(profile, r.port).filter(start_at__lt=end)
    closures = closures.filter(end_at__isnull=True) | closures.filter(end_at__gte=start)
    ports, reasons = {}, {}
    for closure in closures:
        hours = max(0.0, (min(closure.end_at or now, end) - max(closure.start_at, start)).total_seconds() / 3600)
        port = ports.setdefault(closure.port, [0, 0.0, 0])
        port[0] += 1
        port[1] += hours
        port[2] += closure.end_at is None
        reason = reasons.setdefault(closure.reason, [0, 0.0])
        reason[0] += 1
        reason[1] += hours
    by_reason = sorted(reasons.items(), key=lambda item: (-item[1][1], item[0].casefold()))
    return _sheet("Port closures", [
        _table(["Port", "Closures", "Hours closed", "Still closed"],
               [[label, ports[key][0], Hours(round(ports[key][1], 1)), ports[key][2]]
                for key, label in port_table.ordered() if key in ports]),
        _table(["Reason", "Closures", "Hours closed"],
               [[name, count, Hours(round(hours, 1))] for name, (count, hours) in by_reason]),
    ], ["Hours count only the part of each closure inside the range; a closure still going on counts up to now."])


def _crew(objects, rows, profile):
    lines = {}

    def line(vessel):
        return lines.setdefault(vessel.opr or NO_LINE, [0, 0, 0, 0, 0.0, 0, 0])

    for vessel in objects:
        for service in vessel.services.all():
            if service.service_type == "Crew Change":
                entry, data = line(vessel), service.data or {}
                entry[0] += 1
                entry[1] += len(data.get("onSigners") or [])
                entry[2] += len(data.get("offSigners") or [])
                entry[3] += crewbookings.early_on_signers(service)
        stays, transfers = vessel.hotel_stays.all(), vessel.transfers.all()
        if stays or transfers:
            entry = line(vessel)
            entry[5] += sum(stay.nights for stay in stays)
            entry[6] += len(transfers)
    by_id = {vessel.id: vessel for vessel in objects}
    for row in rows:
        if row["kind"] == "Crew Change" and row["label"].startswith("Broken visa"):
            line(by_id[row["vessel"]["id"]])[4] += row["revenue_egp"]
    order = sorted(lines, key=lambda name: (-lines[name][0], name.casefold()))
    table_rows = [[name, *lines[name][:4], round(lines[name][4], 2), *lines[name][5:]] for name in order]
    total = ["Total", *(sum(row[i] for row in table_rows) for i in range(1, 5)),
             round(sum(row[5] for row in table_rows), 2), *(sum(row[i] for row in table_rows) for i in (6, 7))]
    head = ["Line", "Crew changes", "On-signers", "Off-signers", "Early arrivals", "Broken visa revenue (EGP)",
            "Hotel nights", "Transfers"]
    # The Hotel nights / Transfers columns only for people with that page.
    keep = [i for i, name in enumerate(head) if not ((name == "Hotel nights" and not profile.sees("hotels"))
                                                     or (name == "Transfers" and not profile.sees("transport")))]
    head, total = [head[i] for i in keep], [total[i] for i in keep]
    table_rows = [[row[i] for i in keep] for row in table_rows]
    return _sheet("Crew", [_table(head, table_rows, total if table_rows else None)],
                  ["Early arrivals: on-signers landing 2 or more days before the vessel date."])


def _disposal(objects, rows, r):
    def blank():
        return [0.0, 0.0, 0.0, 0.0, 0.0]

    ports, months = {}, {month: blank() for month in _months(r)}
    by_id = {vessel.id: vessel for vessel in objects}

    def entries(vessel):
        return ports.setdefault(vessel.port, blank()), months[f"{vessel.date:%Y-%m}"]

    for vessel in objects:
        record = getattr(vessel, "disposal", None)
        if record and not record.hidden and (record.garbage or record.sludge):
            for entry in entries(vessel):
                entry[0] += float(record.garbage or 0)
                entry[1] += float(record.sludge or 0)
    for row in rows:
        if row["kind"] == "Garbage & Sludge":
            for entry in entries(by_id[row["vessel"]["id"]]):
                entry[2] += row["revenue_egp"]
                entry[3] += row["cost_egp"]
                entry[4] += row["profit_egp"]

    def values(entry):
        return [round(x, 3) for x in entry[:2]] + [round(x, 2) for x in entry[2:]]

    head = ["Garbage (m³)", "Sludge (t)", *MONEY_HEAD]
    port_rows = [[label, *values(ports[key])] for key, label in port_table.ordered() if key in ports]
    total = ["Total", *values([sum(entry[i] for entry in ports.values()) for i in range(5)])]
    return _sheet("Garbage & Sludge", [
        _table(["Port", *head], port_rows, total if port_rows else None),
        _table(["Month", *head], [[month, *values(entry)] for month, entry in months.items()]),
    ], ["Vessels marked as having no garbage or sludge are left out."])


STATUS_HEAD = ["Month", "In progress", "Completed", "Cancelled", "Open", "Closed"]


def _service_status(objects, rows, r):
    """Services per operations status and Calculations rows Open / Closed, per vessel-date month."""
    months = {month: [0, 0, 0, 0, 0] for month in _months(r)}
    order = list(SERVICE_STATUSES)
    for vessel in objects:
        for service in vessel.services.all():
            months[f"{vessel.date:%Y-%m}"][order.index(service.status)] += 1
    for row in rows:
        months[row["vessel"]["date"][:7]][4 if row["closed"] else 3] += 1
    table_rows = [[month, *counts] for month, counts in months.items()]
    total = ["Total", *(sum(row[i] for row in table_rows) for i in range(1, 6))]
    return _sheet("Service status", [_table(STATUS_HEAD, table_rows, total)],
                  ["Open / Closed: the Calculations rows (lines with money), as accounting marked them."])


def _vessels(profile, r):
    """(queryset, Vessel objects with services / bookings / disposal, plain vessel dicts) in the range and scope."""
    queryset = scoped_vessels(profile, r.port, prefetch=False).filter(date__gte=r.date_from, date__lte=r.date_to)
    objects = list(queryset.prefetch_related("services", "hotel_stays", "transfers").select_related("disposal"))
    plain = [{"id": v.id, "port": v.port, "opr": v.opr, "date": v.date.isoformat(),
              "services_count": len(v.services.all())} for v in objects]
    return queryset, objects, plain


def data(profile, r, now=None):
    """Every sheet's tables, keyed: summary, months, lines, services, ports_perf, closures, agents, crew, disposal,
    service_status."""
    queryset, objects, vessels = _vessels(profile, r)
    known = {v["id"] for v in vessels}
    # Only the vessels read above: one saved into the range meanwhile must not crash the report (or be half in it).
    rows = [row for row in calculations.rows_for(queryset) if row["vessel"]["id"] in known
            and profile.sees(ROW_PAGES.get(row["kind"], "vessels"))]
    money = {v["id"]: (0.0, 0.0, 0.0) for v in vessels} | _money_by_vessel(rows)
    sheets = {
        "summary": _summary(vessels, money, rows, profile),
        "months": _by_month(vessels, money, rows, r),
        "lines": _by_line(vessels, money, profile),
        "services": _by_service(rows),
        "ports_perf": _ports_perf(objects, r),
        "closures": _closures(profile, r, now or timezone.now()) if profile.sees("closures") else None,
        "agents": _agents(profile, r),
        "crew": _crew(objects, rows, profile),
        "disposal": _disposal(objects, rows, r) if profile.sees("disposal") else None,
        "service_status": _service_status(objects, rows, r),
    }
    # Sheets of pages the person doesn't have are left out (access rework piece 2); without money.view, the money
    # columns and the sheet that is only money (piece 3).
    if not moneyaccess.views(profile):
        sheets["services"] = None
    return {key: _without_money(sheet, profile) for key, sheet in sheets.items() if sheet is not None}


def _pick(row, keep):
    return [row[i] for i in keep]


def _without_money(sheet, profile):
    """The sheet without the money columns this person may not get (head, rows and total alike)."""
    tables = []
    for table in sheet["tables"]:
        gone = moneyaccess.money_columns(table["head"], profile)
        keep = [i for i in range(len(table["head"])) if i not in gone]
        tables.append(_table(_pick(table["head"], keep), [_pick(row, keep) for row in table["rows"]],
                             _pick(table["total"], keep) if table["total"] else table["total"]))
    return {**sheet, "tables": tables}


def port_label(r):
    return port_table.label(r.port) if r.port else "All ports"


# (chart kind, title, table index, [series column heads]); the first column of that table holds the categories.
# A chart whose series column is not there (money columns without money.view) is not drawn.
CHARTS = {
    "summary": ("column", "Profit per port (EGP)", 0, ["Profit (EGP)"]),
    "months": ("line", "Revenue, cost and profit per month (EGP)", 0, ["Revenue (EGP)", "Cost (EGP)", "Profit (EGP)"]),
    "lines": ("bar", "Revenue per line (EGP)", 0, ["Revenue (EGP)"]),
    "services": ("bar", "Profit per service (EGP)", 0, ["Profit (EGP)"]),
    "ports_perf": ("column", "Average waiting per port (h)", 0, ["Avg waiting (h)"]),
    "closures": ("column", "Hours closed per port", 0, ["Hours closed"]),
    "agents": ("bar", "Jobs per agent", 0, ["Total"]),
    "crew": ("column", "On- and off-signers per line", 0, ["On-signers", "Off-signers"]),
    "disposal": ("column", "Garbage (m³) and sludge (t) per month", 1, ["Garbage (m³)", "Sludge (t)"]),
    "service_status": ("column", "Services per status per month", 0, ["In progress", "Completed", "Cancelled"]),
}


def _has_data(sheet):
    """Any count or amount other than zero in any table row (zero-filled months alone are no data)."""
    for table in sheet["tables"]:
        for row in table["rows"]:
            for value in row[1:]:
                value = value.value if isinstance(value, Hours) else value
                if isinstance(value, int | float) and not isinstance(value, bool) and value:
                    return True
    return False


def _layout(key, sheet, subtitle):
    rows, starts = [[Bold(sheet["title"])], [subtitle], []], []
    if not _has_data(sheet):
        rows.append(["No data"])
        return xlsx.Sheet(name=xlsx.safe_sheet_name(sheet["title"]), rows=rows, widths=[24], charts=[])
    for table in sheet["tables"]:
        starts.append(len(rows))
        rows.append([Bold(str(cell)) for cell in table["head"]])
        rows += table["rows"]
        if table["total"]:
            rows.append([Bold(str(table["total"][0])), *table["total"][1:]])
        rows.append([])
    rows += [[note] for note in sheet["notes"]]
    widest = max(len(table["head"]) for table in sheet["tables"])
    charts = []
    kind, title, index, heads = CHARTS[key]
    table = sheet["tables"][index]
    names = [str(cell) for cell in table["head"]]
    if table["rows"] and all(head in names for head in heads):
        first, last = starts[index] + 1, starts[index] + len(table["rows"])
        series = [(head, first, last, len(names) - 1 - names[::-1].index(head)) for head in heads]
        charts.append(xlsx.Chart(kind=kind, title=title, categories=(first, last, 0), series=series,
                                 anchor=(widest + 1, 3)))
    return xlsx.Sheet(name=xlsx.safe_sheet_name(sheet["title"]), rows=rows, widths=[24] + [14] * (widest - 1),
                      charts=charts)


def subtitle(r, now):
    return (f"{r.date_from:%d/%m/%Y} to {r.date_to:%d/%m/%Y} · {port_label(r)} · "
            f"made {timezone.localtime(now):%d/%m/%Y %H:%M}")


def workbook(profile, r, now):
    """The management workbook (.xlsx bytes): ten sheets, each with its tables, notes and one chart."""
    line = subtitle(r, now)
    return xlsx.build([_layout(key, sheet, line) for key, sheet in data(profile, r, now).items()])

"""Analysis reports and Report charts (one response for both, so they always agree): every visit in scope counts
once (Planned, Working and Completed), filtered by port / terminal / berth / report date / shipping line."""

from sheet.errors import BadRequest
from sheet.listing import date_param

from .access import scoped_terminals, scoped_visits
from .figures import average, figures, report_date

DAYS_PER_MONTH = 30.44
DAYS_PER_YEAR = 365.25


def _row(name, rows):
    numbers = [n for _, n in rows]
    visits = [v for v, _ in rows]
    return {
        "name": name,
        "calls": len(rows),
        "waiting": average(n["waiting"] for n in numbers),
        "operation": average(n["operation"] for n in numbers),
        "port_stay": average(n["port_stay"] for n in numbers),
        "loa": average(float(v.loa) if v.loa is not None else None for v in visits),
        "cranes": average(v.cranes for v in visits),
        "productivity": average(n["productivity"] for n in numbers),
        "total_moves": sum(n["total_moves"] or 0 for n in numbers),
        "berthed": sum(1 for v in visits if v.atb),
    }


def _per(calls, days, length):
    return round(calls / (days / length), 1)


def response(profile, params):
    date_from, date_to = date_param(params, "from"), date_param(params, "to")
    if date_from and date_to and date_from > date_to:
        raise BadRequest("From must be on or before To.")
    port = params.get("port") or None
    terminals = scoped_terminals(profile, port)
    visits = scoped_visits(profile, port)
    terminal = (params.get("terminal") or "").strip()
    if terminal:
        if not terminal.isdigit():
            raise BadRequest("Unknown terminal.")
        terminals = terminals.filter(pk=int(terminal))
        visits = visits.filter(terminal_id=int(terminal))
    line_choices = sorted(set(visits.values_list("shipping_line", flat=True)))
    berth = (params.get("berth") or "").strip()
    line = (params.get("line") or "").strip()
    rows = []
    for visit in visits.order_by("id"):
        day = report_date(visit)
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        if berth and (visit.actual_berth or visit.planned_berth) != berth:
            continue
        if line and visit.shipping_line != line:
            continue
        rows.append((visit, figures(visit)))
    headline = _row("", rows)
    days = (date_to - date_from).days + 1 if date_from and date_to else None
    by_line = {}
    for row in rows:
        by_line.setdefault(row[0].shipping_line, []).append(row)
    berth_choices = []
    for item in terminals:
        berth_choices += [b for b in item.berths if b not in berth_choices]
    return {
        "headline": {key: headline[key] for key in ("calls", "waiting", "operation", "port_stay", "productivity")}
        | {"per_week": _per(len(rows), days, 7) if days else None,
           "per_month": _per(len(rows), days, DAYS_PER_MONTH) if days else None,
           "per_year": _per(len(rows), days, DAYS_PER_YEAR) if days else None},
        "terminals": [_row(t.name, [r for r in rows if r[0].terminal_id == t.id]) for t in terminals],
        "lines": sorted((_row(name, items) for name, items in by_line.items()), key=lambda r: (-r["calls"], r["name"])),
        "line_choices": line_choices,
        "berth_choices": berth_choices,
    }

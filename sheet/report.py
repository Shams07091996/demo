"""The management workbook's tables, for a date range and port: one source for each figure, no new money maths.

Money comes from the Calculations rows (calculations.rows_for: services, hotel stays, transfers, garbage & sludge),
so the Summary equals the Calculations page's totals. Counts follow the Dashboard (a Crew Change is one service and
one job; arrival and sailing are one job each). Every table is {"head", "rows", "total"}; a sheet is
{"title", "tables", "notes"}. Plain values only: xlsx turns floats into money cells and ints into counts.
"""

from dataclasses import dataclass
from datetime import date

from . import calculations
from . import dashboard as dashboard_figures
from .access import scoped_vessels
from .constants import PORT_LABELS, PORTS, SERVICE_TYPES

NO_LINE, NO_AGENT_LABEL = "(no line)", "(no agent)"
MONEY_HEAD = ["Revenue (EGP)", "Cost (EGP)", "Profit (EGP)"]
KIND_NAMES = {"Hotel stay": "Hotels", "Transfer": "Transport"}
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


def _summary(vessels, money, rows):
    groups = _grouped(vessels, money, lambda v: v["port"])
    table = _table(["Port", "Vessels", "Services", *MONEY_HEAD],
                   [groups[key].row(label) for key, label in PORTS if key in groups],
                   ["Total", len(vessels), sum(v["services_count"] for v in vessels), *_totals(rows)])
    notes = ["Money includes hotels, transport and garbage & sludge."]
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


def _by_line(vessels, money):
    lines = _grouped(vessels, money, lambda v: v["opr"] or NO_LINE)
    order = sorted(lines, key=lambda name: (-lines[name].revenue, name.casefold()))
    first = _table(["Line", "Vessels", "Services", *MONEY_HEAD], [lines[name].row(name) for name in order])
    pairs = _grouped(vessels, money, lambda v: (v["opr"] or NO_LINE, v["port"]))
    second = _table(["Line", "Port", "Vessels", "Services", *MONEY_HEAD],
                    [pairs[(name, key)].row(name, label) for name in order for key, label in PORTS
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


def _vessels(profile, r):
    """(Vessel queryset, plain vessel dicts) in the range and scope."""
    queryset = scoped_vessels(profile, r.port, prefetch=False).filter(date__gte=r.date_from, date__lte=r.date_to)
    plain = [{"id": v.id, "port": v.port, "opr": v.opr, "date": v.date.isoformat(),
              "services_count": len(v.services.all())} for v in queryset.prefetch_related("services")]
    return queryset, plain


def data(profile, r):
    """Every sheet's tables, keyed: summary, months, lines, services, ports_perf, closures, agents, crew, disposal."""
    queryset, vessels = _vessels(profile, r)
    rows = calculations.rows_for(queryset)
    money = {v["id"]: (0.0, 0.0, 0.0) for v in vessels} | _money_by_vessel(rows)
    return {
        "summary": _summary(vessels, money, rows),
        "months": _by_month(vessels, money, rows, r),
        "lines": _by_line(vessels, money),
        "services": _by_service(rows),
        "ports_perf": _sheet("Port performance", []),
        "closures": _sheet("Port closures", []),
        "agents": _agents(profile, r),
        "crew": _sheet("Crew", []),
        "disposal": _sheet("Garbage & Sludge", []),
    }


def port_label(r):
    return PORT_LABELS.get(r.port, "All ports") if r.port else "All ports"

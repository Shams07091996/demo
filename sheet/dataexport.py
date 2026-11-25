"""Each page's table as an Excel file with the page look: Vessels, Hotels, Transport, Port closures, Garbage & Sludge,
Calculations and Services, plus the All data file (five of them, one sheet each).

The columns are the page's table (`COLUMNS`: the same headings in the same order, kept equal to the front end's by
`tests_page_excel`), shown or left out by the same rule as on the page ("port" only for people with several ports,
"money.edit" only with that permission, "completed" only when Completed is ticked); no ids or other columns the page
does not show. A page cell holding two amounts (Garbage & Sludge's LE and USD) becomes two columns (`SPLIT`).
Values are typed (numbers, real Excel dates, statuses coloured like the page's pills), "—" is an empty cell, and the
page's totals are the last row where the page shows totals. Each sheet takes exactly the rows its page shows for the
same query (the page's own filter functions, without paging), so port users get only their port.
"""

from datetime import date, datetime

from . import calculations, closures, disposal, listing, logistics, moneyaccess, ports, services, xlsx
from .constants import BILLING, SERVICE_STATUSES

TITLES = {"vessels": "Vessels", "hotels": "Hotels", "transfers": "Transport", "closures": "Port closures",
          "disposal": "Garbage & Sludge", "calculations": "Calculations", "services": "Services"}
PAGES = tuple(TITLES)
ALL_PAGES = ("hotels", "transfers", "closures", "disposal", "calculations")  # the All data file's sheets, in order
# The page (constants.PAGES) each export belongs to: a person exports only pages they have.
EXPORT_PAGE = {"vessels": "vessels", "hotels": "hotels", "transfers": "transport", "closures": "closures",
               "disposal": "disposal", "calculations": "calculations", "services": "services"}

# (heading, rule): rule None = always; "port" = people with several ports; "money.edit" = that permission;
# "completed" = Completed ticked in the status filter (Services). The headings are the page's.
COLUMNS = {
    "vessels": [("Vessel", None), ("OPR", None), ("POC", None), ("Arrival agent", None), ("Sailing agent", None),
                ("Port", "port"), ("Date", None), ("Services", None)],
    "hotels": [("Check-in", None), ("Nights", None), ("Check-out", None), ("Hotel", None), ("Guests", None),
               ("Nationality", None), ("Vessel", None), ("Cost/night", "money.edit"), ("Revenue/night", "money.edit")],
    "transfers": [("Date & time", None), ("From → To", None), ("Guests", None), ("Flight", None), ("Vessel", None),
                  ("Cost", "money.edit"), ("Revenue", "money.edit")],
    "closures": [("Port", "port"), ("Closed from", None), ("Reopened", None), ("Hours", None), ("Reason", None),
                 ("Notes", None)],
    "disposal": [("Date", None), ("Vessel", None), ("OPR", None), ("Port", "port"), ("Garbage m³", None),
                 ("Sludge t", None), ("Revenue", "money.edit"), ("Cost", "money.edit"), ("Profit", "money.edit")],
    "calculations": [("Date", None), ("Vessel", None), ("OPR", None), ("Port", "port"), ("Item", None),
                     ("Cost", None), ("Revenue", None), ("Profit LE", None), ("Status", None), ("Billing party", None),
                     ("Billing", None), ("Accounting", None)],
    "services": [("Vessel", None), ("Date", None), ("Service", None), ("Agent", None), ("Status", None),
                 ("Completed", "completed"), ("Missing", None)],
}
# A page column whose cell shows two amounts: the file's columns for it.
SPLIT = {("disposal", "Revenue"): ("Revenue LE", "Revenue USD"), ("disposal", "Cost"): ("Cost LE", "Cost USD"),
         ("disposal", "Profit"): ("Profit LE", "Profit USD")}

SERVICE_TONES = {"in_progress": "progress", "completed": "done", "cancelled": "cancel"}


def all_pages_for(profile):
    """The All data file's sheets this person may have."""
    return [page for page in ALL_PAGES if profile.sees(EXPORT_PAGE[page])]


def _day(iso):
    return xlsx.Day(date.fromisoformat(iso)) if iso else None


def _moment(iso):
    return xlsx.Moment(datetime.fromisoformat(iso)) if iso else None


def _text(value):
    """A page's text, "—" / nothing as an empty cell."""
    return value if value not in (None, "", "—") else None


def _price(amount, currency):
    return xlsx.Price(float(amount), currency) if amount is not None else None


def _status(key):
    return xlsx.Status(SERVICE_STATUSES[key], SERVICE_TONES[key]) if key in SERVICE_STATUSES else None


def _accounting(closed, ref=True):
    if not ref:
        return None
    return xlsx.Status("Closed", "done") if closed else xlsx.Status("Open", "info")


def _guests(row):
    return "\n".join(f"{g['name']} ({g['rank']})" if g["rank"] else g["name"] for g in row["guests"]) or None


def _unique(row, key):
    return ", ".join(dict.fromkeys(g[key] for g in row["guests"] if g[key])) or None


def _booking_vessel(row):
    words = [row["vessel"]["name"]]
    if row.get("draft"):
        words.append("To complete")
    if row.get("cancelled"):
        words.append("Cancelled")
    if row.get("closed"):
        words.append("Closed")
    return " · ".join(words)


def _vessels(profile, params):
    filters = listing.parse_filters(params, paged=False)
    moneyaccess.require_sort(profile, filters.sort)
    rows = []
    for v in listing.matching(listing.range_rows(profile, filters), filters):
        rows.append([v["name"], _text(v["opr"]), _text(v["poc"]), _text(v["arrival_agent"]), _text(v["sailing_agent"]),
                     ports.label(v["port"]), _day(v["date"]),
                     ", ".join(_service_tag(s) for s in v["services"]) or None])
    return rows, None


def _service_tag(service):
    if service["type"] != "Crew Change":
        return service["type"]
    data = service.get("data") or {}
    return f"Crew Change ({len(data.get('onSigners') or [])} on / {len(data.get('offSigners') or [])} off)"


def _hotels(profile, params):
    _p, pairs = logistics.filtered("hotels", profile, params)
    rows = [[_day(r["check_in"]), r["nights"], _day(r["check_out"]), r["hotel"], _guests(r),
             _unique(r, "nationality"), _booking_vessel(r), _price(r.get("cost_per_night"), r.get("cost_currency")),
             _price(r.get("revenue_per_night"), r.get("revenue_currency"))]
            for r, _stay in pairs]
    return rows, None


def _transfers(profile, params):
    _p, pairs = logistics.filtered("transfers", profile, params)
    rows = []
    for r, trip in pairs:
        route = f"{logistics._place(trip, trip.from_place)} → {logistics._place(trip, trip.to_place)}"
        rows.append([_moment(r["at"]), route, _guests(r), _unique(r, "flight"), _booking_vessel(r),
                     _price(r.get("cost"), r.get("cost_currency")),
                     _price(r.get("revenue"), r.get("revenue_currency"))])
    return rows, None


def _closures(profile, params):
    rows = []
    for c in closures.filtered(profile, params):
        hours = round((c.end_at - c.start_at).total_seconds() / 3600, 1) if c.end_at else None
        reopened = xlsx.Moment(c.end_at) if c.end_at else "Still closed"
        rows.append([ports.label(c.port), xlsx.Moment(c.start_at), reopened,
                     xlsx.Hours(hours), c.reason, _text(c.notes)])
    return rows, None


def _le(value):
    return xlsx.Price(value, "LE") if value is not None else None


def _usd(value):
    return xlsx.Price(value, "USD") if value is not None else None


def _disposal(profile, params):
    found = disposal.response(profile, params)
    rows = []
    for r in found["rows"]:
        v = r["vessel"]
        rows.append([_day(v["date"]), v["name"], _text(v["opr"]), v["port_label"],
                     None if r["hidden"] else r["garbage"], None if r["hidden"] else r["sludge"],
                     _le(r.get("revenue_egp")), _usd(r.get("revenue_usd")), _le(r.get("cost_egp")),
                     _usd(r.get("cost_usd")), _le(r.get("profit_egp")), _usd(r.get("profit_usd"))])
    t = found.get("totals")
    total = None
    if t:
        total = ["Total", None, None, None, None, None, _le(t["revenue_egp"]), _usd(t["revenue_usd"]),
                 _le(t["cost_egp"]), _usd(t["cost_usd"]), _le(t["profit_egp"]), _usd(t["profit_usd"])]
    return rows, total


def _item(row):
    lines = [row["label"]]
    if row["price_missing"]:
        lines.append("No price for this port and month")
    if row["note"]:
        lines.append(row["note"])
    return "\n".join(lines)


def _calculations(profile, params):
    _p, found, _oprs, _parties = calculations.filtered(profile, params)
    rows = []
    cost = revenue = profit = 0.0
    for r in found:
        v = r["vessel"]
        status = _status(r["status"])
        if status and r["cancel_reason"]:
            status = xlsx.Status(f"{status.text}\n{r['cancel_reason']}", status.tone)
        rows.append([_day(v["date"]), v["name"], _text(v["opr"]), ports.label(v["port"]), _item(r),
                     _le(r["cost_egp"]), _le(r["revenue_egp"]), _le(r["profit_egp"]), status,
                     (r["billing_party"] or {}).get("name") or None, BILLING.get(r["billing"]) or None,
                     _accounting(r["closed"], r["ref"])])
        cost, revenue, profit = cost + r["cost_egp"], revenue + r["revenue_egp"], profit + r["profit_egp"]
    total = ["Total", None, None, None, f"{len(found)} line{'' if len(found) == 1 else 's'}", _le(round(cost, 2)),
             _le(round(revenue, 2)), _le(round(profit, 2)), None, None, None, None]
    return rows, total


def _services(profile, params):
    found, _agents = services.filtered(profile, params)
    rows = []
    for r in found:
        v = r["vessel"]
        status = _status(r["status"])
        if status and r["sailed"]:
            status = xlsx.Status(f"{status.text} · Sailed", status.tone)
        if r["completed_at"]:
            completed = _moment(r["completed_at"])
        else:
            completed = f"≈ {date.fromisoformat(v['date']).strftime('%d/%m/%Y')}" if r["completed_guess"] else None
        rows.append([v["name"], _day(v["date"]), r["type"], _text(r["agent"]), status, completed,
                     ", ".join(r["missing"]) or None])
    return rows, None


BUILDERS = {"vessels": _vessels, "hotels": _hotels, "transfers": _transfers, "closures": _closures,
            "disposal": _disposal, "calculations": _calculations, "services": _services}


def _shown(page, rule, profile, params):
    if rule == "port":
        return profile.is_admin or len(profile.ports) > 1
    if rule == "completed":
        return "completed" in services._statuses(params)
    if rule:
        return profile.can(rule)
    return True


def headings(page):
    """The file's headings for every column of the page (two-amount cells split), in order."""
    return [h for heading, _rule in COLUMNS[page] for h in SPLIT.get((page, heading), (heading,))]


def filters_line(profile, params):
    """The filters the file was made with, in words (always some text: the line under the title)."""
    words = []
    date_from, date_to = listing.date_param(params, "from"), listing.date_param(params, "to")
    if date_from or date_to:
        words.append(" – ".join(d.strftime("%d/%m/%Y") if d else "…" for d in (date_from, date_to)))
    port = params.get("port") or ""
    if port and port != "ALL":
        words.append(ports.label(port))
    elif profile.is_admin:
        words.append("All ports")
    else:
        words.append(", ".join(ports.label(key) for key in profile.ports))
    if params.get("q"):
        words.append(f"Search: {params['q'][:100]}")
    return " · ".join(words)


def sheet(page, profile, params):
    """One page's table (its list query, every page of it) as an xlsx.Sheet with the page look."""
    rows, total = BUILDERS[page](profile, params)
    keep = []
    for heading, rule in COLUMNS[page]:
        width = len(SPLIT.get((page, heading), (heading,)))
        keep.extend([_shown(page, rule, profile, params)] * width)
    head = [h for h, shown in zip(headings(page), keep, strict=True) if shown]

    def pick(row):
        return [value for value, shown in zip(row, keep, strict=True) if shown]

    return xlsx.table_sheet(TITLES[page], TITLES[page], filters_line(profile, params), head,
                            [pick(row) for row in rows], total=pick(total) if total else None)


def page_file(page, profile, params):
    return xlsx.build([sheet(page, profile, params)])


def all_file(profile, date_from, date_to, port):
    """The five pages for one From–To range and port, one sheet each (each page reads the range its own way)."""
    params = {"from": date_from.isoformat(), "to": date_to.isoformat(), "port": port or ""}
    return xlsx.build([sheet(page, profile, params) for page in all_pages_for(profile)])

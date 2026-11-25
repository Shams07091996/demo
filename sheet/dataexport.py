"""Plain-table Excel files of six pages, for other programs: Hotels, Transport, Port closures, Garbage & Sludge,
Calculations and Services (the last is not in the All data file). One header row (always the same columns) and one
row per record; numbers as numbers, dates as real Excel dates; no titles, totals or notes (that is the management
workbook, report.py).

Each sheet takes exactly the rows its page shows for the same query (the page's own filter functions, without
paging), so port users get only their port. `all_file` puts the five in one workbook for a From–To range.
"""

from datetime import date, datetime

from . import calculations, closures, disposal, logistics, moneyaccess, ports, services, xlsx
from .constants import BILLING, SERVICE_STATUSES

TITLES = {"hotels": "Hotels", "transfers": "Transport", "closures": "Port closures", "disposal": "Garbage & Sludge",
          "calculations": "Calculations", "services": "Services"}
PAGES = tuple(TITLES)
ALL_PAGES = PAGES[:5]  # the All data file's sheets, in order (the Services list is exported from its page only)
# The page (constants.PAGES) each export belongs to: a person exports only pages they have.
EXPORT_PAGE = {"hotels": "hotels", "transfers": "transport", "closures": "closures", "disposal": "disposal",
               "calculations": "calculations", "services": "services"}


def all_pages_for(profile):
    """The All data file's sheets this person may have."""
    return [page for page in ALL_PAGES if profile.sees(EXPORT_PAGE[page])]


def _port(key):
    return ports.label(key)


def _num(value):
    return float(value) if value is not None else None


def _accounting(closed):
    return "Closed" if closed else "Open"


def _guests(booking):
    return "; ".join(g.name for g in booking.guests.all())


def _hotels(profile, params):
    head = ["Booking id", "Vessel id", "Vessel", "Port", "Guests", "Hotel", "Check-in", "Nights", "Check-out",
            "Cost per night", "Cost currency", "Revenue per night", "Revenue currency", "Exchange rate", "Draft",
            "Cancelled", "Accounting"]
    _p, pairs = logistics.filtered("hotels", profile, params)
    rows = [[s.id, s.vessel_id, s.vessel.name, _port(s.vessel.port), _guests(s), s.hotel, xlsx.Day(s.check_in),
             s.nights, xlsx.Day(s.check_out), _num(s.cost_per_night), s.cost_currency, _num(s.revenue_per_night),
             s.revenue_currency, _num(s.exchange_rate), s.draft, s.cancelled, _accounting(s.acct_closed)]
            for _row, s in pairs]
    return head, rows


def _transfers(profile, params):
    head = ["Booking id", "Vessel id", "Vessel", "Port", "Guests", "From", "To", "Airport", "Hotel", "Port name",
            "Date & time", "Cost", "Cost currency", "Revenue", "Revenue currency", "Exchange rate", "Draft",
            "Cancelled", "Accounting"]
    _p, pairs = logistics.filtered("transfers", profile, params)
    rows = [[t.id, t.vessel_id, t.vessel.name, _port(t.vessel.port), _guests(t), logistics._place(t, t.from_place),
             logistics._place(t, t.to_place), t.airport, t.hotel, t.port_name, xlsx.Moment(t.at), _num(t.cost),
             t.cost_currency, _num(t.revenue), t.revenue_currency, _num(t.exchange_rate), t.draft, t.cancelled,
             _accounting(t.acct_closed)]
            for _row, t in pairs]
    return head, rows


def _closures(profile, params):
    head = ["Closure id", "Port", "Closed from", "Reopened", "Hours", "Reason", "Notes"]
    rows = []
    for c in closures.filtered(profile, params):
        hours = round((c.end_at - c.start_at).total_seconds() / 3600, 1) if c.end_at else None
        rows.append([c.id, _port(c.port), xlsx.Moment(c.start_at), xlsx.Moment(c.end_at), hours, c.reason, c.notes])
    return head, rows


def _disposal(profile, params):
    head = ["Vessel id", "Vessel", "Date", "OPR", "Port", "Garbage m³", "Sludge t", "Hidden", "Revenue EGP",
            "Cost EGP", "Profit EGP", "Revenue USD", "Cost USD", "Profit USD", "Rate missing", "Price missing",
            "Accounting"]
    rows = []
    for r in disposal.response(profile, params)["rows"]:
        v = r["vessel"]
        rows.append([v["id"], v["name"], xlsx.Day(date.fromisoformat(v["date"])), v["opr"], v["port_label"],
                     r["garbage"], r["sludge"], r["hidden"], r["revenue_egp"], r["cost_egp"], r["profit_egp"],
                     r["revenue_usd"], r["cost_usd"], r["profit_usd"], r["rate_missing"], r["price_missing"],
                     _accounting(r["closed"])])
    return head, rows


def _side(side):
    return (side["amount"], side["currency"]) if side else (None, None)


def _calculations(profile, params):
    head = ["Vessel id", "Vessel", "Vessel date", "OPR", "Port", "Item", "Line", "Note", "Record", "Record id",
            "Cost", "Cost currency", "Revenue", "Revenue currency", "Cost EGP", "Revenue EGP", "Profit EGP",
            "Cost USD", "Revenue USD", "Profit USD", "Rate source", "Rate missing", "Price missing", "Status",
            "Cancellation reason", "Accounting", "Billing party", "Billing"]
    _p, found, _oprs, _parties = calculations.filtered(profile, params)
    rows = []
    for r in found:
        v, ref = r["vessel"], r["ref"] or {}
        cost, revenue = _side(r["cost"]), _side(r["revenue"])
        rows.append([v["id"], v["name"], xlsx.Day(date.fromisoformat(v["date"])), v["opr"], _port(v["port"]),
                     r["kind"], r["label"], r["note"], ref.get("kind"), ref.get("id"), *cost, *revenue,
                     round(r["cost_egp"], 2), round(r["revenue_egp"], 2), round(r["profit_egp"], 2),
                     r["cost_usd"], r["revenue_usd"], r["profit_usd"], r["rate_source"], r["rate_missing"],
                     r["price_missing"], SERVICE_STATUSES.get(r["status"], ""), r["cancel_reason"],
                     _accounting(r["closed"]), (r["billing_party"] or {}).get("name", ""),
                     BILLING.get(r["billing"], "")])
    return head, rows


def _services(profile, params):
    head = ["Service id", "Vessel id", "Vessel", "Port", "Vessel date", "Service", "Agent", "Status",
            "Cancellation reason", "Completed", "Sailed", "Missing", "Billing party", "Billing"]
    found, _agents = services.filtered(profile, params)
    rows = []
    for r in found:
        v = r["vessel"]
        vessel_day = date.fromisoformat(v["date"])
        if r["completed_at"]:
            completed = xlsx.Moment(datetime.fromisoformat(r["completed_at"]))
        else:
            completed = xlsx.Day(vessel_day if r["completed_guess"] else None)  # completed before it was tracked
        rows.append([r["id"], v["id"], v["name"], _port(v["port"]), xlsx.Day(vessel_day), r["type"], r["agent"],
                     SERVICE_STATUSES.get(r["status"], ""), r["cancel_reason"], completed,
                     "Yes" if r["sailed"] else "No", ", ".join(r["missing"]),
                     (r["billing_party"] or {}).get("name", ""), BILLING.get(r["billing"], "")])
    return head, rows


BUILDERS = {"hotels": _hotels, "transfers": _transfers, "closures": _closures, "disposal": _disposal,
            "calculations": _calculations, "services": _services}


def _plain(value):
    """Numbers (ids, money, rates, quantities, hours) shown exactly as stored: a CSV saved from Excel keeps them."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return xlsx.Number(value)
    return value


def sheet(page, profile, params):
    """One page's rows (its list query, all pages of it) as an xlsx.Sheet: header row, then one row per record."""
    head, rows = moneyaccess.drop_columns(*BUILDERS[page](profile, params), profile)  # money columns: money.view
    rows = [[_plain(value) for value in row] for row in rows]
    return xlsx.Sheet(TITLES[page], [head, *rows], widths=[16] * len(head))


def page_file(page, profile, params):
    return xlsx.build([sheet(page, profile, params)])


def all_file(profile, date_from, date_to, port):
    """The five pages for one From–To range and port, one sheet each (each page reads the range its own way)."""
    params = {"from": date_from.isoformat(), "to": date_to.isoformat(), "port": port or ""}
    return xlsx.build([sheet(page, profile, params) for page in all_pages_for(profile)])

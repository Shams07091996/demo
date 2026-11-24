"""The Calculations page: every money line — services (one per multi-service entry), hotel stays and transfers — of
the vessels in a date range (on the vessel date), OPR and port, with totals. Each row also carries its service's
operations status and its accounting state (Open / Closed, with `ref` naming what /api/accounting/ closes); both
narrow the rows and the totals. Worked out on each request from the same
maths as the vessel figures (finance.service_lines / logistics.booking_line), so the two can never disagree.
"""

from dataclasses import dataclass
from datetime import date

from . import disposal
from .access import scoped_vessels
from .constants import SERVICE_STATUSES
from .errors import BadRequest
from .finance import service_lines
from .listing import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, date_param, int_param
from .logistics import booking_line
from .models import VesselDisposal
from .serializers import month_rates

SORT_KEYS = {
    "date": lambda r: r["vessel"]["date"],
    "vessel": lambda r: r["vessel"]["name"].casefold(),
    "opr": lambda r: r["vessel"]["opr"].casefold(),
    "kind": lambda r: r["kind"].casefold(),
    "cost": lambda r: r["cost_egp"],
    "revenue": lambda r: r["revenue_egp"],
    "profit": lambda r: r["profit_egp"],
}


@dataclass
class Params:
    date_from: date | None
    date_to: date | None
    opr: str | None
    port: str | None
    sort: str
    desc: bool
    page: int
    page_size: int
    statuses: set | None = None    # only rows of services with one of these statuses (bookings / disposal left out)
    accounting: set | None = None  # only rows that are "open" / "closed"


ACCOUNTING = ("open", "closed")


def _choice_list(params, key, allowed, message):
    """A comma list of allowed values (empty items ignored); None when absent or empty; anything unknown refused."""
    items = {item.strip() for item in (params.get(key) or "").split(",") if item.strip()}
    if items - set(allowed):
        raise BadRequest(message)
    return items or None


def parse_params(params):
    p = Params(
        date_from=date_param(params, "from"),
        date_to=date_param(params, "to"),
        opr=params.get("opr") or None,
        port=params.get("port") or None,
        sort=params.get("sort") or "date",
        desc=True,
        page=int_param(params, "page", 1, 1, 10**9, "Page must be a whole number from 1."),
        page_size=int_param(params, "page_size", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE, "Rows per page must be 1–200."),
        statuses=_choice_list(params, "status", SERVICE_STATUSES, "Unknown status."),
        accounting=_choice_list(params, "accounting", ACCOUNTING, "Unknown accounting status."),
    )
    if p.date_from and p.date_to and p.date_from > p.date_to:
        raise BadRequest("From must be on or before To.")
    if p.sort not in SORT_KEYS:
        raise BadRequest("Unknown sort.")
    direction = params.get("dir") or "desc"
    if direction not in ("asc", "desc"):
        raise BadRequest("Unknown sort.")
    p.desc = direction == "desc"
    return p


def _rounded_side(side):
    if not side:
        return None
    return {**side, "amount": round(side["amount"], 2), "egp": round(side["egp"], 2)}


def _usd(item):
    """(cost, revenue, profit) in USD: a Garbage & Sludge line brings its own; otherwise when every side of the line is
    in USD, else None."""
    if "usd" in item:
        return item["usd"]
    sides = [side for side in (item["cost"], item["revenue"]) if side]
    if not sides or any(side["currency"] != "USD" for side in sides):
        return None
    cost, revenue = (round(side["amount"] * side["times"], 2) if side else 0.0
                     for side in (item["cost"], item["revenue"]))
    return cost, revenue, round(revenue - cost, 2)


def _state(obj, kind, status=None, reason=""):
    """What a row says about its thing: operations status (services only), accounting state and what closes it."""
    if obj is None:  # garbage & sludge with nothing entered yet: nothing to close
        return {"status": None, "cancel_reason": "", "closed": False, "ref": None}
    return {"status": status, "cancel_reason": reason, "closed": obj.acct_closed, "ref": {"kind": kind, "id": obj.id}}


def _row(vessel, kind, item, state):
    usd = _usd(item)
    return {
        "vessel": {"id": vessel.id, "name": vessel.name, "date": vessel.date.isoformat(), "opr": vessel.opr,
                   "port": vessel.port},
        "kind": kind,
        "label": item["label"],
        "note": item["note"],
        "cost": _rounded_side(item["cost"]),
        "revenue": _rounded_side(item["revenue"]),
        "cost_egp": item["cost_egp"],
        "revenue_egp": item["revenue_egp"],
        "profit_egp": item["profit_egp"],
        "cost_usd": usd[0] if usd else None,
        "revenue_usd": usd[1] if usd else None,
        "profit_usd": usd[2] if usd else None,
        "rate_source": item["rate_source"],
        "rate_missing": item["rate_missing"],
        "price_missing": item.get("price_missing", False),
        **state,
    }


def _vessel_rows(vessel, rate, price):
    """One vessel's lines: its services in order, its garbage and sludge, then its hotel stays, then its transfers."""
    rows = []
    for service in vessel.services.all():
        lines = service_lines(service.service_type, service.data, rate)
        state = _state(service, "service", service.status, service.cancel_reason)
        rows += [_row(vessel, service.service_type, item, state) for item in lines]
    try:
        record = vessel.disposal
    except VesselDisposal.DoesNotExist:
        record = None
    state = _state(record, "disposal")
    rows += [_row(vessel, "Garbage & Sludge", item, state) for item in disposal.calculation_lines(vessel, rate, price)]
    for kind, ref, label, bookings in (("hotels", "hotel", "Hotel stay", vessel.hotel_stays.all()),
                                       ("transfers", "transfer", "Transfer", vessel.transfers.all())):
        for booking in bookings:
            item = booking_line(kind, booking, rate)
            if item["cost"] or item["revenue"]:
                status = "cancelled" if booking.cancelled else None
                rows.append(_row(vessel, label, item, _state(booking, ref, status)))
    return rows


def rows_for(vessels):
    """Every money line of these vessels (a Vessel queryset), newest vessel first, lines in order. Also feeds the
    management workbook, so its money always equals this page's."""
    vessels = vessels.prefetch_related("services", "hotel_stays", "transfers").select_related("disposal")
    rates, prices = month_rates(), disposal.prices_map()
    rows = []
    for vessel in vessels.order_by("-date", "-id"):
        month = (vessel.date.year, vessel.date.month)
        rows += _vessel_rows(vessel, rates.get(month), prices.get((*month, vessel.port)))
    return rows


def filtered(profile, params):
    """(params, rows, oprs): every row the page's filters show, sorted, not paged (also the export)."""
    p = parse_params(params)
    vessels = scoped_vessels(profile, p.port, prefetch=False).prefetch_related("services", "hotel_stays", "transfers")
    vessels = vessels.select_related("disposal")
    if p.date_from:
        vessels = vessels.filter(date__gte=p.date_from)
    if p.date_to:
        vessels = vessels.filter(date__lte=p.date_to)
    # The OPR dropdown offers the OPRs that actually occur in this range and scope (not narrowed by the OPR filter).
    oprs = sorted(set(vessels.exclude(opr="").values_list("opr", flat=True)), key=str.casefold)
    if p.opr is not None:
        vessels = vessels.filter(opr=p.opr)
    rows = rows_for(vessels)
    if p.statuses is not None:
        rows = [r for r in rows if r["status"] in p.statuses]
    if p.accounting is not None:
        rows = [r for r in rows if ("closed" if r["closed"] else "open") in p.accounting]
    rows.sort(key=SORT_KEYS[p.sort], reverse=p.desc)  # stable: ties keep newest vessel first, lines in order
    return p, rows, oprs


def response(profile, params):
    p, rows, oprs = filtered(profile, params)
    totals = {
        "revenue_egp": round(sum(r["revenue_egp"] for r in rows), 2),
        "cost_egp": round(sum(r["cost_egp"] for r in rows), 2),
        "profit_egp": round(sum(r["profit_egp"] for r in rows), 2),
        "lines": len(rows),
        "rate_missing_lines": sum(1 for r in rows if r["rate_missing"]),
        "price_missing_lines": sum(1 for r in rows if r["price_missing"]),
        "open": sum(1 for r in rows if not r["closed"]),
        "closed": sum(1 for r in rows if r["closed"]),
        # USD totals of the lines that are wholly in USD (the EGP totals above cover every line).
        **{f"{key}_usd": round(sum(r[f"{key}_usd"] for r in rows if r[f"{key}_usd"] is not None), 2)
           for key in ("cost", "revenue", "profit")},
    }
    start = (p.page - 1) * p.page_size
    page_rows = [
        {**r, **{key: round(r[key], 2) for key in ("cost_egp", "revenue_egp", "profit_egp")}}
        for r in rows[start : start + p.page_size]
    ]
    return {
        "rows": page_rows,
        "page": p.page,
        "page_size": p.page_size,
        "count": len(rows),
        "pages": max(1, -(-len(rows) // p.page_size)),
        "totals": totals,
        "oprs": oprs,
    }

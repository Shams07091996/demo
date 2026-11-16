"""The Calculations page: every money line — services (one per multi-service entry), hotel stays and transfers — of
the vessels in a date range (on the vessel date), OPR and port, with totals. Worked out on each request from the same
maths as the vessel figures (finance.service_lines / logistics.booking_line), so the two can never disagree.
"""

from dataclasses import dataclass
from datetime import date

from .access import scoped_vessels
from .errors import BadRequest
from .finance import service_lines
from .listing import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, date_param, int_param
from .logistics import booking_line
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


def _row(vessel, kind, item):
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
        "rate_source": item["rate_source"],
        "rate_missing": item["rate_missing"],
    }


def _vessel_rows(vessel, rate):
    """One vessel's lines: its services in order, then its hotel stays, then its transfers."""
    rows = []
    for service in vessel.services.all():
        lines = service_lines(service.service_type, service.data, rate)
        rows += [_row(vessel, service.service_type, item) for item in lines]
    for kind, label, bookings in (("hotels", "Hotel stay", vessel.hotel_stays.all()),
                                  ("transfers", "Transfer", vessel.transfers.all())):
        for booking in bookings:
            item = booking_line(kind, booking, rate)
            if item["cost"] or item["revenue"]:
                rows.append(_row(vessel, label, item))
    return rows


def response(profile, params):
    p = parse_params(params)
    vessels = scoped_vessels(profile, p.port, prefetch=False).prefetch_related("services", "hotel_stays", "transfers")
    if p.date_from:
        vessels = vessels.filter(date__gte=p.date_from)
    if p.date_to:
        vessels = vessels.filter(date__lte=p.date_to)
    # The OPR dropdown offers the OPRs that actually occur in this range and scope (not narrowed by the OPR filter).
    oprs = sorted(set(vessels.exclude(opr="").values_list("opr", flat=True)), key=str.casefold)
    if p.opr is not None:
        vessels = vessels.filter(opr=p.opr)
    rates = month_rates()
    rows = []
    for vessel in vessels.order_by("-date", "-id"):
        rows += _vessel_rows(vessel, rates.get((vessel.date.year, vessel.date.month)))
    rows.sort(key=SORT_KEYS[p.sort], reverse=p.desc)  # stable: ties keep newest vessel first, lines in order
    totals = {
        "revenue_egp": round(sum(r["revenue_egp"] for r in rows), 2),
        "cost_egp": round(sum(r["cost_egp"] for r in rows), 2),
        "profit_egp": round(sum(r["profit_egp"] for r in rows), 2),
        "lines": len(rows),
        "rate_missing_lines": sum(1 for r in rows if r["rate_missing"]),
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

"""The Dashboard's Money view: revenue, cost and profit of the Calculations lines (services, hotel stays, transfers,
garbage & sludge) of the vessels in the Dashboard's filters, by service, by customer and per month. Money comes only
from calculations.rows_for, so it always equals the Calculations page.

A line's customer: a service line's billing party, else (any other line, or a service without one) the vessel's
ship's customer, else "No customer". Filters: dates, port, OPR as on the Dashboard; `service` keeps lines of that kind
(a service type or one of EXTRA_KINDS); `agent` keeps service lines of that agent (others dropped); `customer` as the
Dashboard's (an id, or "__none__")."""

from . import calculations
from .access import scoped_vessels
from .constants import NO_AGENT, SERVICE_TYPES
from .dashboard import _months_between, parse
from .errors import BadRequest
from .models import Customer

EXTRA_KINDS = ("Hotel stay", "Transfer", "Garbage & Sludge")
KINDS = (*SERVICE_TYPES, *EXTRA_KINDS)
MONEY = ("revenue_egp", "cost_egp", "profit_egp")
_ORDER = {kind: i for i, kind in enumerate(KINDS)}


def _customer(row):
    party = row["billing_party"]
    return party["id"] if party else row["vessel"]["ship_customer_id"]


def _blank():
    return {**dict.fromkeys(MONEY, 0.0), "lines": 0}


def _add(entry, row):
    for key in MONEY:
        entry[key] += row[key]
    entry["lines"] += 1


def _rounded(entry):
    return {**entry, **{key: round(entry[key], 2) for key in MONEY}}


def response(profile, params):
    service = params.get("service") or None
    if service is not None and service not in KINDS:
        raise BadRequest("Unknown service type.")
    f = parse({key: params.get(key) for key in ("from", "to", "port", "opr", "agent", "customer") if params.get(key)})
    vessels = scoped_vessels(profile, f.port, prefetch=False)
    if f.date_from:
        vessels = vessels.filter(date__gte=f.date_from)
    if f.date_to:
        vessels = vessels.filter(date__lte=f.date_to)
    if f.opr is not None:
        vessels = vessels.filter(opr=f.opr)
    rows = calculations.rows_for(vessels)
    if service is not None:
        rows = [r for r in rows if r["kind"] == service]
    if f.agent is not None:
        rows = [r for r in rows if (r["ref"] or {}).get("kind") == "service" and r["agent"] == f.agent]
    if f.customer is not None:
        wanted = None if f.customer == NO_AGENT else f.customer
        rows = [r for r in rows if _customer(r) == wanted]

    totals, by_kind, by_customer, months = _blank(), {}, {}, {}
    for row in rows:
        _add(totals, row)
        _add(by_kind.setdefault(row["kind"], _blank()), row)
        _add(by_customer.setdefault(_customer(row), _blank()), row)
        _add(months.setdefault(row["vessel"]["date"][:7], _blank()), row)
    totals = {**_rounded(totals), "rate_missing_lines": sum(1 for r in rows if r["rate_missing"]),
              "price_missing_lines": sum(1 for r in rows if r["price_missing"])}

    names = dict(Customer.objects.filter(id__in=[k for k in by_customer if k is not None]).values_list("id", "name"))
    customers = [{"id": key, "name": names.get(key, "No customer") if key is not None else "No customer",
                  **_rounded(entry)} for key, entry in by_customer.items()]
    customers.sort(key=lambda c: (c["id"] is None, -c["revenue_egp"], c["name"].casefold()))

    month_list = []
    if months:
        keys = sorted(months)
        first, last = (tuple(int(x) for x in key.split("-")) for key in (keys[0], keys[-1]))
        month_list = [{"month": key, **_rounded(months.get(key) or _blank())} for key in _months_between(first, last)]
    return {
        "totals": totals,
        "by_service": [{"kind": kind, **_rounded(entry)}
                       for kind, entry in sorted(by_kind.items(), key=lambda item: _ORDER.get(item[0], len(KINDS)))],
        "by_customer": customers,
        "months": month_list,
        "kinds": list(KINDS),
    }

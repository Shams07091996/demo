"""The vessel list as the server serves it: date range, search, OPR bucket, sorting, paging and totals.

The database narrows by date range and port. Money can't be summed in SQL (each service has its own currency and
exchange rate), so every vessel in that range gets its figures computed once in Python; search, bucket, exact OPR,
sorting and paging then run on those dicts.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Prefetch, Q
from django.utils import timezone

from .access import scoped_vessels
from .constants import SERVICE_TYPES
from .errors import BadRequest
from .models import Service, Vessel
from .serializers import month_rates, vessel_to_dict

SORT_KEYS = ("name", "opr", "poc", "arrival_agent", "sailing_agent", "port", "date", "total_cost_egp")
BUCKETS = ("ALL", "ARK", "MSK", "OTH", "SERVICES")
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_QUERY = 100


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    q: str = ""
    bucket: str = "ALL"
    port: str | None = None
    opr: str | None = None
    sort: str = "date"
    desc: bool = True
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


def date_param(params, key):
    text = (params.get(key) or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise BadRequest("Enter dates as YYYY-MM-DD.") from None


def int_param(params, key, default, low, high, message):
    text = (params.get(key) or "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise BadRequest(message) from None
    if not low <= value <= high:
        raise BadRequest(message)
    return value


def parse_filters(params, *, paged=True):
    """Read the list filters from a query string (a QueryDict or any dict-like)."""
    f = Filters(date_from=date_param(params, "from"), date_to=date_param(params, "to"))
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise BadRequest("From must be on or before To.")
    f.q = (params.get("q") or "").strip()[:MAX_QUERY]
    f.bucket = (params.get("bucket") or "ALL").strip().upper()
    if f.bucket not in BUCKETS:
        raise BadRequest("Unknown filter.")
    f.port = params.get("port") or None
    f.opr = params.get("opr") if params.get("opr") not in (None, "") else None
    f.sort = params.get("sort") or "date"
    if f.sort not in SORT_KEYS:
        raise BadRequest("Unknown sort.")
    direction = params.get("dir") or "desc"
    if direction not in ("asc", "desc"):
        raise BadRequest("Unknown sort.")
    f.desc = direction == "desc"
    if paged:
        f.page = int_param(params, "page", 1, 1, 10**9, "Page must be a whole number from 1.")
        f.page_size = int_param(
            params, "page_size", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE, "Rows per page must be 1–200."
        )
    return f


def opr_bucket(opr):
    upper = (opr or "").strip().upper()
    return upper if upper in ("ARK", "MSK") else "OTH"


def _figures(vessels):
    rates = month_rates()
    return [vessel_to_dict(v, rates) for v in vessels]


def range_rows(profile, f):
    """Every vessel this profile may see in the date range and port, with figures, newest first."""
    queryset = scoped_vessels(profile, f.port)
    if f.date_from:
        queryset = queryset.filter(date__gte=f.date_from)
    if f.date_to:
        queryset = queryset.filter(date__lte=f.date_to)
    return _figures(queryset.order_by("-date", "-id"))


def _matches_query(row, needle):
    fields = [row["name"], row["opr"], row["poc"], row["arrival_agent"], row["sailing_agent"],
              row["delay_reason"]]
    fields += [part for s in row["services"] for part in (s["type"], s["agent"])]
    return any(needle in (field or "").casefold() for field in fields)


def _sort_key(key):
    if key == "total_cost_egp":
        return lambda row: row["total_cost_egp"]
    return lambda row: (row[key] or "").casefold()


def matching(rows, f):
    """Apply search, bucket and exact OPR, then sort. Ties keep the incoming newest-first order."""
    if f.q:
        needle = f.q.casefold()
        rows = [r for r in rows if _matches_query(r, needle)]
    if f.bucket == "SERVICES":
        rows = [r for r in rows if r["services"]]
    elif f.bucket != "ALL":
        rows = [r for r in rows if opr_bucket(r["opr"]) == f.bucket]
    if f.opr is not None:
        rows = [r for r in rows if r["opr"] == f.opr]
    # Rows arrive as (-date, -id). Python's sort is stable, also with reverse=True, so give ties a -id order first.
    rows = sorted(rows, key=lambda r: r["id"], reverse=True)
    return sorted(rows, key=_sort_key(f.sort), reverse=f.desc)


def totals(rows):
    buckets = [opr_bucket(r["opr"]) for r in rows]
    return {
        "vessels": len(rows),
        "ark": buckets.count("ARK"),
        "msk": buckets.count("MSK"),
        "oth": buckets.count("OTH"),
        "with_services": sum(1 for r in rows if r["services"]),
        "cost_egp": round(sum(r["total_cost_egp"] for r in rows), 2),
        "profit_egp": round(sum(r["total_profit_egp"] for r in rows), 2),
    }


def list_response(profile, params):
    f = parse_filters(params)
    in_range = range_rows(profile, f)
    rows = matching(in_range, f)
    start = (f.page - 1) * f.page_size
    return {
        "vessels": rows[start : start + f.page_size],
        "page": f.page,
        "page_size": f.page_size,
        "count": len(rows),
        "pages": max(1, math.ceil(len(rows) / f.page_size)),
        "totals": totals(in_range),
    }



def alerts_response(profile, params):
    """Vessels dated today or tomorrow (Cairo date), whatever range or search the list shows, and past vessels missing
    an agent."""
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    vessels = scoped_vessels(profile, params.get("port") or None).filter(date__in=[today, tomorrow])
    rows = _figures(vessels.order_by("-id"))
    return {
        "today": [r for r in rows if r["date"] == today.isoformat()],
        "tomorrow": [r for r in rows if r["date"] == tomorrow.isoformat()],
        "missing_agent": missing_agents(profile, params.get("port") or None, today),
    }


def missing_agents(profile, port, today):
    """Vessels dated before today (Cairo) that miss an agent, oldest first. Every service type needs one.

    `missing` names what is missing: "Arrival", "Sailing", then each service type without an agent (once, in
    SERVICE_TYPES order). Only these four fields are sent, so the list stays light however long it grows."""
    order = {name: i for i, name in enumerate(SERVICE_TYPES)}
    found = []
    # No look-back limit, so keep the query light: only vessels with a gap, and only the columns needed.
    gaps = Q(arrival_agent="") | Q(sailing_agent="") | Q(services__agent="")
    light_services = Service.objects.only("id", "vessel_id", "service_type", "agent")
    vessels = (
        scoped_vessels(profile, port, prefetch=False)
        .filter(date__lt=today)
        .filter(pk__in=Vessel.objects.filter(gaps).values("pk"))
        .only("id", "name", "date", "arrival_agent", "sailing_agent")
        .prefetch_related(Prefetch("services", queryset=light_services))
    )
    for vessel in vessels.order_by("date", "id"):
        missing = [label for label, agent in (("Arrival", vessel.arrival_agent), ("Sailing", vessel.sailing_agent))
                   if not agent]
        types = {s.service_type for s in vessel.services.all() if not s.agent}
        missing += sorted(types, key=lambda name: order.get(name, len(order)))
        if missing:
            found.append({"id": vessel.id, "name": vessel.name, "date": vessel.date.isoformat(), "missing": missing})
    return found

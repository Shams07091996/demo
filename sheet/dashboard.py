"""The Dashboard: OPR figures, jobs per agent, services per month and money per month, for one set of filters.

A job is entering a vessel (its arrival agent), sailing it (its sailing agent) or one service (that service's agent);
a Crew Change is one job however many crew it moves. Months follow the vessel date. Money is the services' own
figures (finance.compute, via serializers.vessel_to_dict), summed and rounded once; hotels and transport never count
here. The status table counts the services by operations status and the Calculations rows (calculations.rows_for)
by accounting state. Everything is worked out per request from the vessels this profile may see (access.scoped_vessels).
"""

from dataclasses import dataclass
from datetime import date

from .access import scoped_vessels
from .constants import NO_AGENT, SERVICE_STATUSES, SERVICE_TYPES
from .errors import BadRequest
from .listing import date_param
from .serializers import month_rates, vessel_to_dict

MAX_JOBS = 500
MONEY = ("cost_egp", "revenue_egp", "profit_egp")
STATUS_KEYS = (*SERVICE_STATUSES, "open", "closed")
_TYPE_ORDER = {name: i for i, name in enumerate(SERVICE_TYPES)}


@dataclass
class Filters:
    date_from: date | None
    date_to: date | None
    port: str | None
    opr: str | None
    agent: str | None  # None: every agent; "": jobs nobody was assigned to
    service: str | None


def parse(params):
    f = Filters(
        date_from=date_param(params, "from"),
        date_to=date_param(params, "to"),
        port=params.get("port") or None,
        opr=params.get("opr") or None,
        agent=None,
        service=params.get("service") or None,
    )
    if f.date_from and f.date_to and f.date_from > f.date_to:
        raise BadRequest("From must be on or before To.")
    if f.service is not None and f.service not in SERVICE_TYPES:
        raise BadRequest("Unknown service type.")
    agent = params.get("agent")
    if agent:
        f.agent = "" if agent == NO_AGENT else agent
    return f


def _rows(profile, f):
    """Vessels in date range + port (not narrowed by OPR) with figures, newest first."""
    queryset = scoped_vessels(profile, f.port)
    if f.date_from:
        queryset = queryset.filter(date__gte=f.date_from)
    if f.date_to:
        queryset = queryset.filter(date__lte=f.date_to)
    rates = month_rates()
    return [vessel_to_dict(v, rates) for v in queryset.order_by("-date", "-id")]


def _jobs(row, f):
    """(job label, agent, service or None) of one vessel that pass the agent / service filters."""
    jobs = []
    if f.service is None:
        jobs += [("Arrival", row["arrival_agent"], None), ("Sailing", row["sailing_agent"], None)]
    jobs += [(s["type"], s["agent"], s) for s in row["services"] if f.service in (None, s["type"])]
    if f.agent is not None:
        jobs = [job for job in jobs if job[1] == f.agent]
    return jobs


def _agents_of(row):
    return (row["arrival_agent"], row["sailing_agent"], *(s["agent"] for s in row["services"]))


def _service_counts(services):
    """Services by type; Crew Change counts the people signing on / off, as the OPR summary shows them."""
    counts = {}
    for service in services:
        if service["type"] == "Crew Change":
            data = service["data"] or {}
            for key, label in (("onSigners", "Crew Change (On)"), ("offSigners", "Crew Change (Off)")):
                counts[label] = counts.get(label, 0) + len(data.get(key) or [])
        else:
            counts[service["type"]] = counts.get(service["type"], 0) + 1
    return counts


def _months_between(first, last):
    year, month = first
    while (year, month) <= last:
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def status_counts(profile, vessels, narrowed):
    """{"months", "totals"}: services per operations status and Calculations rows Open / Closed, per vessel-date
    month (zero-filled between the first and last month with any count). `vessels` are the (row, jobs) that count;
    when narrowed (agent / service filter), only the counted services and their rows count, no bookings."""
    from . import calculations  # calculations imports listing, like this module's callers

    months = {}

    def month_of(day):
        return months.setdefault(day[:7], dict.fromkeys(STATUS_KEYS, 0))

    counted = set()
    for row, jobs in vessels:
        services = [s for _, _, s in jobs if s is not None] if narrowed else row["services"]
        for service in services:
            month_of(row["date"])[service["status"]] += 1
            counted.add(service["id"])
    ids = [row["id"] for row, _ in vessels]
    for line in calculations.rows_for(scoped_vessels(profile, prefetch=False).filter(pk__in=ids)):
        if narrowed and (line["ref"] or {}).get("kind") != "service" or narrowed and line["ref"]["id"] not in counted:
            continue
        month_of(line["vessel"]["date"])["closed" if line["closed"] else "open"] += 1
    month_list = []
    if months:
        keys = sorted(months)
        first, last = (tuple(int(x) for x in key.split("-")) for key in (keys[0], keys[-1]))
        month_list = [{"month": key, **months.get(key, dict.fromkeys(STATUS_KEYS, 0))}
                      for key in _months_between(first, last)]
    return {"months": month_list, "totals": {key: sum(m[key] for m in month_list) for key in STATUS_KEYS}}


def response(profile, params):
    f = parse(params)
    in_range = _rows(profile, f)
    filters = {
        "oprs": sorted({r["opr"] for r in in_range if r["opr"]}, key=str.casefold),
        "agents": sorted({a for r in in_range for a in _agents_of(r) if a}, key=str.casefold),
    }
    narrowed = f.agent is not None or f.service is not None
    vessels = []  # (row, its jobs) of the vessels that count
    for row in in_range:
        if f.opr is not None and row["opr"] != f.opr:
            continue
        jobs = _jobs(row, f)
        if narrowed and not jobs:
            continue
        vessels.append((row, jobs))

    by_opr, agents, months = {}, {}, {}
    totals = {"jobs": 0, "services": 0, **{key: 0.0 for key in MONEY}}
    for row, jobs in vessels:
        services = [s for _, _, s in jobs if s is not None] if narrowed else row["services"]
        if row["opr"]:
            by_opr.setdefault(row["opr"], []).append(services)
        month = row["date"][:7]
        for label, agent, service in jobs:
            entry = agents.setdefault(agent, {"agent": agent, "arrivals": 0, "sailings": 0, "by_type": {}, "total": 0})
            entry["total"] += 1
            totals["jobs"] += 1
            if service is None:
                entry["arrivals" if label == "Arrival" else "sailings"] += 1
                continue
            entry["by_type"][label] = entry["by_type"].get(label, 0) + 1
            m = months.setdefault(month, {"month": month, "by_type": {}, "total": 0, **{key: 0.0 for key in MONEY}})
            m["by_type"][label] = m["by_type"].get(label, 0) + 1
            m["total"] += 1
            totals["services"] += 1
            for key in MONEY:
                m[key] += service["calc"][key]
                totals[key] += service["calc"][key]

    oprs = [
        {
            "opr": opr,
            "vessels": len(groups),
            "services": sum(len(services) for services in groups),
            "cost_egp": round(sum(s["calc"]["cost_egp"] for services in groups for s in services), 2),
            "profit_egp": round(sum(s["calc"]["profit_egp"] for services in groups for s in services), 2),
            "service_counts": _service_counts([s for services in groups for s in services]),
        }
        for opr, groups in sorted(by_opr.items())
    ]
    month_list = []
    if months:
        keys = sorted(months)
        first, last = (tuple(int(x) for x in key.split("-")) for key in (keys[0], keys[-1]))
        for key in _months_between(first, last):
            m = months.get(key) or {"month": key, "by_type": {}, "total": 0, **{k: 0.0 for k in MONEY}}
            month_list.append({**m, **{k: round(m[k], 2) for k in MONEY}})
    present = {t for entry in agents.values() for t in entry["by_type"]}
    return {
        "count": len(vessels),
        "oprs": oprs,
        "filters": filters,
        "service_types": sorted(present, key=_TYPE_ORDER.get),
        # Busiest first; "(no agent)" always last.
        "agents": sorted(agents.values(), key=lambda a: (a["agent"] == "", -a["total"], a["agent"].casefold())),
        "months": month_list,
        "totals": {**totals, **{key: round(totals[key], 2) for key in MONEY}},
        "status": status_counts(profile, vessels, narrowed),
    }


def jobs_response(profile, params):
    """One agent's jobs in the filters (the Dashboard's agent row), newest vessel first, at most MAX_JOBS."""
    if not params.get("agent"):
        raise BadRequest("Choose an agent.")
    f = parse(params)
    jobs = []
    for row in _rows(profile, f):
        if f.opr is not None and row["opr"] != f.opr:
            continue
        jobs += [
            {"vessel_id": row["id"], "vessel": row["name"], "date": row["date"], "job": label}
            for label, _, _ in _jobs(row, f)
        ]
    return {"jobs": jobs[:MAX_JOBS], "truncated": len(jobs) > MAX_JOBS}

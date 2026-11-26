"""The Services page: services (not vessels or money lines) as a work list, with what each one is missing."""

from django.utils import timezone

from . import crewbookings, finance, moneyaccess
from .access import scoped_vessels
from .constants import MULTI_TYPES, NO_AGENT, SERVICE_STATUSES, SERVICE_TYPES
from .errors import BadRequest
from .listing import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, date_param, int_param
from .models import Guest, HotelStay, Service
from .serializers import local_iso, month_rates


def status_permissions(old, new):
    """The permissions a change of status needs: to or from Cancelled `services.cancel`, to or from Completed
    `services.complete` (Cancelled -> Completed both); none when it stays the same."""
    if old == new:
        return []
    needs = []
    if "cancelled" in (old, new):
        needs.append("services.cancel")
    if "completed" in (old, new):
        needs.append("services.complete")
    return needs


def stamp_completed(service, old_status, now):
    """completed_at follows the status, never the payload: it becomes Completed -> now; it leaves Completed -> None;
    otherwise unchanged (a save that keeps it Completed keeps its time)."""
    if service.status == "completed":
        if old_status != "completed":  # completed before tracking began: stays without a time
            service.completed_at = now
    else:
        service.completed_at = None


MISSING_ORDER = ("Agent", "Cost", "Revenue", "Rate", "Bookings")


def _empty(value):
    return value is None or value == ""  # a typed 0 is filled in (the user's decision)


def money_gaps(service_type, data):
    """(cost missing, revenue missing): a money box of this type left empty. Cash to Master has no cost (the rest
    goes to the master); its revenue is the amount with its percentage or fixed share."""
    data = data or {}
    if service_type == "Cash to Master":
        share = "fixedRevenue" if data.get("shareMode") == "fixed" else "percentage"
        return False, _empty(data.get("amount")) or _empty(data.get(share))
    if service_type in MULTI_TYPES:
        entries = [e for e in data.get("entries") or [] if isinstance(e, dict)]
        if not entries:
            return True, True
        return any(_empty(e.get("cost")) for e in entries), any(_empty(e.get("revenue")) for e in entries)
    return _empty(data.get("cost")), _empty(data.get("revenue"))


def missing(service, month_rate, incomplete_uids):
    """What this service still lacks, in MISSING_ORDER; nothing for a cancelled service. `incomplete_uids`: crew uids
    of this vessel's incomplete bookings (incomplete_crew_uids)."""
    if service.status == "cancelled":
        return []
    found = []
    if not service.agent:
        found.append("Agent")
    cost, revenue = money_gaps(service.service_type, service.data)
    if cost:
        found.append("Cost")
    if revenue:
        found.append("Revenue")
    if any(line["rate_missing"] for line in finance.service_lines(service.service_type, service.data, month_rate)):
        found.append("Rate")
    if service.service_type == "Crew Change" and crewbookings._crew_uids(service) & incomplete_uids:
        found.append("Bookings")
    return found


def incomplete_crew_uids(vessel_ids):
    """Crew uids on the not-cancelled bookings of these vessels that are a draft or lack cost / revenue (the rule of
    the Missing details alert, without its "has sailed" limit)."""
    uids = set()
    for model, _label, incomplete_q in crewbookings._INCOMPLETE:
        bookings = model.objects.filter(incomplete_q, vessel_id__in=vessel_ids, cancelled=False).values("pk")
        link = "stay__in" if model is HotelStay else "transfer__in"
        uids |= set(Guest.objects.filter(**{link: bookings}).exclude(crew_uid="").values_list("crew_uid", flat=True))
    return uids


def sailed(vessel, today, now):
    """The vessel has left: its sailing time has passed, or it has none and its date is before today (Cairo)."""
    if vessel.sailing_at is not None:
        return vessel.sailing_at <= now
    return vessel.date < today


# ---- the list (GET /api/services/) ----------------------------------------------------------------------------


def _statuses(params):
    """The ticked statuses (comma list, empty items ignored); none sent = In progress, the to-do list."""
    items = {item.strip() for item in (params.get("status") or "").split(",") if item.strip()}
    if items - set(SERVICE_STATUSES):
        raise BadRequest("Unknown status.")
    return items or {"in_progress"}


def completed_day(service):
    """The Cairo date it was completed, or (completed before this was tracked) its vessel's date."""
    return timezone.localdate(service.completed_at) if service.completed_at else service.vessel.date


def _row(service, gaps, today, now):
    vessel = service.vessel
    return {
        "id": service.id,
        "vessel": {"id": vessel.id, "name": vessel.name, "date": vessel.date.isoformat(), "port": vessel.port,
                   "opr": vessel.opr, "terminal": vessel.terminal, "berth": vessel.berth},
        "type": service.service_type,
        "agent": service.agent,
        "status": service.status,
        "cancel_reason": service.cancel_reason,
        "completed_at": local_iso(service.completed_at),
        "completed_guess": service.status == "completed" and service.completed_at is None,
        "sailed": service.status == "in_progress" and sailed(vessel, today, now),
        "missing": gaps,
        "billing": service.billing,
        "billing_party": ({"id": service.billing_party.id, "name": service.billing_party.name}
                          if service.billing_party else None),
    }


def filtered(profile, params, today=None, now=None):
    """(rows, agents): every service the filters show, sorted, not paged (the page and its Excel export). Port users
    only ever get their own port (scoped_vessels). `agents`: the agents present before the agent filter."""
    now = now or timezone.now()
    today = today or timezone.localdate(now)
    statuses = _statuses(params)
    date_from, date_to = date_param(params, "from"), date_param(params, "to")
    if date_from and date_to and date_from > date_to:
        raise BadRequest("From must be on or before To.")
    service_type = params.get("type") or None
    if service_type is not None and service_type not in SERVICE_TYPES:
        raise BadRequest("Unknown service type.")
    agent = params.get("agent") or None
    search = (params.get("q") or "").strip().casefold()
    by_completed = statuses == {"completed"}  # only Completed ticked: the range is on the completed date

    vessels = scoped_vessels(profile, params.get("port") or None, prefetch=False)
    if not by_completed:
        if date_from:
            vessels = vessels.filter(date__gte=date_from)
        if date_to:
            vessels = vessels.filter(date__lte=date_to)
    found = Service.objects.filter(vessel__in=vessels, status__in=statuses).select_related("vessel", "billing_party")
    if service_type:
        found = found.filter(service_type=service_type)
    rates = month_rates()
    incomplete = incomplete_crew_uids(vessels.values("pk"))

    picked = []
    for service in found:
        if search and search not in service.vessel.name.casefold():
            continue
        if by_completed and ((date_from and completed_day(service) < date_from)
                             or (date_to and completed_day(service) > date_to)):
            continue
        month = (service.vessel.date.year, service.vessel.date.month)
        gaps = moneyaccess.tags_out(missing(service, rates.get(month), incomplete), profile)
        if params.get("missing") == "1" and not gaps:
            continue
        picked.append((service, gaps))
    agents = sorted({s.agent for s, _gaps in picked if s.agent}, key=str.casefold)
    if agent is not None:
        wanted = "" if agent == NO_AGENT else agent
        picked = [(s, gaps) for s, gaps in picked if s.agent == wanted]
    if by_completed:  # what got done: newest first
        picked.sort(key=lambda item: (completed_day(item[0]),
                                      item[0].completed_at.timestamp() if item[0].completed_at else 0, item[0].id),
                    reverse=True)
    else:  # the to-do list: oldest first
        picked.sort(key=lambda item: (item[0].vessel.date, item[0].id))
    return [_row(s, gaps, today, now) for s, gaps in picked], agents


def grouped(rows):
    """The rows under their vessels: vessels in the order of their first row, each with its rows in order."""
    groups = {}
    for row in rows:
        groups.setdefault(row["vessel"]["id"], {"vessel": row["vessel"], "services": []})["services"].append(row)
    return list(groups.values())


def list_response(profile, params):
    """The page: matching services under their vessels, paged by vessel (the Excel export stays one row a service)."""
    page = int_param(params, "page", 1, 1, 10**9, "Page must be a whole number from 1.")
    page_size = int_param(params, "page_size", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE, "Rows per page must be 1–200.")
    rows, agents = filtered(profile, params)
    vessels = grouped(rows)
    start = (page - 1) * page_size
    return {"vessels": vessels[start:start + page_size], "count": len(vessels), "services_count": len(rows),
            "page": page, "page_size": page_size, "pages": max(1, -(-len(vessels) // page_size)), "agents": agents}

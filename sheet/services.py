"""The Services page: services (not vessels or money lines) as a work list, with what each one is missing."""

from . import crewbookings, finance
from .constants import MULTI_TYPES
from .models import Guest, HotelStay


def stamp_completed(service, old_status, now):
    """completed_at follows the status, never the payload: it becomes Completed -> now; it leaves Completed -> None;
    otherwise unchanged (a save that keeps it Completed keeps its time)."""
    if service.status == "completed":
        if old_status != "completed" or service.completed_at is None:
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
        bookings = model.objects.filter(incomplete_q, vessel_id__in=vessel_ids, cancelled=False)
        link = "stay__in" if model is HotelStay else "transfer__in"
        uids |= set(Guest.objects.filter(**{link: bookings}).exclude(crew_uid="").values_list("crew_uid", flat=True))
    return uids


def sailed(vessel, today, now):
    """The vessel has left: its sailing time has passed, or it has none and its date is before today (Cairo)."""
    if vessel.sailing_at is not None:
        return vessel.sailing_at <= now
    return vessel.date < today

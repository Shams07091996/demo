"""Accounting status: each thing that makes a Calculations row — a service (all its rows together), a hotel stay, a
transfer, a vessel's garbage & sludge — is Open (default) or Closed (settled). Read-only accounts (the accountants)
and admins set it on the Calculations page; nobody else.

A Closed thing is locked: no edit or delete of it, no change to that vessel's garbage / sludge, no deleting its
vessel, for every role — accounting reopens it first. Setting the flag never raises `version` (an accounting click must
not make an operations dialog conflict) and operations saves never write it (conflicts.UNTRACKED).

Closing needs a rate (the month's, or one written on the line) for anything in USD, and garbage & sludge needs its
month's price. A line that used the month's rate gets it written on as its own rate (as if typed, version raised), and
garbage & sludge keeps a copy of its price too: the numbers stay as closed, also after reopening, until a person
changes them.
"""

from django.shortcuts import get_object_or_404

from .access import scoped_vessels
from .errors import BadRequest
from .models import HotelStay, Service, Transfer, VesselDisposal

LOCKED = "Accounting has closed this. Ask accounting to reopen it first."
NO_MONEY = "Only a line with money can be closed."
NEEDS_RATE = "Add this month's exchange rate (or write one on the line) first."
NEEDS_PRICE = "Add this month's Garbage & Sludge price first."
KINDS = {"service": Service, "hotel": HotelStay, "transfer": Transfer, "disposal": VesselDisposal}


def clean_request(payload):
    """(kind, id, closed) of a POST /api/accounting/ body; anything else is refused."""
    kind, pk, closed = payload.get("kind"), payload.get("id"), payload.get("closed")
    if not isinstance(kind, str) or kind not in KINDS:
        raise BadRequest("Unknown row.")
    if not isinstance(pk, int) or isinstance(pk, bool) or pk < 1:
        raise BadRequest("Unknown row.")
    if not isinstance(closed, bool):
        raise BadRequest("Say whether the row is closed (true or false).")
    return kind, pk, closed


def set_closed(profile, kind, pk, closed):
    """Close or reopen one row the profile may see (404 otherwise). Saves only the flag."""
    rows = KINDS[kind].objects.filter(vessel__in=scoped_vessels(profile, prefetch=False)).select_for_update()
    obj = get_object_or_404(rows, pk=pk)
    fields = ["acct_closed"]
    if closed and not obj.acct_closed:
        fields += _keep_numbers(kind, obj, _lines(kind, obj))
    if obj.acct_closed != closed:
        obj.acct_closed = closed
        obj.save(update_fields=fields)
    return obj


def _lines(kind, obj):
    """The thing's Calculations rows; refused when it has none, or a rate or price is missing."""
    from .calculations import rows_for
    from .models import Vessel

    rows = [row for row in rows_for(Vessel.objects.filter(pk=obj.vessel_id))
            if row["ref"] == {"kind": kind, "id": obj.pk}]
    if not rows:
        raise BadRequest(NO_MONEY)
    if any(row["price_missing"] for row in rows):
        raise BadRequest(NEEDS_PRICE)
    if any(row["rate_missing"] for row in rows):
        raise BadRequest(NEEDS_RATE)
    return rows


def _keep_numbers(kind, obj, rows):
    """Write the month's rate (and garbage & sludge's price) onto the thing; the fields to save."""
    from . import disposal
    from .serializers import month_rates

    vessel = obj.vessel
    month = (vessel.date.year, vessel.date.month)
    rate = month_rates().get(month)
    used_month = any(row["rate_source"] == "month" for row in rows)
    if kind == "service":
        if not used_month or rate is None:
            return []
        obj.data = {**(obj.data or {}), "exchangeRate": float(rate)}
        obj.version += 1
        return ["data", "version"]
    if kind in ("hotel", "transfer"):
        if not used_month or rate is None or obj.exchange_rate is not None:
            return []
        obj.exchange_rate = rate
        obj.version += 1
        return ["exchange_rate", "version"]
    fields = []
    if obj.exchange_rate is None and rate is not None:
        obj.exchange_rate = rate
        fields.append("exchange_rate")
    if obj.frozen_price is None:
        price = disposal.prices_map().get((*month, vessel.port))
        if price is not None:
            obj.frozen_price = price
            fields.append("frozen_price")
    return fields


def _any_closed(queryset):
    """Whether any of these rows is closed, read under a row lock: accounting closing one of them meanwhile waits for
    this transaction (or this one waits for it and then sees the stored value), so a check can't go stale."""
    return any(queryset.select_for_update().values_list("acct_closed", flat=True))


def require_open(obj):
    """Refuse a change to something accounting has closed (None: nothing there yet, so nothing to lock). Reads the
    stored flag, not the one on `obj`, which may have been loaded before accounting closed it."""
    if obj is not None and _any_closed(type(obj).objects.filter(pk=obj.pk)):
        raise BadRequest(LOCKED)


def require_vessel_open(vessel):
    """Refuse deleting a vessel while any of its services, bookings or its garbage & sludge is closed."""
    models = (Service, HotelStay, Transfer, VesselDisposal)
    if any(_any_closed(model.objects.filter(vessel=vessel)) for model in models):
        raise BadRequest(LOCKED)

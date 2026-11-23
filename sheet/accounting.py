"""Accounting status: each thing that makes a Calculations row — a service (all its rows together), a hotel stay, a
transfer, a vessel's garbage & sludge — is Open (default) or Closed (settled). Read-only accounts (the accountants)
and admins set it on the Calculations page; nobody else.

A Closed thing is locked: no edit or delete of it, no change to that vessel's garbage / sludge, no deleting its
vessel, for every role — accounting reopens it first. Setting the flag never raises `version` (an accounting click must
not make an operations dialog conflict) and operations saves never write it (conflicts.UNTRACKED).
"""

from django.shortcuts import get_object_or_404

from .access import scoped_vessels
from .errors import BadRequest
from .models import HotelStay, Service, Transfer, VesselDisposal

LOCKED = "Accounting has closed this. Ask accounting to reopen it first."
KINDS = {"service": Service, "hotel": HotelStay, "transfer": Transfer, "disposal": VesselDisposal}


def clean_request(payload):
    """(kind, id, closed) of a POST /api/accounting/ body; anything else is refused."""
    kind, pk, closed = payload.get("kind"), payload.get("id"), payload.get("closed")
    if kind not in KINDS:
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
    if obj.acct_closed != closed:
        obj.acct_closed = closed
        obj.save(update_fields=["acct_closed"])
    return obj


def require_open(obj):
    """Refuse a change to something accounting has closed (None: nothing there yet, so nothing to lock)."""
    if obj is not None and obj.acct_closed:
        raise BadRequest(LOCKED)


def require_vessel_open(vessel):
    """Refuse deleting a vessel while any of its services, bookings or its garbage & sludge is closed."""
    closed = (
        vessel.services.filter(acct_closed=True).exists()
        or vessel.hotel_stays.filter(acct_closed=True).exists()
        or vessel.transfers.filter(acct_closed=True).exists()
        or VesselDisposal.objects.filter(vessel=vessel, acct_closed=True).exists()
    )
    if closed:
        raise BadRequest(LOCKED)

"""Port closures: when a port was shut (weather, fog, strike...). A record of its own, not linked to vessels.

Scoped by the closure's own port (`access.scoped_closures`); the list shows the closures that overlap a date range
(Cairo dates), newest first. A closure with no Reopened time is still going on, so it overlaps every later range."""

from datetime import datetime, time, timedelta

from django.http import Http404
from django.utils import timezone

from . import conflicts, ports
from .access import scoped_closures
from .errors import BadRequest
from .listing import date_param
from .models import PortClosure
from .serializers import local_iso
from .validators import clean_closure


def closure_to_dict(closure, profile):
    hours = (closure.end_at - closure.start_at).total_seconds() / 3600 if closure.end_at else None
    return {
        "id": closure.id,
        "port": closure.port,
        "port_label": ports.label(closure.port),
        "start_at": local_iso(closure.start_at),
        "end_at": local_iso(closure.end_at),
        "hours": round(hours, 1) if hours is not None else None,
        "reason": closure.reason,
        "notes": closure.notes,
        "version": closure.version,
        "can_edit": profile.is_admin or profile.port == closure.port,
    }


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def filtered(profile, params):
    """The closures the page shows (scoped, overlapping From–To), newest first (also the export)."""
    date_from, date_to = date_param(params, "from"), date_param(params, "to")
    if date_from and date_to and date_from > date_to:
        raise BadRequest("From must be on or before To.")
    queryset = scoped_closures(profile, params.get("port") or None)
    if date_to:
        queryset = queryset.filter(start_at__lt=_day_start(date_to + timedelta(days=1)))
    if date_from:
        start = _day_start(date_from)
        queryset = queryset.filter(end_at__isnull=True) | queryset.filter(end_at__gte=start)
    return queryset.order_by("-start_at", "-id")


def list_response(profile, params):
    return {"closures": [closure_to_dict(c, profile) for c in filtered(profile, params)]}


def get_closure(profile, pk):
    try:
        return scoped_closures(profile).get(pk=pk)
    except PortClosure.DoesNotExist:
        raise Http404 from None


def save_closure(profile, data, existing=None):
    """Create (existing=None) or replace a closure from browser data."""
    closure = existing or PortClosure()
    before = conflicts.snapshot(closure)
    for field, value in clean_closure(data, profile, existing).items():
        setattr(closure, field, value)
    if existing:
        conflicts.bump_if_changed(closure, before)
    closure.save()
    return closure

"""Edit conflicts: a save of a record someone else saved after it was opened is refused (409), never silent.

Vessel, Service, HotelStay, Transfer and PortClosure have a `version` counter. A dialog sends the version it opened
with; the update view locks the row, `check`s it, and raises it with `bump_if_changed` **before** saving, so the
version change is in the same History record as the fields it came with. Only real changes count (a save of the
same values, or a booking re-saved with the same guests, keeps the version), and only person saves raise it —
automatic updates (crewbookings.sync, the sailing-day rule) never do, so they never cause a warning.
"""

import re

from django.utils import timezone

from .constants import TIME_LABELS
from .errors import ApiError, BadRequest
from .history import _values
from .models import ChangeRecord, HotelStay, Service, Transfer

OUT_OF_DATE = "This page is out of date. Reload it and try again."
UNTRACKED = {"id", "created_at", "version"}
GUEST_FIELDS = ("name", "rank", "nationality", "group", "flight", "crew_uid")
BOOKINGS = (HotelStay, Transfer)
LABELS = {**TIME_LABELS, "service_type": "Type", "port_name": "Port", "from_place": "From", "to_place": "To",
          "at": "Time", "check_in": "Check-in"}


class Conflict(ApiError):
    status = 409


def sent_version(payload):
    """The version the browser opened the record with: a whole number from 1, else the page is out of date."""
    value = payload.get("version") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BadRequest(OUT_OF_DATE)
    return value


def _guest_values(guests):
    return tuple(tuple(str(guest.get(field) or "") for field in GUEST_FIELDS) for guest in guests)


def snapshot(instance, guests=None):
    """What a person can change on this record (a booking: its guests too, from `guests` or the database)."""
    values = tuple(sorted((k, repr(v)) for k, v in _values(instance).items() if k not in UNTRACKED))
    if not isinstance(instance, BOOKINGS):
        return values, ()
    if guests is None:
        guests = instance.guests.values(*GUEST_FIELDS) if instance.pk else []
    return values, _guest_values(guests)


def bump_if_changed(instance, before, guests=None):
    """Raise the version (not saved yet: the caller saves) when the record — or a booking's guests — will differ."""
    if snapshot(instance, guests) != before:
        instance.version += 1


def check(instance, sent, user):
    if instance.version != sent:
        raise Conflict("conflict", conflict=describe(instance, sent, user))


def locked(instance, payload, user):
    """The record locked for this write (inside the request's transaction), once the version sent is current."""
    sent = sent_version(payload)
    row = type(instance).objects.select_for_update().get(pk=instance.pk)
    check(row, sent, user)
    return row


def _label(model, field):
    if field in LABELS:
        return LABELS[field]
    name = field.removesuffix("_id")
    try:
        verbose = str(model._meta.get_field(name).verbose_name)
    except Exception:  # noqa: BLE001 -- an unknown key: show it readable
        verbose = name.replace("_", " ")
    return verbose[:1].upper() + verbose[1:]


def _data_labels(old, new):
    old, new = old or {}, new or {}
    keys = [k for k in {**old, **new} if old.get(k) != new.get(k)]
    return [re.sub(r"(?<!^)(?=[A-Z])", " ", key).capitalize() for key in keys]


def _fields(model, records):
    found = []
    for record in records:
        for field, (old, new) in record.changes.items():
            if field == "version":
                continue
            labels = _data_labels(old, new) if model is Service and field == "data" else [_label(model, field)]
            found += [label for label in labels if label not in found]
    if not found and model in BOOKINGS:
        found = ["Guests"]
    return found


def _when(moment):
    local = timezone.localtime(moment)
    return f"{local:%H:%M}" if local.date() == timezone.localdate() else f"{local:%d/%m %H:%M}"


def describe(instance, sent, user):
    """Who saved last, when, and which fields changed since `sent` (from the History), and the current version."""
    model = type(instance)
    records = list(ChangeRecord.objects.filter(object_type=model._meta.model_name, object_id=instance.pk)
                   .order_by("id"))
    start = 0
    for index, record in enumerate(records):
        version = record.changes.get("version")
        if (version and version[1] == sent) or (sent == 1 and record.action == "create"):
            start = index + 1
    after = records[start:]
    saves = [r for r in after if "version" in r.changes] or after
    last = saves[-1] if saves else None
    return {
        "who": last.username if last else "",
        "same_person": bool(last and user is not None and last.user_id == user.id),
        "at": _when(last.at) if last else "",
        "fields": _fields(model, after),
        "version": instance.version,
    }

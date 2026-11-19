"""Hotels and Transport: the bookings lists (range, search, sort, paging), saving bookings, and the crew picker.

A booking is one hotel room (HotelStay) or one car trip (Transfer) for 1..6 guests of one vessel. Bookings are
scoped through their vessel, so port users only ever see and change their own port's. Every role sees booking money
(cost = what we pay, revenue = what we get); only editors change it. Booking money counts on the Calculations page
only; it is not part of any vessel figure.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from . import finance, history
from .access import scoped_vessels
from .constants import MAX_NIGHTS, PORT_LABELS
from .errors import BadRequest
from .listing import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MAX_QUERY, date_param, int_param
from .models import Guest, HotelStay, Transfer, Vessel
from .serializers import local_iso
from .validators import check_booking_lists, clean_hotel_stay, clean_transfer

KINDS = {"hotels": HotelStay, "transfers": Transfer}
SORTS = {
    "hotels": ("check_in", "nights", "hotel", "guest", "vessel"),
    "transfers": ("at", "from_place", "to_place", "guest", "vessel"),
}
MONEY_KEYS = {"hotels": ("cost_per_night", "revenue_per_night"), "transfers": ("cost", "revenue")}
PLACE_LABELS = {"airport": "Airport", "hotel": "Hotel", "port": "Port"}
CLEANERS = {"hotels": clean_hotel_stay, "transfers": clean_transfer}
GUEST_FK = {"hotels": "stay", "transfers": "transfer"}


@dataclass
class Params:
    date_from: date | None
    date_to: date | None
    q: str
    port: str | None
    sort: str
    desc: bool
    page: int
    page_size: int


def parse_params(kind, params):
    p = Params(
        date_from=date_param(params, "from"),
        date_to=date_param(params, "to"),
        q=(params.get("q") or "").strip()[:MAX_QUERY],
        port=params.get("port") or None,
        sort=params.get("sort") or SORTS[kind][0],
        desc=False,
        page=int_param(params, "page", 1, 1, 10**9, "Page must be a whole number from 1."),
        page_size=int_param(params, "page_size", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE, "Rows per page must be 1–200."),
    )
    if p.date_from and p.date_to and p.date_from > p.date_to:
        raise BadRequest("From must be on or before To.")
    if p.sort not in SORTS[kind]:
        raise BadRequest("Unknown sort.")
    direction = params.get("dir") or "asc"
    if direction not in ("asc", "desc"):
        raise BadRequest("Unknown sort.")
    p.desc = direction == "desc"
    return p


def scoped(kind, profile, port=None):
    """The bookings of this kind whose vessel the profile may see."""
    return (
        KINDS[kind]
        .objects.filter(vessel__in=scoped_vessels(profile, port, prefetch=False))
        .select_related("vessel")
        .prefetch_related("guests")
    )


def _in_range(kind, queryset, p):
    if kind == "transfers":  # the trip's (Cairo) date is in the range
        if p.date_from:
            queryset = queryset.filter(at__date__gte=p.date_from)
        if p.date_to:
            queryset = queryset.filter(at__date__lte=p.date_to)
        return list(queryset)
    # A stay is shown for every night it covers: check-in <= to and check-out > from.
    if p.date_to:
        queryset = queryset.filter(check_in__lte=p.date_to)
    if p.date_from:
        queryset = queryset.filter(check_in__gt=p.date_from - timedelta(days=MAX_NIGHTS))
        return [s for s in queryset if s.check_out > p.date_from]
    return list(queryset)


def _guest_dict(guest):
    return {
        "name": guest.name, "rank": guest.rank, "nationality": guest.nationality,
        "group": guest.group, "flight": guest.flight, "crew_uid": guest.crew_uid,
    }


def booking_to_dict(kind, obj, profile):
    vessel = obj.vessel
    row = {
        "id": obj.id,
        "vessel": {"id": vessel.id, "name": vessel.name, "port": vessel.port,
                   "port_label": PORT_LABELS.get(vessel.port, vessel.port)},
        "guests": [_guest_dict(g) for g in obj.guests.all()],
        "hotel": obj.hotel,
        "draft": obj.draft,
    }
    if kind == "hotels":
        row.update(check_in=obj.check_in.isoformat(), nights=obj.nights, check_out=obj.check_out.isoformat())
    else:
        row.update(from_place=obj.from_place, to_place=obj.to_place, airport=obj.airport, port_name=obj.port_name,
                   at=local_iso(obj.at))
    as_float = lambda value: float(value) if value is not None else None  # noqa: E731
    cost_key, revenue_key = MONEY_KEYS[kind]
    row.update(
        {
            cost_key: as_float(getattr(obj, cost_key)),
            "cost_currency": obj.cost_currency,
            revenue_key: as_float(getattr(obj, revenue_key)),
            "revenue_currency": obj.revenue_currency,
            "exchange_rate": as_float(obj.exchange_rate),
        }
    )
    return row


def _place(transfer, place):
    name = {"airport": transfer.airport, "hotel": transfer.hotel, "port": transfer.port_name}[place]
    return f"{PLACE_LABELS[place]} ({name})" if name else PLACE_LABELS[place]


def booking_line(kind, obj, month_rate):
    """The money line of a hotel stay (per night × nights) or a transfer, in finance's line shape."""
    own_rate = finance.num(obj.exchange_rate)
    rate = own_rate or finance.num(month_rate)
    cost_key, revenue_key = MONEY_KEYS[kind]
    times = obj.nights if kind == "hotels" else 1
    if kind == "hotels":
        label = f"Hotel · {obj.hotel} · {obj.nights} night{'' if obj.nights == 1 else 's'}"
    else:
        label = f"Transfer · {_place(obj, obj.from_place)} → {_place(obj, obj.to_place)}"
    return finance.line(
        label,
        finance.money(getattr(obj, cost_key), obj.cost_currency, rate, times),
        finance.money(getattr(obj, revenue_key), obj.revenue_currency, rate, times),
        own_rate,
    )


def _matches(row, needle):
    fields = [row["vessel"]["name"], row["hotel"], row.get("airport"), row.get("port_name")]
    for guest in row["guests"]:
        fields += [guest["name"], guest["flight"]]
    return any(needle in (field or "").casefold() for field in fields)


def _sort_key(sort):
    if sort == "guest":
        return lambda r: (r["guests"][0]["name"] if r["guests"] else "").casefold()
    if sort == "vessel":
        return lambda r: r["vessel"]["name"].casefold()
    if sort == "nights":
        return lambda r: r[sort]
    return lambda r: str(r[sort]).casefold()


def list_response(kind, profile, params):
    p = parse_params(kind, params)
    rows = [booking_to_dict(kind, obj, profile) for obj in _in_range(kind, scoped(kind, profile, p.port), p)]
    if p.q:
        needle = p.q.casefold()
        rows = [r for r in rows if _matches(r, needle)]
    rows.sort(key=lambda r: r["id"])  # stable ties: oldest booking first
    rows.sort(key=_sort_key(p.sort), reverse=p.desc)
    start = (p.page - 1) * p.page_size
    return {
        "bookings": rows[start : start + p.page_size],
        "page": p.page,
        "page_size": p.page_size,
        "count": len(rows),
        "pages": max(1, -(-len(rows) // p.page_size)),
    }


def get_booking(kind, profile, pk):
    """A booking the profile may see, or 404."""
    try:
        return scoped(kind, profile).get(pk=pk)
    except KINDS[kind].DoesNotExist:
        raise Http404 from None


def _vessel_for(profile, raw_id):
    try:
        return scoped_vessels(profile, prefetch=False).get(pk=int(raw_id))
    except (TypeError, ValueError, Vessel.DoesNotExist):
        raise Http404 from None


def save_booking(kind, profile, data, existing=None):
    """Create (existing=None) or replace a booking from browser data. The vessel of an existing booking never
    changes; a new booking's vessel must be one the profile may see (else 404)."""
    cleaned = CLEANERS[kind](data)
    guests = cleaned.pop("guests")
    with transaction.atomic():
        obj = existing or KINDS[kind](vessel=_vessel_for(profile, data.get("vessel")))
        check_booking_lists(cleaned, obj.vessel.port, existing)
        for field, value in cleaned.items():
            setattr(obj, field, value)
        obj.draft = False  # saved by a person: no longer an automatic draft
        obj.save()
        obj.guests.all().delete()
        history.record_created(
            Guest.objects.bulk_create(
                [Guest(**{GUEST_FK[kind]: obj}, position=i, **guest) for i, guest in enumerate(guests)]
            )
        )
    return get_booking(kind, profile, obj.pk)


# ---- crew picker: the guests of a vessel's crew change, with a best-effort flight time ----------

_MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
_DAY_MONTH_TIME = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\s+(?:(\d{4})\s+)?(\d{1,2}):(\d{2})")
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_DMY = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")


def _aware(year, month, day, hour, minute):
    try:
        return timezone.make_aware(datetime(year, month, day, hour, minute))
    except ValueError:
        return None


def parse_flight_time(text, segment_date, near):
    """'13 NOV 10:00' (year optional) or '10:00' plus a dd.mm.yyyy segment date -> a Cairo datetime, or None when
    it can't be read. Without a year, the one putting the date nearest to `near` (the vessel date) is used."""
    text = str(text or "")
    found = _DAY_MONTH_TIME.search(text)
    if found:
        day, mon, year, hour, minute = found.groups()
        month = _MONTHS.get(mon.upper())
        if not month:
            return None
        years = [int(year)] if year else [near.year - 1, near.year, near.year + 1]
        candidates = [c for c in (_aware(y, month, int(day), int(hour), int(minute)) for y in years) if c]
        return min(candidates, key=lambda c: abs(c.date() - near)) if candidates else None
    clock, on_day = _TIME.match(text), _DMY.search(str(segment_date or ""))
    if clock and on_day:
        day, month, year = (int(x) for x in on_day.groups())
        return _aware(year, month, day, int(clock[1]), int(clock[2]))
    return None


def crew_leg(member, group):
    """The flight leg into Egypt (on-signer: the last) or out of Egypt (off-signer: the first), or {}."""
    segments = (member.get("flightStructured") or {}).get("segments") or []
    leg = (segments[-1] if group == "on" else segments[0]) if segments else {}
    return leg if isinstance(leg, dict) else {}


def crew_moment(member, group, near):
    """When an on-signer lands / an off-signer takes off (Cairo datetime), or None when it can't be read."""
    leg = crew_leg(member, group)
    key = "arrivalTime" if group == "on" else "departureTime"
    return parse_flight_time(leg.get(key), leg.get("date"), near) if leg else None


def _crew_entry(member, group, near):
    personal = member.get("personalStructured") or {}
    leg = crew_leg(member, group)
    moment = crew_moment(member, group, near)
    stamp = local_iso(moment) if moment else ""
    return {
        "uid": member.get("uid", ""),
        "group": group,
        "name": member.get("name") or personal.get("name") or "",
        "rank": personal.get("rank", ""),
        "nationality": personal.get("nationality", ""),
        "flight": leg.get("flightNo", ""),
        "city": leg.get("arrivalCity" if group == "on" else "departureCity", "") if leg else "",  # the airport's city
        "arrival": stamp if group == "on" else "",
        "departure": stamp if group == "off" else "",
    }


def crew_of(vessel):
    """On- and off-signers of every Crew Change service on the vessel, in order."""
    crew = []
    for service in vessel.services.filter(service_type="Crew Change").order_by("id"):
        data = service.data or {}
        for key, group in (("onSigners", "on"), ("offSigners", "off")):
            crew += [_crew_entry(m, group, vessel.date) for m in data.get(key) or [] if isinstance(m, dict)]
    return [c for c in crew if c["name"]]

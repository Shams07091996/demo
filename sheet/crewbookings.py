"""Automatic bookings for crew-change members.

Every crew member (on- and off-signer) gets a draft transfer, and a draft hotel stay while "Needs hotel" is on. A draft
is linked to its member by `Guest.crew_uid`; it follows the member (name, flight time) while it is still a draft with
that one guest, and is deleted when the member goes away (or switches Needs hotel off). A booking a person has saved
(`draft=False`) is never changed or deleted here. Runs inside the request's transaction, so history records the user.
"""

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from .logistics import crew_leg, crew_moment
from .models import Guest, HotelStay, Service, Transfer

_GROUPS = (("onSigners", "on"), ("offSigners", "off"))


def crew_members(vessel):
    """uid -> (member, "on" / "off") for every Crew Change service of the vessel that is not cancelled (a cancelled
    one's members lose their draft bookings, and get them back if it is un-cancelled)."""
    found = {}
    for service in vessel.services.filter(service_type="Crew Change").exclude(status="cancelled").order_by("id"):
        data = service.data or {}
        for key, group in _GROUPS:
            for member in data.get(key) or []:
                if isinstance(member, dict) and member.get("uid"):
                    found[member["uid"]] = (member, group)
    return found


def _guest_fields(member, group):
    personal = member.get("personalStructured") or {}
    return {
        "name": str(member.get("name") or personal.get("name") or "").upper()[:120],
        "rank": str(personal.get("rank") or "")[:60],
        "nationality": str(personal.get("nationality") or "")[:60],
        "group": group,
        "flight": str(crew_leg(member, group).get("flightNo") or "")[:20],
    }


def _when(member, group, vessel):
    """(transfer time, hotel check-in) for the member: from the flight, else the vessel date."""
    moment = crew_moment(member, group, vessel.date)
    at = moment or timezone.make_aware(datetime.combine(vessel.date, time()))
    check_in = timezone.localdate(moment) if moment and group == "on" else vessel.date
    return at, check_in


def _wanted(kind, member):
    return kind is Transfer or bool(member.get("needsHotel"))


def _create(kind, vessel, uid, member, group):
    at, check_in = _when(member, group, vessel)
    if kind is Transfer:
        ends = ("airport", "port") if group == "on" else ("port", "airport")
        booking = Transfer.objects.create(vessel=vessel, from_place=ends[0], to_place=ends[1], at=at, draft=True)
        Guest.objects.create(transfer=booking, crew_uid=uid, **_guest_fields(member, group))
    else:
        booking = HotelStay.objects.create(vessel=vessel, hotel="", check_in=check_in, nights=1, draft=True)
        Guest.objects.create(stay=booking, crew_uid=uid, **_guest_fields(member, group))


def _refresh(kind, booking, guest, member, group, vessel):
    """Keep a one-guest draft in step with its member; save only what changed (no history noise)."""
    at, check_in = _when(member, group, vessel)
    field, value = ("at", at) if kind is Transfer else ("check_in", check_in)
    if getattr(booking, field) != value:
        setattr(booking, field, value)
        booking.save()
    fields = _guest_fields(member, group)
    if any(getattr(guest, key) != value for key, value in fields.items()):
        for key, value in fields.items():
            setattr(guest, key, value)
        guest.save()


_GUEST_FK = {Transfer: "transfer", HotelStay: "stay"}


def _adopt(unlinked, member, group, uid):
    """A booking made before crew uids existed (guest with the same name and group, no uid) is linked to the member
    instead of getting a duplicate draft. True when one was adopted."""
    name = _guest_fields(member, group)["name"]
    for guest in unlinked:
        if name and guest.name == name and guest.group == group:
            guest.crew_uid = uid
            guest.save()
            unlinked.remove(guest)
            return True
    return False


def sync(vessel):
    """Bring the vessel's automatic bookings in step with all its Crew Change services."""
    members = crew_members(vessel)
    for kind, related in ((Transfer, vessel.transfers), (HotelStay, vessel.hotel_stays)):
        linked = {}  # uid -> [(booking, guest, number of guests)]
        for booking in related.prefetch_related("guests"):
            guests = list(booking.guests.all())
            uids = {g.crew_uid for g in guests if g.crew_uid}
            closed = booking.acct_closed  # settled by accounting: never changed or deleted here
            if booking.draft and not closed and not any(u in members and _wanted(kind, members[u][0]) for u in uids):
                booking.delete()
                continue
            for guest in guests:
                if guest.crew_uid:
                    linked.setdefault(guest.crew_uid, []).append((booking, guest, len(guests)))
        unlinked = [g for g in Guest.objects.filter(**{f"{_GUEST_FK[kind]}__vessel": vessel}, crew_uid="")]
        for uid, (member, group) in members.items():
            if not _wanted(kind, member):
                continue
            if uid not in linked:
                if not _adopt(unlinked, member, group, uid):
                    _create(kind, vessel, uid, member, group)
                continue
            for booking, guest, count in linked[uid]:
                if booking.draft and count == 1 and not booking.acct_closed:
                    _refresh(kind, booking, guest, member, group, vessel)


def incomplete(booking):
    """Still to finish: never saved by a person, or no cost / revenue yet."""
    if booking.cancelled:
        return False
    if isinstance(booking, HotelStay):
        return booking.draft or booking.cost_per_night is None or booking.revenue_per_night is None
    return booking.draft or booking.cost is None or booking.revenue is None


# ---- alerts --------------------------------------------------------------------------------------

EARLY_DAYS = 2  # an on-signer landing this many days (or more) before the vessel date breaks the visa terms
EARLY_LOOK_BACK = timedelta(days=60)
_INCOMPLETE = (
    (HotelStay, "Hotel", Q(draft=True) | Q(cost_per_night=None) | Q(revenue_per_night=None)),
    (Transfer, "Transport", Q(draft=True) | Q(cost=None) | Q(revenue=None)),
)


def booking_gaps(vessels, today, now):
    """vessel -> ["Hotel: <guests>", "Transport: <guests>", ...] for incomplete bookings of vessels that have sailed
    (sailing time passed, or no sailing time and dated before today)."""
    sailed = vessels.filter(Q(sailing_at__lte=now) | Q(sailing_at=None, date__lt=today))
    gaps = {}
    for kind, label, incomplete_q in _INCOMPLETE:
        bookings = kind.objects.filter(incomplete_q, vessel__in=sailed.values("pk"), cancelled=False)
        for booking in bookings.select_related("vessel").prefetch_related("guests").order_by("id"):
            names = ", ".join(g.name for g in booking.guests.all())
            gaps.setdefault(booking.vessel, []).append(f"{label}: {names}")
    return gaps


def _lands_early(person, vessel_date):
    moment = crew_moment(person, "on", vessel_date)
    lands = timezone.localdate(moment) if moment else None
    return bool(lands and lands <= vessel_date - timedelta(days=EARLY_DAYS))


def early_on_signers(service):
    """How many of this Crew Change's on-signers land EARLY_DAYS or more before the vessel date (visa or not)."""
    people = (service.data or {}).get("onSigners") or []
    return sum(1 for person in people if isinstance(person, dict) and _lands_early(person, service.vessel.date))


def early_arrivals(vessels, today):
    """On-signers landing EARLY_DAYS or more before their vessel's date, with no broken-visa charge entered yet."""
    services = (
        Service.objects.filter(service_type="Crew Change", vessel__in=vessels.filter(date__gte=today - EARLY_LOOK_BACK))
        .exclude(status="cancelled")
        .select_related("vessel")
        .only("id", "data", "vessel__id", "vessel__name", "vessel__date")
        .order_by("vessel__date", "vessel__id", "id")
    )
    rows = []
    for service in services:
        vessel = service.vessel
        for person in (service.data or {}).get("onSigners") or []:
            if not isinstance(person, dict):
                continue
            visa = person.get("brokenVisa") or {}
            if visa.get("cost") is not None or visa.get("revenue") is not None:
                continue  # handled (0 means "checked, no charge")
            if _lands_early(person, vessel.date):
                lands = timezone.localdate(crew_moment(person, "on", vessel.date))
                rows.append({"id": vessel.id, "name": vessel.name, "date": vessel.date.isoformat(),
                             "crew": person.get("name") or "", "lands": lands.isoformat()})
    return rows

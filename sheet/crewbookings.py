"""Automatic bookings for crew-change members.

Every crew member (on- and off-signer) gets a draft transfer, and a draft hotel stay while "Needs hotel" is on. A draft
is linked to its member by `Guest.crew_uid`; it follows the member (name, flight time) while it is still a draft with
that one guest, and is deleted when the member goes away (or switches Needs hotel off). A booking a person has saved
(`draft=False`) is never changed or deleted here. Runs inside the request's transaction, so history records the user.
"""

from datetime import datetime, time

from django.utils import timezone

from .logistics import crew_leg, crew_moment
from .models import Guest, HotelStay, Transfer

_GROUPS = (("onSigners", "on"), ("offSigners", "off"))


def crew_members(vessel):
    """uid -> (member, "on" / "off") for every Crew Change service of the vessel."""
    found = {}
    for service in vessel.services.filter(service_type="Crew Change").order_by("id"):
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


def sync(vessel):
    """Bring the vessel's automatic bookings in step with all its Crew Change services."""
    members = crew_members(vessel)
    for kind, related in ((Transfer, vessel.transfers), (HotelStay, vessel.hotel_stays)):
        linked = {}  # uid -> [(booking, guest, number of guests)]
        for booking in related.prefetch_related("guests"):
            guests = list(booking.guests.all())
            uids = {g.crew_uid for g in guests if g.crew_uid}
            if booking.draft and not any(u in members and _wanted(kind, members[u][0]) for u in uids):
                booking.delete()
                continue
            for guest in guests:
                if guest.crew_uid:
                    linked.setdefault(guest.crew_uid, []).append((booking, guest, len(guests)))
        for uid, (member, group) in members.items():
            if not _wanted(kind, member):
                continue
            if uid not in linked:
                _create(kind, vessel, uid, member, group)
                continue
            for booking, guest, count in linked[uid]:
                if booking.draft and count == 1:
                    _refresh(kind, booking, guest, member, group, vessel)


def incomplete(booking):
    """Still to finish: never saved by a person, or no cost / revenue yet."""
    if isinstance(booking, HotelStay):
        return booking.draft or booking.cost_per_night is None or booking.revenue_per_night is None
    return booking.draft or booking.cost is None or booking.revenue is None

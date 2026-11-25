"""Automatic bookings for crew-change members.

A crew member (on- or off-signer) gets a draft hotel stay while its Hotel button is pressed (`needsHotel`) and a draft
transfer while its Transport button is (`needsTransport`). What was typed on the crew card (`hotel`, `transport`) is
used, else the automatic values (from the flight, else the vessel date). A draft is linked to its member by
`Guest.crew_uid`; it follows the member (name, typed values, flight time) while it is still a draft with that one
guest, and is deleted when the member goes away (or the button is released). A booking a person has saved
(`draft=False`) is never changed or deleted here. Runs inside the request's transaction, so history records the user.
"""

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from .accounting import LOCKED
from .errors import BadRequest
from .logistics import MONEY_KEYS, crew_leg, crew_moment
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
    """(transfer time, hotel check-in) for the member from the flight, else the vessel date."""
    moment = crew_moment(member, group, vessel.date)
    at = moment or timezone.make_aware(datetime.combine(vessel.date, time()))
    check_in = timezone.localdate(moment) if moment and group == "on" else vessel.date
    return at, check_in


_NAME_FIELD = {"airport": "airport", "hotel": "hotel", "port": "port_name"}


def _transfer_fields(member, group, vessel):
    """The draft transfer's fields: what was typed on the crew card, else the automatic values."""
    typed = member.get("transport") or {}
    automatic = ("airport", "port") if group == "on" else ("port", "airport")
    from_place, to_place = typed.get("from") or automatic[0], typed.get("to") or automatic[1]
    if from_place == to_place:  # only one end typed and it is the other's automatic place
        to_place = next(p for p in (automatic[1], automatic[0], "hotel") if p != from_place)
    fields = {"from_place": from_place, "to_place": to_place, "airport": "", "hotel": "", "port_name": ""}
    for end, place in (("from", from_place), ("to", to_place)):
        if typed.get(end) == place and typed.get(f"{end}Name"):
            fields[_NAME_FIELD[place]] = typed[f"{end}Name"]
    at = _typed_moment(typed.get("at"))
    fields["at"] = at or _when(member, group, vessel)[0]
    return fields


def _typed_moment(text):
    if not text:
        return None
    try:
        return timezone.make_aware(datetime.fromisoformat(text))
    except ValueError:
        return None


def _stay_fields(member, group, vessel):
    """The draft hotel stay's fields: what was typed on the crew card, else the automatic values (1 night)."""
    typed = member.get("hotel") or {}
    check_in = _typed_day(typed.get("checkIn")) or _when(member, group, vessel)[1]
    check_out = _typed_day(typed.get("checkOut"))
    nights = (check_out - check_in).days if check_out and check_out > check_in else 1
    return {"hotel": typed.get("name") or "", "check_in": check_in, "nights": nights}


def _typed_day(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date() if text else None
    except ValueError:
        return None


def _wanted(kind, member):
    return bool(member.get("needsTransport" if kind is Transfer else "needsHotel"))


def _fields(kind, member, group, vessel):
    return (_transfer_fields if kind is Transfer else _stay_fields)(member, group, vessel)


def _create(kind, vessel, uid, member, group):
    booking = kind.objects.create(vessel=vessel, draft=True, **_fields(kind, member, group, vessel))
    Guest.objects.create(**{_GUEST_FK[kind]: booking}, crew_uid=uid, **_guest_fields(member, group))


def _refresh(kind, booking, guest, member, group, vessel):
    """Keep a one-guest draft in step with its member; save only what changed (no history noise)."""
    fields = _fields(kind, member, group, vessel)
    if any(getattr(booking, key) != value for key, value in fields.items()):
        for key, value in fields.items():
            setattr(booking, key, value)
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


# ---- cancelling a crew change's saved bookings -------------------------------------------------

BOOKING_KINDS = {"hotel": (HotelStay, "hotels"), "transfer": (Transfer, "transfers")}


def _crew_uids(service):
    data = service.data or {}
    return {m["uid"] for key, _group in _GROUPS for m in data.get(key) or [] if isinstance(m, dict) and m.get("uid")}


def saved_bookings(service):
    """[(kind, booking)] of a Crew Change's saved (non-draft) bookings: those with a guest copied from its crew."""
    uids = _crew_uids(service) if service.service_type == "Crew Change" else set()
    found = []
    for kind, (model, _plural) in BOOKING_KINDS.items():
        bookings = (model.objects.filter(vessel_id=service.vessel_id, draft=False, guests__crew_uid__in=uids)
                    .distinct().prefetch_related("guests").order_by("id")) if uids else []
        found += [(kind, booking) for booking in bookings]
    return found


def saved_by_member(service):
    """{crew uid: {"hotel": bool, "transport": bool}} for the members of a Crew Change that have a hotel stay /
    transfer saved by a person (not a draft); members with neither are left out."""
    found = {}
    for kind, booking in saved_bookings(service):
        key = "hotel" if kind == "hotel" else "transport"
        for guest in booking.guests.all():
            if guest.crew_uid:
                found.setdefault(guest.crew_uid, {"hotel": False, "transport": False})[key] = True
    uids = _crew_uids(service)
    return {uid: value for uid, value in found.items() if uid in uids}


def booking_ref(kind, booking):
    """What the service dialog lists for one booking."""
    if kind == "hotel":
        what = f"Hotel · {booking.hotel or 'no hotel yet'} · {booking.check_in:%d/%m/%Y}"
    else:
        what = f"Transfer · {booking.from_place} → {booking.to_place} · {timezone.localtime(booking.at):%d/%m/%Y %H:%M}"
    return {"kind": kind, "id": booking.id, "label": what, "guests": ", ".join(g.name for g in booking.guests.all()),
            "cancelled": booking.cancelled, "closed": booking.acct_closed}


def cancel_bookings(service, refs, zero_money=True):
    """Cancel the listed saved bookings of a cancelled Crew Change (cleaned refs [(kind, id)]): each is marked
    cancelled, its money set to 0 when `zero_money` (the person has money.edit; a fee can be typed later) and its
    version raised. Anything not that crew change's,
    or closed by accounting, refuses the whole save."""
    if not refs:
        return []
    if service.service_type != "Crew Change" or service.status != "cancelled":
        raise BadRequest("Only a cancelled crew change cancels its bookings.")
    own = {(kind, booking.pk) for kind, booking in saved_bookings(service)}
    done = []
    for kind, pk in refs:
        if (kind, pk) not in own:
            raise BadRequest("That booking is not one of this crew change's.")
        model, plural = BOOKING_KINDS[kind]
        booking = model.objects.select_for_update().get(pk=pk)
        if booking.acct_closed:
            raise BadRequest(LOCKED)
        if booking.cancelled:
            continue
        booking.cancelled = True
        for key in MONEY_KEYS[plural] if zero_money else ():
            setattr(booking, key, 0)
        booking.version += 1
        booking.save()
        done.append((kind, pk))
    return done


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

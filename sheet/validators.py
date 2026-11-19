"""Input validation. Everything that arrives from the browser is cleaned here before it is stored."""

import math
import re
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .constants import (
    GUEST_GROUPS,
    MAX_GUESTS,
    MAX_NIGHTS,
    MULTI_TYPES,
    OPTION_KINDS,
    PLACE_KEYS,
    PORT_KEYS,
    SINGLE_EXTRAS,
    SUMMARY_FIELDS,
    TIME_KEYS,
    TIME_LABELS,
    is_delayed,
)
from .errors import BadRequest
from .models import Option

MAX_ENTRIES = 100
MAX_CREW = 60
MAX_SEGMENTS = 12
MAX_AMOUNT = 1e10  # same ceiling as booking money
UID_RE = re.compile(r"^[0-9a-f]{12}$")  # a crew member's stable identity (links its automatic bookings)
MAX_RATE = 1_000_000
KIND_LABELS = dict(OPTION_KINDS)


def _text(value, limit=200):
    return str(value if value is not None else "").strip()[:limit]


def _short(value, limit, label):
    """Trimmed text; refused (not cut) when longer than `limit` characters."""
    text = str(value if value is not None else "").strip()
    if len(text) > limit:
        raise BadRequest(f"{label} is too long (at most {limit} characters).")
    return text


def _parse_number(value, label):
    """None when empty; a finite float otherwise, refused when it is not a number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise BadRequest(f"{label} must be a number.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise BadRequest(f"{label} must be a number.") from None
    if not math.isfinite(result):
        raise BadRequest(f"{label} must be a number.")
    return result


def _amount(value, label):
    """An optional amount, quantity or weight: a number of 0 or more."""
    result = _parse_number(value, label)
    if result is None:
        return None
    if result < 0:
        raise BadRequest(f"{label} must be 0 or more.")
    if result >= MAX_AMOUNT:
        raise BadRequest(f"{label} is too large.")
    return result


def _rate(value):
    """An optional exchange rate: above 0. 0 means empty (use the month rate), as the money maths already treats it."""
    result = _parse_number(value, "Exchange rate")
    if result == 0:
        return None
    if result is not None and not 0 < result < MAX_RATE:
        raise BadRequest("Exchange rate must be a number above 0.")
    return result


def listed(kind, value, port, current=""):
    """A value from the Master data list `kind` for `port` (that port's or All ports'), or empty.
    The value already saved on the record (`current`) stays allowed even if it left the list."""
    label = KIND_LABELS[kind]
    text = _short(value, 100, label)
    if not text or text == (current or ""):
        return text
    if not Option.objects.filter(kind=kind, value=text, port__in=("", port or "")).exists():
        raise BadRequest(f"{label}: choose a value from the Master data {label} list for this port.")
    return text


def _currency(value):
    return "USD" if value == "USD" else "EGP"


def _as_list(value):
    return value if isinstance(value, list) else []


def _as_dict(value):
    return value if isinstance(value, dict) else {}


# ---- service data ---------------------------------------------------------------------------


def _crew_member(raw):
    personal = _as_dict(raw.get("personalStructured"))
    segments = _as_list(_as_dict(raw.get("flightStructured")).get("segments"))
    segment_keys = ("flightNo", "airline", "departureCity", "departureTime", "arrivalCity", "arrivalTime", "date")
    return {
        "name": _text(raw.get("name"), 120),
        "flightData": _text(raw.get("flightData"), 4000),
        "personalData": _text(raw.get("personalData"), 2000),
        "personalStructured": {
            key: _text(personal.get(key), 120)
            for key in ("name", "firstName", "lastName", "rank", "nationality")
            if personal.get(key)
        },
        "flightStructured": {
            "segments": [
                {key: _text(seg.get(key), 160) for key in segment_keys}
                for seg in segments[:MAX_SEGMENTS]
                if isinstance(seg, dict)
            ]
        },
    }


def _broken_visa(raw):
    """An on-signer's broken-visa charge (landed too early): cost / revenue, each optional."""
    raw = _as_dict(raw)
    return {
        "cost": _amount(raw.get("cost"), "Broken visa cost"),
        "costCurrency": _currency(raw.get("costCurrency")),
        "revenue": _amount(raw.get("revenue"), "Broken visa revenue"),
        "revenueCurrency": _currency(raw.get("revenueCurrency")),
    }


def _clean_crew_change(raw):
    """On- and off-signers. Each keeps a valid uid it was sent (once per crew change) or gets a new one."""
    seen = set()
    cleaned = {}
    for group in ("onSigners", "offSigners"):
        members = []
        for item in _as_list(raw.get(group))[:MAX_CREW]:
            if not isinstance(item, dict):
                continue
            member = _crew_member(item)
            uid = item.get("uid")
            if not (isinstance(uid, str) and UID_RE.match(uid)) or uid in seen:
                uid = secrets.token_hex(6)
                while uid in seen:
                    uid = secrets.token_hex(6)
            seen.add(uid)
            member["uid"] = uid
            member["needsHotel"] = bool(item.get("needsHotel"))
            if group == "onSigners":
                member["brokenVisa"] = _broken_visa(item.get("brokenVisa"))
            members.append(member)
        cleaned[group] = members
    return cleaned


def _clean_multi(service_type, raw):
    entries = []
    raw_entries = _as_list(raw.get("entries"))
    if len(raw_entries) > MAX_ENTRIES:
        raise BadRequest(f"At most {MAX_ENTRIES} lines per service.")
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        line = f" (line {len(entries) + 1})"
        item = {
            "awb": _short(entry.get("awb"), 60, "AWB" + line),
            "cost": _amount(entry.get("cost"), "Cost" + line),
            "costCurrency": _currency(entry.get("costCurrency")),
            "revenue": _amount(entry.get("revenue"), "Revenue" + line),
            "revenueCurrency": _currency(entry.get("revenueCurrency")),
        }
        if service_type == "Delivery Parcels":
            item["weight"] = _amount(entry.get("weight"), "Weight" + line)
        entries.append(item)
    return {"entries": entries, "exchangeRate": _rate(raw.get("exchangeRate"))}


def _clean_cash_to_master(raw):
    percentage = _parse_number(raw.get("percentage"), "Percentage")
    if percentage is not None and not 0 <= percentage <= 100:
        raise BadRequest("Percentage must be from 0 to 100.")
    return {
        "amount": _amount(raw.get("amount"), "Amount"),
        "amountCurrency": _currency(raw.get("amountCurrency")),
        "shareMode": "fixed" if raw.get("shareMode") == "fixed" else "percent",
        "percentage": percentage,
        "fixedRevenue": _amount(raw.get("fixedRevenue"), "Fixed revenue"),
        "exchangeRate": _rate(raw.get("exchangeRate")),
    }


def _service_money(raw):
    """The cost / revenue fields every single-priced service has (Crew Change and Others / Remarks too)."""
    return {
        "cost": _amount(raw.get("cost"), "Cost"),
        "costCurrency": _currency(raw.get("costCurrency")),
        "revenue": _amount(raw.get("revenue"), "Revenue"),
        "revenueCurrency": _currency(raw.get("revenueCurrency")),
        "exchangeRate": _rate(raw.get("exchangeRate")),
    }


def _clean_single(service_type, raw):
    cleaned = _service_money(raw)
    extra = SINGLE_EXTRAS.get(service_type)
    if extra == "quantity":
        cleaned["quantity"] = _amount(raw.get("quantity"), "Quantity")
    elif extra:
        cleaned[extra] = _short(raw.get(extra), 160, "Name")
    return cleaned


def clean_service_data(service_type, raw):
    """Return a sanitised copy of a service's data for its type; unknown keys are dropped."""
    raw = _as_dict(raw)
    if service_type == "Others / Remarks":
        return {"note": _short(raw.get("note"), 1000, "Note"), **_service_money(raw)}
    if service_type == "Crew Change":
        return {**_clean_crew_change(raw), **_service_money(raw)}
    if service_type in MULTI_TYPES:
        return _clean_multi(service_type, raw)
    if service_type == "Cash to Master":
        return _clean_cash_to_master(raw)
    return _clean_single(service_type, raw)


# ---- vessels --------------------------------------------------------------------------------


def clean_summary(raw):
    """Optional vendor / invoice notes: only the known fields, each trimmed."""
    raw = _as_dict(raw)
    cleaned = {key: _short(raw.get(key), 80, key) for key in SUMMARY_FIELDS}
    return {key: value for key, value in cleaned.items() if value}


def _local_datetime(value, label):
    """'2026-11-13T08:30' (Cairo time) -> aware datetime; empty -> None."""
    text = _text(value, 40)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        raise BadRequest(f"{label}: enter a valid date and time.") from None
    if not 2000 <= parsed.year <= 2100:
        raise BadRequest(f"{label}: enter a valid date and time.")
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


# (earlier, later) pairs that must be in order when both are filled in. Berthing vs. operations is left
# free on purpose: operations at anchorage can start before the vessel berths.
_TIME_ORDER = [
    ("arrival_at", "berthing_at"),
    ("arrival_at", "ops_start_at"),
    ("arrival_at", "ops_end_at"),
    ("arrival_at", "sailing_at"),
    ("berthing_at", "sailing_at"),
    ("ops_start_at", "ops_end_at"),
    ("ops_start_at", "sailing_at"),
    ("ops_end_at", "sailing_at"),
]


def _check_time_order(times):
    for earlier, later in _TIME_ORDER:
        if times[earlier] and times[later] and times[later] < times[earlier]:
            raise BadRequest(f"{TIME_LABELS[later]} cannot be before {TIME_LABELS[earlier].lower()}.")


def clean_delay_reason(data, times, port, existing=None):
    """A reason from the Master data "delay" list, required when the vessel berthed more than DELAY_LIMIT after it
    arrived and refused otherwise. A save without the key keeps the stored reason (and is checked like it)."""
    saved = getattr(existing, "delay_reason", "")
    sent = data["delay_reason"] if "delay_reason" in data else saved
    if is_delayed(times["arrival_at"], times["berthing_at"]):
        reason = listed("delay", sent, port, saved)
        if not reason:
            raise BadRequest("Choose a delay reason (berthed more than 2 hours after arrival).")
        return reason
    if _text(sent, 200):
        raise BadRequest("Not delayed (berthed within 2 hours): clear the delay reason.")
    return ""


def clean_agent(value, port, current=""):
    """An agent from the Master data Agent list of `port` (or All ports), or empty."""
    return listed("agent", value, port, current)


def clean_vessel(data, profile, existing=None):
    """Validate vessel input. Port users are always pinned to their own port."""
    name = _short(data.get("name"), 120, "Vessel name")
    if not name:
        raise BadRequest("Vessel name is required.")
    try:
        when = date.fromisoformat(str(data.get("date", "")))
    except ValueError:
        raise BadRequest("Enter a valid date.") from None

    if profile.port:
        port = profile.port
    else:
        port = data.get("port") or (existing.port if existing else "alexandria")
        if port not in PORT_KEYS:
            raise BadRequest("Unknown port.")

    times = {key: _local_datetime(data.get(key), TIME_LABELS[key]) for key in TIME_KEYS}
    _check_time_order(times)
    if times["sailing_at"]:  # once it has sailed, the vessel's date is its sailing day (Cairo)
        when = timezone.localdate(times["sailing_at"])

    # OPR and POC: required for a new vessel and can't be emptied once set (older vessels without them still save).
    opr = listed("opr", data.get("opr"), port, getattr(existing, "opr", ""))
    poc = listed("poc", data.get("poc"), port, getattr(existing, "poc", ""))
    for value, field, message in ((opr, "opr", "Choose an OPR."), (poc, "poc", "Choose a POC.")):
        if not value and (existing is None or getattr(existing, field)):
            raise BadRequest(message)

    return {
        "name": name,
        "opr": opr,
        "poc": poc,
        "arrival_agent": clean_agent(data.get("arrival_agent"), port, getattr(existing, "arrival_agent", "")),
        "sailing_agent": clean_agent(data.get("sailing_agent"), port, getattr(existing, "sailing_agent", "")),
        "date": when,
        "port": port,
        "summary": clean_summary(data.get("summary")),
        "delay_reason": clean_delay_reason(data, times, port, existing),
        **times,
    }


# ---- hotels and transport ---------------------------------------------------------------------

# Booking field -> Master data list it must come from (checked once the vessel, and so the port, is known).
BOOKING_LISTS = {"hotel": "hotel", "airport": "airport", "port_name": "port"}


def check_booking_lists(cleaned, port, existing=None):
    """Hotel / airport / port of a cleaned booking must be in Master data for the vessel's port (or saved already)."""
    for field, kind in BOOKING_LISTS.items():
        if cleaned.get(field):
            listed(kind, cleaned[field], port, getattr(existing, field, ""))


def clean_guests(raw):
    """1..MAX_GUESTS guests, each a copy of a crew member's details (or typed by hand)."""
    if not isinstance(raw, list) or not raw:
        raise BadRequest("Add at least one guest.")
    if len(raw) > MAX_GUESTS:
        raise BadRequest(f"At most {MAX_GUESTS} guests per booking.")
    guests = []
    for item in raw:
        item = _as_dict(item)
        name = _short(str(item.get("name") or "").upper(), 120, "Guest name")
        if not name:
            raise BadRequest("Every guest needs a name.")
        group = item.get("group")
        guests.append(
            {
                "name": name,
                "rank": _short(item.get("rank"), 60, "Guest rank"),
                "nationality": _short(item.get("nationality"), 60, "Guest nationality"),
                "group": group if group in GUEST_GROUPS else "",
                "flight": _short(item.get("flight"), 20, "Guest flight"),
                "crew_uid": uid if isinstance(uid := item.get("crew_uid"), str) and UID_RE.match(uid) else "",
            }
        )
    return guests


def _money(value, message):
    """An optional non-negative amount as Decimal (None when empty)."""
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise BadRequest(message) from None
    if not amount.is_finite() or amount < 0 or amount >= Decimal("1e10"):
        raise BadRequest(message)
    return amount.quantize(Decimal("0.01"))


def _price_fields(data, cost_key, revenue_key):
    """Cost (what we pay) and revenue (what we get), each optional with its own currency, plus one optional rate."""
    rate = data.get("exchange_rate")
    if rate in (None, ""):
        rate = None
    else:
        try:
            rate = Decimal(str(rate))
        except InvalidOperation:
            raise BadRequest("Exchange rate must be a positive number.") from None
        if not rate.is_finite() or not 0 < rate < 1_000_000:
            raise BadRequest("Exchange rate must be a positive number.")
    return {
        cost_key: _money(data.get(cost_key), "Prices cannot be negative."),
        "cost_currency": _currency(data.get("cost_currency")),
        revenue_key: _money(data.get(revenue_key), "Prices cannot be negative."),
        "revenue_currency": _currency(data.get("revenue_currency")),
        "exchange_rate": rate,
    }


def clean_hotel_stay(data):
    """One room: hotel, check-in, nights (1..MAX_NIGHTS), optional cost / revenue per room per night, guests."""
    guests = clean_guests(data.get("guests"))  # first: the guests are the first part of the form
    hotel = _short(data.get("hotel"), 100, "Hotel")
    if not hotel:
        raise BadRequest("Choose a hotel.")
    try:
        check_in = date.fromisoformat(str(data.get("check_in", "")))
    except ValueError:
        raise BadRequest("Enter a valid check-in date.") from None
    if not 2000 <= check_in.year <= 2100:
        raise BadRequest("Enter a valid check-in date.")
    nights = data.get("nights")
    if isinstance(nights, str) and nights.strip().isdigit():
        nights = int(nights)
    if isinstance(nights, bool) or not isinstance(nights, int) or not 1 <= nights <= MAX_NIGHTS:
        raise BadRequest(f"Nights must be a whole number from 1 to {MAX_NIGHTS}.")
    return {
        "hotel": hotel,
        "check_in": check_in,
        "nights": nights,
        **_price_fields(data, "cost_per_night", "revenue_per_night"),
        "guests": guests,
    }


_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def clean_transfer(data):
    """One car trip between airport / hotel / port, at a date and time (Cairo), with guests."""
    guests = clean_guests(data.get("guests"))  # first: the guests are the first part of the form
    from_place, to_place = data.get("from_place"), data.get("to_place")
    if from_place not in PLACE_KEYS or to_place not in PLACE_KEYS:
        raise BadRequest("Choose where from and where to.")
    if from_place == to_place:
        raise BadRequest("From and To must be different.")
    ends = (from_place, to_place)
    named = {}  # which hotel / airport / port, required only when that end is used
    for place, key, message in (("hotel", "hotel", "Choose a hotel."), ("airport", "airport", "Choose an airport."),
                                ("port", "port_name", "Choose a port.")):
        named[key] = _short(data.get(key), 100, place.capitalize()) if place in ends else ""
        if place in ends and not named[key]:
            raise BadRequest(message)
    text = _text(data.get("at"), 40)
    if not _DATE_TIME.match(text):
        raise BadRequest("Enter the date and time.")
    try:
        at = _local_datetime(text, "Date and time")
    except BadRequest:
        raise BadRequest("Enter the date and time.") from None
    return {
        "from_place": from_place,
        "to_place": to_place,
        **named,
        "at": at,
        **_price_fields(data, "cost", "revenue"),
        "guests": guests,
    }


# ---- port closures ----------------------------------------------------------------------------


def clean_closure(data, profile, existing=None):
    """Validate a port closure. Port users are always pinned to their own port; the reason is from the Master data
    "closure" list of that port (or All ports); an empty Reopened means the port is still closed."""
    data = _as_dict(data)
    if profile.port:
        port = profile.port
    else:
        port = data.get("port") or (existing.port if existing else "")
        if port not in PORT_KEYS:
            raise BadRequest("Unknown port.")
    start_at = _local_datetime(data.get("start_at"), "Closed from")
    if start_at is None:
        raise BadRequest("Closed from is required.")
    end_at = _local_datetime(data.get("end_at"), "Reopened")
    if end_at is not None and end_at < start_at:
        raise BadRequest("Reopened cannot be before closed from.")
    reason = listed("closure", data.get("reason"), port, getattr(existing, "reason", ""))
    if not reason:
        raise BadRequest("Choose a closure reason.")
    return {"port": port, "start_at": start_at, "end_at": end_at, "reason": reason,
            "notes": _short(data.get("notes"), 500, "Notes")}

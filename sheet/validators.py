"""Input validation. Everything that arrives from the browser is cleaned here before it is stored."""

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .constants import (
    BULK_MAX_ROWS,
    GUEST_GROUPS,
    MAX_GUESTS,
    MAX_NIGHTS,
    MULTI_TYPES,
    PLACE_KEYS,
    PORT_KEYS,
    SINGLE_EXTRAS,
    SUMMARY_FIELDS,
    TIME_KEYS,
    TIME_LABELS,
)
from .errors import BadRequest

MAX_ENTRIES = 100
MAX_CREW = 60
MAX_SEGMENTS = 12


def _text(value, limit=200):
    return str(value if value is not None else "").strip()[:limit]


def _number(value):
    """A finite float, or None when the field is empty or not a number."""
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


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


def _clean_crew_change(raw):
    return {
        group: [_crew_member(m) for m in _as_list(raw.get(group))[:MAX_CREW] if isinstance(m, dict)]
        for group in ("onSigners", "offSigners")
    }


def _clean_multi(service_type, raw):
    entries = []
    for entry in _as_list(raw.get("entries"))[:MAX_ENTRIES]:
        if not isinstance(entry, dict):
            continue
        item = {
            "awb": _text(entry.get("awb"), 60),
            "cost": _number(entry.get("cost")),
            "costCurrency": _currency(entry.get("costCurrency")),
            "revenue": _number(entry.get("revenue")),
            "revenueCurrency": _currency(entry.get("revenueCurrency")),
        }
        if service_type == "Delivery Parcels":
            item["weight"] = _number(entry.get("weight"))
        entries.append(item)
    return {"entries": entries, "exchangeRate": _number(raw.get("exchangeRate"))}


def _clean_cash_to_master(raw):
    percentage = _number(raw.get("percentage"))
    if percentage is not None:
        percentage = max(0.0, min(100.0, percentage))
    return {
        "amount": _number(raw.get("amount")),
        "amountCurrency": _currency(raw.get("amountCurrency")),
        "shareMode": "fixed" if raw.get("shareMode") == "fixed" else "percent",
        "percentage": percentage,
        "fixedRevenue": _number(raw.get("fixedRevenue")),
        "exchangeRate": _number(raw.get("exchangeRate")),
    }


def _service_money(raw):
    """The cost / revenue fields every single-priced service has (Crew Change and Others / Remarks too)."""
    return {
        "cost": _number(raw.get("cost")),
        "costCurrency": _currency(raw.get("costCurrency")),
        "revenue": _number(raw.get("revenue")),
        "revenueCurrency": _currency(raw.get("revenueCurrency")),
        "exchangeRate": _number(raw.get("exchangeRate")),
    }


def _clean_single(service_type, raw):
    cleaned = _service_money(raw)
    extra = SINGLE_EXTRAS.get(service_type)
    if extra == "quantity":
        cleaned["quantity"] = _number(raw.get("quantity"))
    elif extra:
        cleaned[extra] = _text(raw.get(extra), 160)
    return cleaned


def clean_service_data(service_type, raw):
    """Return a sanitised copy of a service's data for its type; unknown keys are dropped."""
    raw = _as_dict(raw)
    if service_type == "Others / Remarks":
        return {"note": _text(raw.get("note"), 1000), **_service_money(raw)}
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
    return {key: _text(raw[key], 80) for key in SUMMARY_FIELDS if _text(raw.get(key), 80)}


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


def clean_vessel(data, profile, existing=None):
    """Validate vessel input. Port users are always pinned to their own port."""
    name = _text(data.get("name"), 120)
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

    return {
        "name": name,
        "opr": _text(data.get("opr"), 100),
        "poc": _text(data.get("poc"), 100),
        "agent": _text(data.get("agent"), 100),
        "date": when,
        "port": port,
        "summary": clean_summary(data.get("summary")),
        **times,
    }


def clean_bulk(rows, profile, default_port=None):
    """Validate many new vessels at once. Nothing is saved unless every row is valid."""
    if not isinstance(rows, list) or not rows:
        raise BadRequest("Add at least one vessel.")
    if len(rows) > BULK_MAX_ROWS:
        raise BadRequest(f"Add at most {BULK_MAX_ROWS} vessels at a time.")
    cleaned, problems = [], {}
    for number, raw in enumerate(rows, start=1):
        try:
            if not isinstance(raw, dict):
                raise BadRequest("Invalid row.")
            cleaned.append(clean_vessel({"port": default_port, **raw} if default_port else raw, profile))
        except BadRequest as error:
            problems[number] = str(error)
    if problems:
        shown = "; ".join(f"row {number}: {message}" for number, message in list(problems.items())[:5])
        raise BadRequest(f"Nothing was saved. {shown}", rows=problems)
    return cleaned


# ---- hotels and transport ---------------------------------------------------------------------


def clean_guests(raw):
    """1..MAX_GUESTS guests, each a copy of a crew member's details (or typed by hand)."""
    if not isinstance(raw, list) or not raw:
        raise BadRequest("Add at least one guest.")
    if len(raw) > MAX_GUESTS:
        raise BadRequest(f"At most {MAX_GUESTS} guests per booking.")
    guests = []
    for item in raw:
        item = _as_dict(item)
        name = _text(item.get("name"), 120).upper()
        if not name:
            raise BadRequest("Every guest needs a name.")
        group = item.get("group")
        guests.append(
            {
                "name": name,
                "rank": _text(item.get("rank"), 60),
                "nationality": _text(item.get("nationality"), 60),
                "group": group if group in GUEST_GROUPS else "",
                "flight": _text(item.get("flight"), 20),
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


def _price_fields(data, price_key):
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
        price_key: _money(data.get(price_key), "Prices cannot be negative."),
        "currency": _currency(data.get("currency")),
        "exchange_rate": rate,
    }


def clean_hotel_stay(data):
    """One room: hotel, check-in, nights (1..MAX_NIGHTS), optional price per room per night, guests."""
    guests = clean_guests(data.get("guests"))  # first: the guests are the first part of the form
    hotel = _text(data.get("hotel"), 100)
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
        **_price_fields(data, "price_per_night"),
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
        named[key] = _text(data.get(key), 100) if place in ends else ""
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
        **_price_fields(data, "price"),
        "guests": guests,
    }

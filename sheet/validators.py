"""Input validation. Everything that arrives from the browser is cleaned here before it is stored."""

import math
import re
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from .constants import (
    BILLING,
    CANCEL_REASON_MAX,
    GUEST_GROUPS,
    MAX_GUESTS,
    MAX_NIGHTS,
    MULTI_TYPES,
    OPTION_KINDS,
    PLACE_KEYS,
    PORT_KEYS,
    RATE_UNITS,
    SERVICE_STATUSES,
    SINGLE_EXTRAS,
    SUMMARY_FIELDS,
    TIME_KEYS,
    TIME_LABELS,
    is_delayed,
)
from .errors import BadRequest
from .models import Customer, Option, Ship

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


def listed(kind, value, port, current="", also=()):
    """A value from the Master data list `kind` for `port` (that port's or All ports'), or empty.
    The value already saved on the record (`current`) stays allowed even if it left the list, and so do the
    values in `also` (a vessel's ship's OPR)."""
    label = KIND_LABELS[kind]
    text = _short(value, 100, label)
    if not text or text == (current or "") or text in also:
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


def clean_service_billing(payload, vessel, existing=None):
    """(billing, billing party) of a service. A save without a key keeps the stored value; a new service starts On
    account, billed to its vessel's ship's customer. The party is a customer id (active, or the saved one) or null."""
    billing = payload.get("billing", getattr(existing, "billing", "account"))
    if not isinstance(billing, str) or billing not in BILLING:
        raise BadRequest("Choose Cash or On account.")
    current = getattr(existing, "billing_party", None)
    if "billing_party" in payload:
        party = pick_customer(payload.get("billing_party"), current, "Billing party")
    elif existing is not None:
        party = current
    else:
        ship = vessel.ship
        party = ship.customer if ship is not None and ship.customer is not None and ship.customer.active else None
    return billing, party


RECEIPT_MAX_LINES = 40


def clean_service_status(payload, existing=None):
    """(status, cancel reason) of a service. A save without the key keeps the stored value (a new service starts In
    progress). The reason is required when Cancelled and refused otherwise (the dialog clears it)."""
    status = payload.get("status", getattr(existing, "status", "in_progress"))
    if not isinstance(status, str) or status not in SERVICE_STATUSES:
        raise BadRequest("Choose a status: In progress, Completed or Cancelled.")
    sent = payload.get("cancel_reason", getattr(existing, "cancel_reason", "") if status == "cancelled" else "")
    reason = _short(sent, CANCEL_REASON_MAX, "The cancellation reason")
    if status == "cancelled" and not reason:
        raise BadRequest("Write why the service was cancelled.")
    if status != "cancelled" and reason:
        raise BadRequest("Only a cancelled service has a cancellation reason: clear it.")
    return status, reason


def clean_receipt(raw):
    """The master receipt's edited text (never stored): limits refused, not cut; the services are required."""
    raw = _as_dict(raw)
    cleaned = {
        "port": _short(raw.get("port"), 80, "Port"),
        "date": _short(raw.get("date"), 20, "Date"),
        "vessel": _short(raw.get("vessel"), 80, "Vessel"),
        "services": _short(raw.get("services"), 2000, "Services"),
    }
    if not cleaned["services"]:
        raise BadRequest("Write the services.")
    if len(cleaned["services"].splitlines()) > RECEIPT_MAX_LINES:
        raise BadRequest(f"Services: at most {RECEIPT_MAX_LINES} lines.")
    return cleaned


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
        port = data.get("port") or (existing.port if existing else "")
        if not port:  # an admin's new vessel: the port is chosen, never assumed
            raise BadRequest("Choose a port.")
        if port not in PORT_KEYS:
            raise BadRequest("Unknown port.")

    times = {key: _local_datetime(data.get(key), TIME_LABELS[key]) for key in TIME_KEYS}
    _check_time_order(times)
    if times["sailing_at"]:  # once it has sailed, the vessel's date is its sailing day (Cairo)
        when = timezone.localdate(times["sailing_at"])

    ship = clean_vessel_ship(data, existing)
    # OPR and POC: required for a new vessel and can't be emptied once set (older vessels without them still save).
    opr = listed("opr", data.get("opr"), port, getattr(existing, "opr", ""), also=(ship.opr,) if ship else ())
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
        "ship": ship,
        **times,
    }


NEED_SHIP = "Choose a ship, or add a new one."


def clean_vessel_ship(data, existing=None):
    """The vessel's ship (`ship_id`): required for a new vessel, kept when the key is not sent, never removed once
    linked; an inactive ship only if it is the one already saved."""
    current = getattr(existing, "ship", None)
    if "ship_id" not in data and existing is not None:
        return current
    value = data.get("ship_id")
    if value is None:
        if existing is None or current is not None:
            raise BadRequest(NEED_SHIP)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(NEED_SHIP)
    if current is not None and value == current.id:
        return current
    ship = Ship.objects.filter(pk=value, active=True).first()
    if ship is None:
        raise BadRequest(NEED_SHIP)
    return ship


# ---- ships ----------------------------------------------------------------------------------

IMO_RE = re.compile(r"^[0-9]{7}$")


def imo_valid(text):
    """A real IMO number: 7 digits whose last is the check digit (first six weighted 7..2, sum mod 10)."""
    if not isinstance(text, str) or not IMO_RE.match(text):
        return False
    total = sum(int(digit) * weight for digit, weight in zip(text[:6], range(7, 1, -1), strict=True))
    return total % 10 == int(text[6])


def _flag(value):
    return value is True


def pick_customer(value, current=None, label="Customer"):
    """A customer by id (active, or the one already saved), or None when empty."""
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"{label}: choose one from the list.")
    if current is not None and value == current.id:
        return current
    found = Customer.objects.filter(pk=value, active=True).first()
    if found is None:
        raise BadRequest(f"{label}: choose one from the list.")
    return found


def clean_ship(data, profile, existing=None):
    """A ship: name (upper case), IMO (required unless "No IMO" is ticked), OPR from Master data, customer."""
    name = _short(data.get("name"), 120, "Ship name").upper()
    if not name:
        raise BadRequest("Ship name is required.")
    if _flag(data.get("no_imo")):
        imo = ""
    else:
        imo = _short(data.get("imo"), 20, "IMO").replace(" ", "")
        if not imo:
            raise BadRequest("Enter the IMO number, or tick No IMO.")
        if not imo_valid(imo):
            raise BadRequest("IMO: enter the 7-digit IMO number (its last digit doesn't match).")
        clash = Ship.objects.filter(imo=imo).exclude(pk=getattr(existing, "pk", None))
        if clash.exists():
            raise BadRequest("IMO: another ship already has this number.")
    current_opr = getattr(existing, "opr", "")
    opr = _short(data.get("opr"), 100, "OPR")
    if opr and opr != current_opr:
        if profile.port:
            listed("opr", opr, profile.port, current_opr)
        elif not Option.objects.filter(kind="opr", value=opr).exists():
            raise BadRequest("OPR: choose a value from the Master data OPR list.")
    active = data.get("active", getattr(existing, "active", True))
    if not isinstance(active, bool):
        raise BadRequest("Active must be yes or no.")
    return {
        "name": name,
        "imo": imo,
        "opr": opr,
        "customer": pick_customer(data.get("customer"), getattr(existing, "customer", None)),
        "active": active,
    }


# ---- customers ------------------------------------------------------------------------------

MAX_CONTACTS = 20
PHONE_RE = re.compile(r"^[0-9 +()\-]{1,40}$")


def _clean_contact(raw, number):
    label = f"Contact {number}"
    if not isinstance(raw, dict):
        raise BadRequest(f"{label}: enter the contact's details.")
    name = _short(raw.get("name"), 100, f"{label} name")
    if not name:
        raise BadRequest(f"{label}: enter a name.")
    email = _short(raw.get("email"), 254, f"{label} email")
    if email:
        try:
            validate_email(email)
        except ValidationError:
            raise BadRequest(f"{label}: enter a valid email address.") from None
    phone = _short(raw.get("phone"), 40, f"{label} phone")
    if phone and not PHONE_RE.match(phone):
        raise BadRequest(f"{label}: a phone number has only digits, spaces and + - ( ).")
    return {"name": name, "role": _short(raw.get("role"), 60, f"{label} role"), "email": email, "phone": phone}


def _clean_rates(raw):
    if not isinstance(raw, dict):  # missing or not an object: refused, never read as "no rates" (a save replaces them)
        raise BadRequest("Rates: send one rate per service type.")
    rates = []
    for service_type, value in raw.items():
        unit = RATE_UNITS.get(service_type)
        if unit is None:
            raise BadRequest(f"{_short(service_type, 40, 'Service type')}: this service type has no agreed rate.")
        if not isinstance(value, dict):
            raise BadRequest(f"{service_type}: enter the rate.")
        amount = _amount(value.get("amount"), f"{service_type} rate")
        if amount is None:
            raise BadRequest(f"{service_type}: enter the rate.")
        if unit == "percent" and amount > 100:
            raise BadRequest(f"{service_type}: a percentage is from 0 to 100.")
        currency = "USD" if unit == "percent" else _currency(value.get("currency"))
        rates.append({"service_type": service_type, "amount": Decimal(str(round(amount, 2))), "currency": currency})
    return rates


def clean_customer(data, existing=None):
    """A customer with its contacts (0-20) and its agreed rates (one per service type, constants.RATE_UNITS)."""
    name = _short(data.get("name"), 120, "Customer name")
    if not name:
        raise BadRequest("Customer name is required.")
    if Customer.objects.filter(name__iexact=name).exclude(pk=getattr(existing, "pk", None)).exists():
        raise BadRequest("Another customer already has this name.")
    contacts = data.get("contacts")
    if not isinstance(contacts, list):  # missing or not a list: refused, never read as "no contacts"
        raise BadRequest("Contacts: send the list of contacts.")
    if len(contacts) > MAX_CONTACTS:
        raise BadRequest(f"At most {MAX_CONTACTS} contacts per customer.")
    active = data.get("active", getattr(existing, "active", True))
    if not isinstance(active, bool):
        raise BadRequest("Active must be yes or no.")
    return {
        "name": name,
        "notes": _short(data.get("notes"), 500, "Notes"),
        "active": active,
        "contacts": [_clean_contact(raw, number) for number, raw in enumerate(contacts, 1)],
        "rates": _clean_rates(data.get("rates")),
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


def clean_booking_refs(raw):
    """The bookings a crew change's cancellation cancels too: [(kind, id)]; absent → []."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 200:
        raise BadRequest("Unknown booking.")
    refs = []
    for item in raw:
        kind, pk = (item.get("kind"), item.get("id")) if isinstance(item, dict) else (None, None)
        if kind not in ("hotel", "transfer") or not isinstance(pk, int) or isinstance(pk, bool) or pk < 1:
            raise BadRequest("Unknown booking.")
        refs.append((kind, pk))
    return refs


def _cancelled(data):
    """A booking's Cancelled tick: true / false, or None when not sent (the stored value stays)."""
    value = data.get("cancelled")
    if value is not None and not isinstance(value, bool):
        raise BadRequest("Say whether the booking is cancelled (true or false).")
    return value


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
        "cancelled": _cancelled(data),
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
        "cancelled": _cancelled(data),
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


DISPOSAL_KINDS = (("garbage", "Garbage", "m³"), ("sludge", "Sludge", "t"))
MAX_PRICE = 1e10  # the columns hold 12 digits with 2 (amounts) or 3 (quantities) decimals


def _required(value, label, places):
    """A price figure: required (an empty one would silently count as 0), 0 or more, within the column."""
    result = _amount(value, label)
    if result is None:
        raise BadRequest(f"Enter the {label[0].lower() + label[1:]} (0 if none).")
    result = round(result, places)
    if result >= (MAX_PRICE if places == 2 else MAX_PRICE / 10):
        raise BadRequest(f"{label} is too large.")
    return Decimal(str(result))


def clean_disposal_price(data):
    """A month (YYYY-MM), a port and the four price blocks {garbage|sludge: {revenue|cost: {min_qty, min, currency,
    extra}}} → (first of the month, port, model fields). Every figure is required; currencies are EGP or USD."""
    data = _as_dict(data)
    try:
        year, month = str(data.get("month", "")).split("-")
        first_of_month = date(int(year), int(month), 1)
    except ValueError:
        raise BadRequest("Enter a month.") from None
    port = data.get("port")
    if port not in PORT_KEYS:
        raise BadRequest("Unknown port.")
    fields = {}
    for kind, label, unit in DISPOSAL_KINDS:
        for side in ("revenue", "cost"):
            block = _as_dict(_as_dict(data.get(kind)).get(side))
            name = f"{label} {side}"
            fields[f"{kind}_{side}_min_qty"] = _required(block.get("min_qty"), f"{name} minimum quantity", 3)
            fields[f"{kind}_{side}_min"] = _required(block.get("min"), f"{name} minimum", 2)
            currency = block.get("currency")
            if currency not in ("EGP", "USD"):
                raise BadRequest(f"{name} currency must be EGP or USD.")
            fields[f"{kind}_{side}_currency"] = currency
            fields[f"{kind}_{side}_extra"] = _required(block.get("extra"), f"{name} extra per {unit}", 2)
    return first_of_month, port, fields


def clean_disposal_quantities(data):
    """The changes to a vessel's Garbage & Sludge: any of garbage (m³), sludge (t) — empty clears — and hidden."""
    data = _as_dict(data)
    changes = {}
    for kind, label, unit in DISPOSAL_KINDS:
        if kind in data:
            value = _amount(data[kind], f"{label} ({unit})")
            if value is not None and round(value, 3) >= MAX_PRICE / 10:
                raise BadRequest(f"{label} ({unit}) is too large.")
            changes[kind] = None if value is None else Decimal(str(round(value, 3)))
    if "hidden" in data:
        if not isinstance(data["hidden"], bool):
            raise BadRequest("Hidden must be true or false.")
        changes["hidden"] = data["hidden"]
    if not changes:
        raise BadRequest("Nothing to change.")
    return changes

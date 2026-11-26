"""Who gets which money (access rework piece 3): the one place that knows which values are money.

- money.edit: the money boxes of the forms (a service's cost / revenue and its other money keys, a booking's prices,
  the Garbage & Sludge rows' money, customers' agreed rates, the receipt's amounts). Without it the server never sends
  them, saves keep the stored values, and sending them anyway is refused.
- money.view: the overviews (vessel totals and profit, each service's figures, the Dashboard's money, totals rows,
  money columns of exports and the management Excel, the Services page's money tags).

The maths (finance, calculations, serializers) always works on the full data; responses go through here last.
A `profile` of None means an internal caller: everything.
"""

import copy

from . import access
from .constants import MULTI_TYPES

EDIT = "money.edit"
VIEW = "money.view"


def edits(profile):
    return profile is None or profile.can(EDIT)


def views(profile):
    return profile is None or profile.can(VIEW)


# ---- a service's data (Service.data, shape per type in validators.clean_service_data) ------------------------

PRICE_KEYS = ("cost", "costCurrency", "revenue", "revenueCurrency")
SINGLE_MONEY = (*PRICE_KEYS, "exchangeRate")
CASH_MONEY = ("amount", "amountCurrency", "shareMode", "percentage", "fixedRevenue", "exchangeRate")
VISA = "brokenVisa"  # on each Crew Change on-signer
ENTRY_MONEY = PRICE_KEYS  # on each line of MULTI_TYPES
SERVICE_MONEY = {
    "single": SINGLE_MONEY,  # every single-priced type, Crew Change and Others / Remarks
    "multi": ("exchangeRate",),
    "Cash to Master": CASH_MONEY,
}


def _top_keys(service_type):
    if service_type in MULTI_TYPES:
        return SERVICE_MONEY["multi"]
    return SERVICE_MONEY.get(service_type, SERVICE_MONEY["single"])


def _dicts(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def strip_service_data(service_type, data):
    """A copy of a service's data without its money keys (uids, quantities, names and notes stay)."""
    data = copy.deepcopy(data) if isinstance(data, dict) else {}
    for key in _top_keys(service_type):
        data.pop(key, None)
    for entry in _dicts(data.get("entries")):
        for key in ENTRY_MONEY:
            entry.pop(key, None)
    for member in _dicts(data.get("onSigners")):
        member.pop(VISA, None)
    return data


def service_money_sent(service_type, raw):
    """Whether a payload's data carries any money key (an empty or null value counts: it would change the money)."""
    if not isinstance(raw, dict):
        return False
    if any(key in raw for key in _top_keys(service_type)):
        return True
    if any(key in entry for entry in _dicts(raw.get("entries")) for key in ENTRY_MONEY):
        return True
    return any(VISA in member for member in _dicts(raw.get("onSigners")))


def _by_uid(items):
    return {item.get("uid"): item for item in _dicts(items) if item.get("uid")}


def keep_service_money(service_type, cleaned, stored_type, stored):
    """`cleaned` (a save without money) with the stored money put back: top keys, then each line / on-signer matched
    by uid; a line or member that is new keeps the cleaner's empty defaults. Another type: nothing to keep."""
    if stored_type != service_type or not isinstance(stored, dict):
        return cleaned
    result = copy.deepcopy(cleaned)
    for key in _top_keys(service_type):
        if key in stored:
            result[key] = copy.deepcopy(stored[key])
    for items, keys in (("entries", ENTRY_MONEY), ("onSigners", (VISA,))):
        old = _by_uid(stored.get(items))
        for item in _dicts(result.get(items)):
            match = old.get(item.get("uid"))
            for key in keys:
                if match is not None and key in match:
                    item[key] = copy.deepcopy(match[key])
    return result


# ---- vessels (serializers.vessel_to_dict) and the vessel list -----------------------------------------------

VESSEL_TOTALS = ("total_cost_egp", "total_profit_egp")
LIST_TOTALS = ("cost_egp", "profit_egp")
MONEY_SORTS = ("total_cost_egp",)


def vessel_out(row, profile):
    """A vessel dict as this person may get it: totals and each service's figures need money.view, the services'
    money boxes money.edit, the month rate either (the service dialog's live preview uses it)."""
    see, edit = views(profile), edits(profile)
    if see and edit:
        return row
    row = {key: value for key, value in row.items() if see or key not in VESSEL_TOTALS}
    if not (see or edit):
        row.pop("rate", None)
    row["services"] = [_service_out(service, see, edit) for service in row["services"]]
    return row


def _service_out(service, see, edit):
    service = {key: value for key, value in service.items() if see or key != "calc"}
    if not edit:
        service["data"] = strip_service_data(service["type"], service["data"])
    return service


def totals_out(totals, profile):
    return totals if views(profile) else {k: v for k, v in totals.items() if k not in LIST_TOTALS}


def require_sort(profile, sort):
    """Sorting by money would show its order: money.view only."""
    if sort in MONEY_SORTS:
        access.require(profile, VIEW)


# ---- export / report columns -----------------------------------------------------------------------------

# The management Excel's money columns (report). The page Excel files (dataexport) follow their page's own rule.
MONEY_HEADS = frozenset({"Revenue (EGP)", "Cost (EGP)", "Profit (EGP)", "Broken visa revenue (EGP)"})


def money_columns(head, profile):
    """Indexes of the columns this person may not get (none with money.view)."""
    return set() if views(profile) else {i for i, name in enumerate(head) if str(name) in MONEY_HEADS}


# ---- bookings (logistics), Garbage & Sludge rows (disposal), customers' agreed rates ------------------------

BOOKING_MONEY = {
    "hotels": ("cost_per_night", "revenue_per_night", "cost_currency", "revenue_currency", "exchange_rate"),
    "transfers": ("cost", "revenue", "cost_currency", "revenue_currency", "exchange_rate"),
}


def booking_out(kind, row, profile):
    return row if edits(profile) else {k: v for k, v in row.items() if k not in BOOKING_MONEY[kind]}


def booking_money_sent(kind, data):
    return isinstance(data, dict) and any(key in data for key in BOOKING_MONEY[kind])


def keep_booking_money(kind, cleaned, existing):
    """A booking save without money: the stored money (a new booking: the model's empty defaults)."""
    for key in BOOKING_MONEY[kind]:
        if existing is not None:
            cleaned[key] = getattr(existing, key)
        elif key.endswith("_currency"):
            cleaned[key] = "EGP"
        else:
            cleaned[key] = None
    return cleaned


DISPOSAL_ROW_MONEY = ("revenue_egp", "cost_egp", "profit_egp", "revenue_usd", "cost_usd", "profit_usd",
                      "rate_missing", "price_missing")
DISPOSAL_LINE_MONEY = ("revenue", "cost", "price_missing")


def disposal_row_out(row, profile):
    """A Garbage & Sludge row: its money (and each line's) only with money.edit; quantities always."""
    if edits(profile):
        return row
    row = {k: v for k, v in row.items() if k not in DISPOSAL_ROW_MONEY}
    row["lines"] = [{k: v for k, v in line.items() if k not in DISPOSAL_LINE_MONEY} for line in row.get("lines", [])]
    return row


def disposal_out(response, profile):
    """The Garbage & Sludge page: rows as disposal_row_out, the totals line only with money.view."""
    out = {"rows": [disposal_row_out(row, profile) for row in response["rows"]]}
    if views(profile):
        out["totals"] = response["totals"]
    return out


def customer_out(row, profile):
    return row if edits(profile) else {k: v for k, v in row.items() if k != "rates"}


# ---- overviews: the Dashboard, the Services page's tags ------------------------------------------------------

DASHBOARD_MONEY = ("cost_egp", "revenue_egp", "profit_egp")


def dashboard_out(response, profile):
    """The Dashboard's figures: jobs and counts for everyone, money only with money.view."""
    if views(profile):
        return response

    def plain(item):
        return {k: v for k, v in item.items() if k not in DASHBOARD_MONEY}

    return {**response, "totals": plain(response["totals"]), "months": [plain(m) for m in response["months"]]}


MONEY_TAGS = ("Cost", "Revenue", "Rate")


def tags_out(tags, profile):
    """A service's "missing" tags: the money ones (an empty money box, a missing rate) only with money.view."""
    return tags if views(profile) else [tag for tag in tags if tag not in MONEY_TAGS]

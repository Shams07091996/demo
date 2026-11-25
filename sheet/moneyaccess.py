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

"""Money maths: cost, revenue and profit of a service, in EGP.

USD amounts are converted with the service's own override rate if it has one,
otherwise with the exchange rate of the vessel's month.
"""

import math

from .constants import MULTI_TYPES


def num(value):
    """Best-effort float; anything missing, invalid or non-finite counts as 0."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


class _Converter:
    """Converts amounts to EGP and remembers whether a USD amount lacked a rate."""

    def __init__(self, rate):
        self.rate = rate
        self.rate_missing = False

    def to_egp(self, amount, currency):
        amount = num(amount)
        if currency != "USD":
            return amount
        if amount and not self.rate:
            self.rate_missing = True
        return amount * (self.rate or 1)


def _multi_entries(data, conv):
    entries = []
    for entry in data.get("entries", []):
        cost = conv.to_egp(entry.get("cost"), entry.get("costCurrency"))
        revenue = conv.to_egp(entry.get("revenue"), entry.get("revenueCurrency"))
        entries.append((cost, revenue))
    return entries


def _cash_to_master(data, conv):
    """Our revenue is a share OF the amount (a percentage or a fixed figure), never on top of it.
    The rest is handed to the master and is not our cost."""
    amount = num(data.get("amount"))
    if data.get("shareMode") == "fixed":
        share = num(data.get("fixedRevenue"))
    else:
        share = amount * num(data.get("percentage")) / 100
    share = max(0.0, min(share, amount))
    currency = data.get("amountCurrency")
    return conv.to_egp(share, currency), conv.to_egp(amount - share, currency)


def compute(service_type, data, month_rate):
    """Return cost / revenue / profit / to_master (EGP), per-entry figures and a missing-rate flag."""
    conv = _Converter(num(data.get("exchangeRate")) or float(month_rate or 0))
    cost = revenue = to_master = 0.0
    per_entry = []

    if service_type in MULTI_TYPES:
        for entry_cost, entry_revenue in _multi_entries(data, conv):
            cost += entry_cost
            revenue += entry_revenue
            per_entry.append(_figures(entry_cost, entry_revenue))
    elif service_type == "Cash to Master":
        revenue, to_master = _cash_to_master(data, conv)
    else:  # every other service, Crew Change and Others / Remarks included, has a cost and a revenue
        cost = conv.to_egp(data.get("cost"), data.get("costCurrency"))
        revenue = conv.to_egp(data.get("revenue"), data.get("revenueCurrency"))

    return {
        **_figures(cost, revenue),
        "to_master_egp": round(to_master, 2),
        "entries": per_entry,
        "rate_missing": conv.rate_missing,
    }


def _figures(cost, revenue):
    return {
        "cost_egp": round(cost, 2),
        "revenue_egp": round(revenue, 2),
        "profit_egp": round(revenue - cost, 2),
    }

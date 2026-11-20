"""Money maths: cost, revenue and profit, in EGP — the only place they are worked out.

USD amounts are converted with the item's own override rate if it has one, otherwise with the exchange rate of the
vessel's month; with neither, USD counts 1:1 and the line is flagged `rate_missing`.

`service_lines` returns the money lines of one service with their working (amount, currency, rate, EGP); `compute`
adds them up for the vessel figures, so the Calculations page and the vessel totals can never disagree.
Hotel stays and transfers use the same `money` / `line` helpers (see logistics.booking_line).
"""

import math

from .constants import MULTI_TYPES, SINGLE_EXTRAS


def num(value):
    """Best-effort float; anything missing, invalid or non-finite counts as 0."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _fmt(amount):
    return f"{amount:,.2f}"


def money(amount, currency, rate, times=1):
    """One side of a line: {amount, currency, times, rate (USD only, None if missing), egp, rate_missing}, or None
    when there is no amount."""
    amount = num(amount)
    if not amount:
        return None
    usd = currency == "USD"
    return {
        "amount": amount,
        "currency": "USD" if usd else "EGP",
        "times": times,
        "rate": (rate or None) if usd else None,
        # Rounded to the cent here, once: every line, vessel total and page total adds these same figures, so what a
        # person sees always adds up.
        "egp": round(amount * times * ((rate or 1) if usd else 1), 2),
        "rate_missing": usd and not rate,
    }


def line(label, cost, revenue, own_rate, note=""):
    """A money line from its two sides (either may be None). `rate_source` says where a USD rate came from."""
    sides = [side for side in (cost, revenue) if side]
    uses_usd = any(side["currency"] == "USD" for side in sides)
    rate_missing = any(side["rate_missing"] for side in sides)
    cost_egp = cost["egp"] if cost else 0.0
    revenue_egp = revenue["egp"] if revenue else 0.0
    return {
        "label": label,
        "note": note,
        "cost": cost,
        "revenue": revenue,
        "cost_egp": cost_egp,
        "revenue_egp": revenue_egp,
        "profit_egp": round(revenue_egp - cost_egp, 2),
        "rate_source": "" if not uses_usd or rate_missing else ("own" if own_rate else "month"),
        "rate_missing": rate_missing,
    }


def _number_text(value):
    value = num(value)
    return f"{value:g}" if value else ""


def _single_label(service_type, data):
    extra = SINGLE_EXTRAS.get(service_type)
    if extra == "quantity":
        detail = f"{_number_text(data.get('quantity'))} t" if _number_text(data.get("quantity")) else ""
    else:
        detail = str(data.get(extra) or "").strip() if extra else ""
    return f"{service_type} · {detail}" if detail else service_type


def _entry_label(service_type, entry):
    parts = [service_type]
    if str(entry.get("awb") or "").strip():
        parts.append(f"AWB {str(entry['awb']).strip()}")
    if _number_text(entry.get("weight")):
        parts.append(f"{_number_text(entry.get('weight'))} kg")
    return " · ".join(parts)


def cash_to_master_share(data):
    """(our share, its currency) of a Cash to Master: a percentage of the amount or a fixed figure, at most the
    amount."""
    amount = num(data.get("amount"))
    fixed = data.get("shareMode") == "fixed"
    share = num(data.get("fixedRevenue")) if fixed else amount * num(data.get("percentage")) / 100
    return max(0.0, min(share, amount)), "USD" if data.get("amountCurrency") == "USD" else "EGP"


def _cash_to_master(data, rate, own_rate):
    """Our revenue is a share OF the amount (a percentage or a fixed figure), never on top of it.
    The rest is handed to the master and is not our cost."""
    amount = num(data.get("amount"))
    fixed = data.get("shareMode") == "fixed"
    share, currency = cash_to_master_share(data)
    percent = _number_text(data.get("percentage")) or "0"
    how = f"fixed {currency} {_fmt(share)}" if fixed else f"{percent}% of {currency} {_fmt(amount)}"
    result = line("Cash to Master", None, money(share, currency, rate), own_rate,
                  note=f"{how} · {currency} {_fmt(amount - share)} to the master")
    to_master = money(amount - share, currency, rate)
    result["to_master_egp"] = to_master["egp"] if to_master else 0.0
    return result


def _all_lines(service_type, data, month_rate):
    """Every money line of a service, empty ones included (multi-entry figures stay aligned with their entries)."""
    own_rate = num(data.get("exchangeRate"))
    rate = own_rate or num(month_rate)
    if service_type in MULTI_TYPES:
        return [
            line(
                _entry_label(service_type, entry),
                money(entry.get("cost"), entry.get("costCurrency"), rate),
                money(entry.get("revenue"), entry.get("revenueCurrency"), rate),
                own_rate,
            )
            for entry in data.get("entries", [])
            if isinstance(entry, dict)
        ]
    if service_type == "Cash to Master":
        return [_cash_to_master(data, rate, own_rate)]
    # Every other service (Crew Change and Others / Remarks included) has one cost and one revenue.
    lines = [
        line(
            _single_label(service_type, data),
            money(data.get("cost"), data.get("costCurrency"), rate),
            money(data.get("revenue"), data.get("revenueCurrency"), rate),
            own_rate,
        )
    ]
    if service_type == "Crew Change":  # plus each on-signer's broken-visa charge
        for member in data.get("onSigners") or []:
            visa = member.get("brokenVisa") if isinstance(member, dict) else None
            if isinstance(visa, dict):
                lines.append(line(
                    f"Broken visa · {member.get('name') or ''}".strip(),
                    money(visa.get("cost"), visa.get("costCurrency"), rate),
                    money(visa.get("revenue"), visa.get("revenueCurrency"), rate),
                    own_rate,
                ))
    return lines


def has_money(item):
    return bool(item["cost"] or item["revenue"])


def service_lines(service_type, data, month_rate):
    """The money lines of one service (lines with neither cost nor revenue are left out). Figures are unrounded."""
    return [item for item in _all_lines(service_type, data or {}, month_rate) if has_money(item)]


def compute(service_type, data, month_rate):
    """Return cost / revenue / profit / to_master (EGP), per-entry figures and a missing-rate flag."""
    lines = _all_lines(service_type, data or {}, month_rate)
    cost = sum(item["cost_egp"] for item in lines)
    revenue = sum(item["revenue_egp"] for item in lines)
    return {
        **_figures(cost, revenue),
        "to_master_egp": round(sum(item.get("to_master_egp", 0.0) for item in lines), 2),
        "entries": (
            [_figures(item["cost_egp"], item["revenue_egp"]) for item in lines] if service_type in MULTI_TYPES else []
        ),
        "rate_missing": any(item["rate_missing"] for item in lines),
    }


def _figures(cost, revenue):
    return {
        "cost_egp": round(cost, 2),
        "revenue_egp": round(revenue, 2),
        "profit_egp": round(revenue - cost, 2),
    }

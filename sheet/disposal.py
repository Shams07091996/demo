"""Garbage & Sludge: monthly prices per port (DisposalPrice) and each vessel's quantities (VesselDisposal).

Each of the four price blocks (garbage / sludge × revenue / cost) has a minimum quantity, a minimum amount in its own
currency and an extra amount per unit above the minimum:

    nothing entered → 0;  quantity ≤ minimum quantity → minimum amount;  else minimum + (quantity − minimum) × extra.

The block's amount is rounded to the cent in its own currency, then converted with the vessel's month rate (EGP ↔ USD)
and rounded again. On the Garbage & Sludge page a figure that needs a missing rate is None (shown blank, row flagged);
`calculation_lines` gives the Calculations page lines in finance's format (USD counted 1:1 there, flagged).
This money is not part of the vessel figures (finance.compute), like hotel stays and transfers.
"""

from dataclasses import dataclass
from datetime import date

from .access import scoped_vessels
from .constants import PORT_LABELS
from .errors import BadRequest
from .finance import line, money, num
from .listing import date_param
from .models import DisposalPrice, VesselDisposal
from .serializers import month_rates

KINDS = (("garbage", "Garbage", "m³"), ("sludge", "Sludge", "t"))
SIDES = ("revenue", "cost")
BLOCK_FIELDS = ("min_qty", "min", "currency", "extra")
SHOW = ("all", "with", "none", "hidden")


def _r(value):
    return round(value, 2)


# ---- prices ----------------------------------------------------------------------------------


def price_to_dict(price):
    blocks = {
        kind: {side: {
            "min_qty": float(getattr(price, f"{kind}_{side}_min_qty")),
            "min": float(getattr(price, f"{kind}_{side}_min")),
            "currency": getattr(price, f"{kind}_{side}_currency"),
            "extra": float(getattr(price, f"{kind}_{side}_extra")),
        } for side in SIDES}
        for kind, _label, _unit in KINDS
    }
    return {
        "id": price.id,
        "month": price.month.strftime("%Y-%m"),
        "label": price.month.strftime("%m.%Y"),
        "port": price.port,
        "port_label": PORT_LABELS.get(price.port, price.port),
        **blocks,
    }


def prices_map():
    """{(year, month, port): price dict} for every saved month and port."""
    return {(p.month.year, p.month.month, p.port): price_to_dict(p) for p in DisposalPrice.objects.all()}


def prices_for(profile):
    prices = DisposalPrice.objects.all()
    if profile.port:  # port users see their own port's prices only
        prices = prices.filter(port=profile.port)
    return [price_to_dict(p) for p in prices]


# ---- money -----------------------------------------------------------------------------------


def block_amount(quantity, block):
    """The amount of one price block for `quantity`, in the block's currency, to the cent."""
    q = num(quantity)
    if not q:
        return 0.0
    minimum = num(block["min"])
    if q <= num(block["min_qty"]):
        return _r(minimum)
    return _r(minimum + (q - num(block["min_qty"])) * num(block["extra"]))


def convert(amount, currency, rate):
    """(EGP, USD) of an amount; the side that needs a missing rate is None."""
    rate = num(rate)
    if currency == "USD":
        return (_r(amount * rate) if rate else None), amount
    return amount, (_r(amount / rate) if rate else None)


def _sum(values):
    return None if any(v is None for v in values) else _r(sum(values))


def _minus(a, b):
    return None if a is None or b is None else _r(a - b)


def kind_line(kind, label, unit, quantity, price, rate):
    """One kind's money for a vessel, or None when no quantity."""
    q = num(quantity)
    if not q:
        return None
    item = {"kind": kind, "label": f"{label} · {q:g} {unit}", "quantity": q, "unit": unit,
            "price_missing": price is None}
    if price is None:
        item.update(revenue=None, cost=None)
        return item
    for side in SIDES:
        block = price[kind][side]
        amount = block_amount(q, block)
        egp, usd = convert(amount, block["currency"], rate)
        item[side] = {"currency": block["currency"], "amount": amount, "egp": egp, "usd": usd}
    return item


def figures(disposal, price, rate):
    """A vessel's lines and totals (EGP and USD) from its quantities, its port and month's price and the month rate."""
    lines = []
    if disposal and not disposal.hidden:
        for kind, label, unit in KINDS:
            item = kind_line(kind, label, unit, getattr(disposal, kind), price, rate)
            if item:
                lines.append(item)
    priced = [item for item in lines if not item["price_missing"]]
    out = {"lines": lines, "price_missing": len(priced) < len(lines)}
    for currency in ("egp", "usd"):
        for side in SIDES:
            out[f"{side}_{currency}"] = _sum([item[side][currency] for item in priced])
        out[f"profit_{currency}"] = _minus(out[f"revenue_{currency}"], out[f"cost_{currency}"])
    out["rate_missing"] = any(item[side]["egp"] is None or item[side]["usd"] is None
                              for item in priced for side in SIDES)
    return out


def calculation_lines(vessel, rate, price):
    """The Calculations page's lines (finance.line format, USD counted 1:1 without a rate) plus USD figures."""
    disposal = getattr(vessel, "disposal", None)
    out = []
    for item in figures(disposal, price, rate)["lines"]:
        if item["price_missing"]:
            entry = line(item["label"], None, None, 0, note="no price for this port and month")
            entry["price_missing"] = True
            entry["usd"] = None
        else:
            sides = {side: money(item[side]["amount"], item[side]["currency"], num(rate)) for side in SIDES}
            entry = line(item["label"], sides["cost"], sides["revenue"], 0)
            usd = [item[side]["usd"] for side in ("cost", "revenue")]
            entry["usd"] = None if None in usd else (usd[0], usd[1], _r(usd[1] - usd[0]))
        out.append(entry)
    return out


def vessel_disposal(vessel):
    try:
        return vessel.disposal
    except VesselDisposal.DoesNotExist:
        return None


# ---- the page --------------------------------------------------------------------------------


@dataclass
class Params:
    date_from: date | None
    date_to: date | None
    port: str | None
    show: str


def parse_params(params):
    p = Params(date_param(params, "from"), date_param(params, "to"), params.get("port") or None,
               params.get("show") or "all")
    if p.date_from and p.date_to and p.date_from > p.date_to:
        raise BadRequest("From must be on or before To.")
    if p.show not in SHOW:
        raise BadRequest("Unknown filter.")
    return p


def row(vessel, rates, prices):
    month = (vessel.date.year, vessel.date.month)
    disposal = vessel_disposal(vessel)
    return {
        "vessel": {"id": vessel.id, "name": vessel.name, "date": vessel.date.isoformat(), "opr": vessel.opr,
                   "port": vessel.port, "port_label": PORT_LABELS.get(vessel.port, vessel.port)},
        "garbage": float(disposal.garbage) if disposal and disposal.garbage is not None else None,
        "sludge": float(disposal.sludge) if disposal and disposal.sludge is not None else None,
        "hidden": bool(disposal and disposal.hidden),
        **figures(disposal, prices.get((*month, vessel.port)), rates.get(month)),
    }


def _entered(r):
    return bool(r["garbage"] or r["sludge"])


FILTERS = {
    "all": lambda r: not r["hidden"],
    "with": lambda r: not r["hidden"] and _entered(r),
    "none": lambda r: not r["hidden"] and not _entered(r),
    "hidden": lambda r: r["hidden"],
}


def response(profile, params):
    p = parse_params(params)
    vessels = scoped_vessels(profile, p.port, prefetch=False).select_related("disposal")
    if p.date_from:
        vessels = vessels.filter(date__gte=p.date_from)
    if p.date_to:
        vessels = vessels.filter(date__lte=p.date_to)
    rates, prices = month_rates(), prices_map()
    rows = [r for r in (row(v, rates, prices) for v in vessels.order_by("-date", "-id")) if FILTERS[p.show](r)]
    totals = {key: _sum([r[key] for r in rows if r[key] is not None])
              for key in ("revenue_egp", "cost_egp", "profit_egp", "revenue_usd", "cost_usd", "profit_usd")}
    totals["rate_missing_rows"] = sum(1 for r in rows if r["rate_missing"])
    totals["price_missing_rows"] = sum(1 for r in rows if r["price_missing"])
    return {"rows": rows, "totals": totals}


def save(vessel, changes):
    """Apply cleaned changes ({garbage, sludge} and / or {hidden}) to a vessel; hiding clears the quantities."""
    disposal = vessel_disposal(vessel) or VesselDisposal(vessel=vessel)
    for key, value in changes.items():
        setattr(disposal, key, value)
    if disposal.hidden:
        disposal.garbage = disposal.sludge = None
    disposal.save()
    vessel.disposal = disposal
    return row(vessel, month_rates(), prices_map())

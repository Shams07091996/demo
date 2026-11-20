"""The master receipt's pre-filled text: what the user sees in the form before editing it and downloading the PDF.

The service's revenue is written as "cost": what ARKAS earns is what the vessel pays. Nothing here is stored.
"""

from django.utils import timezone

from .constants import MULTI_TYPES, PORT_LABELS
from .finance import cash_to_master_share, num


def _amount_text(amount, currency):
    figure = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    return f"${figure}" if currency == "USD" else f"EGP {figure}"


def _revenue(service):
    """{currency: total revenue} of a service, in the currencies it was entered in."""
    data = service.data or {}
    if service.service_type == "Cash to Master":
        share, currency = cash_to_master_share(data)
        pairs = [(share, currency)]
    elif service.service_type in MULTI_TYPES:
        pairs = [(num(e.get("revenue")), e.get("revenueCurrency")) for e in data.get("entries") or []
                 if isinstance(e, dict)]
    else:
        pairs = [(num(data.get("revenue")), data.get("revenueCurrency"))]
    totals = {}
    for amount, currency in pairs:
        if amount > 0:
            key = "USD" if currency == "USD" else "EGP"
            totals[key] = totals.get(key, 0.0) + amount
    return totals


def services_line(service):
    """e.g. "Landing with cost $120.50 and EGP 3,000"; just the label when there is no revenue."""
    label = service.service_type
    if label == "Others / Remarks":
        note = str((service.data or {}).get("note") or "").strip()
        label = note.splitlines()[0].strip() if note else label
    totals = _revenue(service)
    amounts = [_amount_text(round(totals[c], 2), c) for c in ("USD", "EGP") if c in totals]
    return f"{label} with cost {' and '.join(amounts)}" if amounts else label


def prefill(service):
    vessel = service.vessel
    return {
        "port": PORT_LABELS.get(vessel.port, vessel.port),
        "date": timezone.localdate().strftime("%d/%m/%Y"),
        "vessel": vessel.name,
        "services": services_line(service),
    }

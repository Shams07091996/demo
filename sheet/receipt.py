"""The master receipt's pre-filled text: what the user sees in the form before editing it and downloading the PDF.

The service's revenue is written as "cost": what ARKAS earns is what the vessel pays. Nothing here is stored.
"""

from django.utils import timezone

from . import ports
from .finance import service_lines


def _amount_text(amount, currency):
    figure = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    return f"${figure}" if currency == "USD" else f"EGP {figure}"


def _revenue(service):
    """{currency: total revenue} of a service, in the currencies it was entered in: the revenue side of every money
    line finance counts for it (entries, Cash to Master's share, a Crew Change's broken-visa charges included)."""
    totals = {}
    for item in service_lines(service.service_type, service.data, None):
        side = item["revenue"]
        if side and side["amount"] > 0:
            totals[side["currency"]] = totals.get(side["currency"], 0.0) + side["amount"] * side["times"]
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
        "port": ports.label(vessel.port),
        "date": timezone.localdate().strftime("%d/%m/%Y"),
        "vessel": vessel.name,
        "services": services_line(service),
    }

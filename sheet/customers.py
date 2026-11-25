"""Customers: who we bill (separate from the OPR), with contacts and agreed rates (constants.RATE_UNITS says what a
rate means per service type). Shared by all ports; everyone reads them, only admins change them. The rates only
pre-fill the service dialog's revenue (js/rates.js); the server never checks a revenue against them."""

from django.db.models import ProtectedError

from .errors import BadRequest, Forbidden
from .models import Customer, CustomerContact, CustomerRate
from .ships import IN_USE
from .validators import clean_customer


def customer_to_dict(customer):
    return {
        "id": customer.id,
        "name": customer.name,
        "notes": customer.notes,
        "active": customer.active,
        "contacts": [{"name": c.name, "role": c.role, "email": c.email, "phone": c.phone}
                     for c in customer.contacts.all()],
        "rates": {r.service_type: {"amount": float(r.amount), "currency": r.currency} for r in customer.rates.all()},
        "ships": [{"id": s.id, "name": s.name, "imo": s.imo} for s in customer.ships.all()],
    }


def list_response():
    customers = Customer.objects.prefetch_related("contacts", "rates", "ships").order_by("name", "id")
    return {"customers": [customer_to_dict(c) for c in customers]}


RATES_NEED_MONEY = "You don't have permission: Enter / edit prices and costs."


def _rate_set(rates):
    return {(r["service_type"], r["amount"], r["currency"]) for r in rates}


def save_customer(payload, existing=None, may_change_rates=True):
    """Create or update a customer; its contacts and rates become what was sent (in the request's one transaction,
    so a refused payload changes nothing). Only rows that really change are written, so the History shows just
    what someone changed."""
    values = clean_customer(payload, existing)
    if not may_change_rates:  # agreed rates are money: only with money.edit (sending them unchanged is fine)
        stored = list(existing.rates.values("service_type", "amount", "currency")) if existing else []
        if _rate_set(values["rates"]) != _rate_set(stored):
            raise Forbidden(RATES_NEED_MONEY)
    customer = existing or Customer()
    for key in ("name", "notes", "active"):
        setattr(customer, key, values[key])
    customer.save()
    _save_contacts(customer, values["contacts"])
    _save_rates(customer, values["rates"])
    return Customer.objects.prefetch_related("contacts", "rates", "ships").get(pk=customer.pk)


CONTACT_FIELDS = ("name", "role", "email", "phone")


def _save_contacts(customer, contacts):
    """Contacts are an ordered list: changed rows in place, extra rows added, missing rows deleted."""
    stored = list(customer.contacts.order_by("position", "id"))
    for position, contact in enumerate(contacts):
        if position < len(stored):
            row = stored[position]
            if any(getattr(row, f) != contact[f] for f in CONTACT_FIELDS):
                for f in CONTACT_FIELDS:
                    setattr(row, f, contact[f])
                row.save()
        else:
            CustomerContact.objects.create(customer=customer, position=position, **contact)
    for row in stored[len(contacts):]:
        row.delete()


def _save_rates(customer, rates):
    """One rate per service type: changed ones updated, new ones added, the others deleted."""
    stored = {r.service_type: r for r in customer.rates.all()}
    for rate in rates:
        row = stored.pop(rate["service_type"], None)
        if row is None:
            CustomerRate.objects.create(customer=customer, **rate)
        elif (row.amount, row.currency) != (rate["amount"], rate["currency"]):
            row.amount, row.currency = rate["amount"], rate["currency"]
            row.save()
    for row in stored.values():
        row.delete()


def delete_customer(customer):
    try:
        customer.delete()
    except ProtectedError:
        raise BadRequest(IN_USE) from None

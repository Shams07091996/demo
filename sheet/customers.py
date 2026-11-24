"""Customers: who we bill (separate from the OPR), with contacts and agreed rates (constants.RATE_UNITS says what a
rate means per service type). Shared by all ports; everyone reads them, only admins change them. The rates only
pre-fill the service dialog's revenue (js/rates.js); the server never checks a revenue against them."""

from django.db.models import ProtectedError

from .errors import BadRequest
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


def save_customer(payload, existing=None):
    """Create or update a customer; its contacts and rates are replaced by what was sent (in the request's one
    transaction, so a refused payload changes nothing)."""
    values = clean_customer(payload, existing)
    customer = existing or Customer()
    for key in ("name", "notes", "active"):
        setattr(customer, key, values[key])
    customer.save()
    customer.contacts.all().delete()
    customer.rates.all().delete()
    for position, contact in enumerate(values["contacts"]):
        CustomerContact.objects.create(customer=customer, position=position, **contact)
    for rate in values["rates"]:
        CustomerRate.objects.create(customer=customer, **rate)
    return Customer.objects.prefetch_related("contacts", "rates", "ships").get(pk=customer.pk)


def delete_customer(customer):
    try:
        customer.delete()
    except ProtectedError:
        raise BadRequest(IN_USE) from None

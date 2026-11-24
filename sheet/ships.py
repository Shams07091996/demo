"""Ships: one record per real ship (name, IMO, OPR, customer), shared by all ports and reused by every port call
(`Vessel.ship`). Admins and port users add and edit them (also from the vessel form); only admins delete, and only
a ship no vessel uses (otherwise it is marked inactive)."""

from django.db.models import Count, ProtectedError, Q

from .errors import BadRequest
from .models import Ship
from .validators import clean_ship

MAX_LIST = 200
IN_USE = "In use: mark it inactive instead."


def ship_to_dict(ship, calls=None):
    customer = ship.customer
    return {
        "id": ship.id,
        "name": ship.name,
        "imo": ship.imo,
        "opr": ship.opr,
        "customer": {"id": customer.id, "name": customer.name} if customer else None,
        "active": ship.active,
        "calls": calls if calls is not None else ship.vessels.count(),
    }


def _limit(params):
    try:
        value = int(params.get("limit") or MAX_LIST)
    except ValueError:
        raise BadRequest("Unknown limit.") from None
    return min(max(value, 1), MAX_LIST)


def list_response(params):
    ships = Ship.objects.select_related("customer").annotate(calls=Count("vessels"))
    query = (params.get("q") or "").strip()[:120]
    if query:  # literal, case-insensitive (icontains escapes % and _)
        ships = ships.filter(Q(name__icontains=query) | Q(imo__icontains=query))
    if params.get("active") == "1":
        ships = ships.filter(active=True)
    return {"ships": [ship_to_dict(s, s.calls) for s in ships.order_by("name", "id")[: _limit(params)]]}


def save_ship(profile, payload, existing=None):
    values = clean_ship(payload, profile, existing)
    ship = existing or Ship()
    for key, value in values.items():
        setattr(ship, key, value)
    ship.save()
    return ship


def delete_ship(ship):
    try:
        ship.delete()
    except ProtectedError:
        raise BadRequest(IN_USE) from None

"""Ports: a table Admins manage (add, rename, turn off). Records hold a port's key, which never changes; screens,
receipts and exports show its name from here. Read at most once per request (cached on the request)."""

import re

from django.db.models import Count, Max

from .history import current_request
from .models import Port, Profile, Vessel

KEY_LENGTH = 18  # leaves room for a digit or two within the 20-character port fields


def _rows():
    request = current_request()
    cached = getattr(request, "_sheet_ports", None) if request is not None else None
    if cached is None:
        cached = list(Port.objects.order_by("position", "name").values_list("key", "name", "active"))
        if request is not None:
            request._sheet_ports = cached
    return cached


def forget():
    """After a port is added or changed: the next read in this request sees it."""
    request = current_request()
    if request is not None and hasattr(request, "_sheet_ports"):
        del request._sheet_ports


def ordered(active_only=False):
    """[(key, name)] in the page order."""
    return [(key, name) for key, name, active in _rows() if active or not active_only]


def keys(active_only=False):
    return [key for key, _ in ordered(active_only)]


def labels():
    return dict(ordered())


def label(key):
    return labels().get(key, key)


def exists(key, active_only=False):
    return key in keys(active_only)


def make_key(name):
    """A new port's fixed key: the name's letters and digits in lower case, a digit added when it is taken."""
    base = re.sub(r"[^a-z0-9]", "", str(name).lower())[:KEY_LENGTH] or "port"
    taken = set(Port.objects.values_list("key", flat=True))
    key, n = base, 2
    while key in taken:
        key, n = f"{base}{n}", n + 1
    return key


def rows():
    """[(key, name, active)] in the page order (the page's `ports-data`)."""
    return list(_rows())


# ---- the Ports page (Admins only: views checks) ----


def port_to_dict(port, vessels=0, users=0):
    return {"key": port.key, "name": port.name, "active": port.active, "vessels": vessels, "users": users}


def list_response():
    """Every port in page order, with how many vessels are in it and how many Users work there."""
    vessels = dict(Vessel.objects.values_list("port").annotate(n=Count("id")).order_by())
    users = {}
    for keys_ in Profile.objects.filter(user__is_active=True).values_list("ports", flat=True):
        for key in set(keys_ or []):
            users[key] = users.get(key, 0) + 1
    return {"ports": [port_to_dict(p, vessels.get(p.key, 0), users.get(p.key, 0))
                      for p in Port.objects.order_by("position", "name")]}


def save_port(values, existing=None):
    """A new port (its key made once from the name, placed last) or an existing one renamed / turned off or on.
    Ports are never deleted: records keep their key."""
    if existing is None:
        last = Port.objects.aggregate(m=Max("position"))["m"]
        port = Port.objects.create(key=make_key(values["name"]), name=values["name"],
                                   active=values.get("active", True), position=0 if last is None else last + 1)
    else:
        port = existing
        changed = [k for k, v in values.items() if getattr(port, k) != v]
        for key in changed:
            setattr(port, key, values[key])
        if changed:
            port.save(update_fields=changed)
    forget()
    return port

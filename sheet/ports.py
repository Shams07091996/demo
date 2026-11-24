"""Ports: a table Admins manage (add, rename, turn off). Records hold a port's key, which never changes; screens,
receipts and exports show its name from here. Read at most once per request (cached on the request)."""

import re

from .history import current_request
from .models import Port

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

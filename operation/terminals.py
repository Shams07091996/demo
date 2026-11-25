"""Terminals: the Excel's Settings sheet. Admins (every port) and people with "Edit terminals and vessel list"
(their own ports) keep them on the Terminals page; never deleted, only turned off."""

from django.db.models import Max
from django.http import Http404

from sheet import ports

from .access import scoped_terminals
from .pictures import has_picture
from .models import Terminal
from .validators import clean_terminal


def terminal_to_dict(terminal):
    return {
        "id": terminal.id,
        "name": terminal.name,
        "code": terminal.code,
        "port": terminal.port,
        "port_label": ports.label(terminal.port),
        "quay_length": terminal.quay_length,
        "cranes": terminal.cranes,
        "berths": list(terminal.berths),
        "lines": list(terminal.lines),
        "active": terminal.active,
        "picture": has_picture(terminal),
    }


def list_response(profile, params):
    return {"terminals": [terminal_to_dict(t) for t in scoped_terminals(profile, params.get("port") or None)]}


def get_terminal(profile, pk):
    try:
        return scoped_terminals(profile).get(pk=pk)
    except Terminal.DoesNotExist:
        raise Http404 from None


def save_terminal(profile, data, existing=None):
    terminal = existing or Terminal(position=(Terminal.objects.aggregate(m=Max("position"))["m"] or 0) + 1)
    for field, value in clean_terminal(data, profile, existing).items():
        setattr(terminal, field, value)
    terminal.save()
    return terminal

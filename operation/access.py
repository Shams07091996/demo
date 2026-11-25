"""Who sees which terminals and visits: a User only their ports' (through the terminal's port), an Admin all."""

from sheet.access import asked_port, ports_of
from sheet.errors import Forbidden

from .models import Terminal, Visit

PAGES = ("op_vessels", "op_live", "op_analysis", "op_charts")


def require_reader(profile):
    """Any Operation page (Admins always)."""
    if not any(profile.sees(page) for page in PAGES):
        raise Forbidden("You don't have access to this page.")


def require_master(profile):
    """Terminals and the vessel list: Admins, or the "Edit terminals and vessel list" tick."""
    if not profile.can("operation.master"):
        raise Forbidden("You don't have permission to do that.")


def scoped_terminals(profile, port=None):
    queryset = Terminal.objects.all()
    mine = ports_of(profile)
    if mine is not None:
        queryset = queryset.filter(port__in=mine)
    port = asked_port(profile, port)
    return queryset.filter(port=port) if port else queryset


def scoped_visits(profile, port=None):
    queryset = Visit.objects.select_related("terminal")
    mine = ports_of(profile)
    if mine is not None:
        queryset = queryset.filter(terminal__port__in=mine)
    port = asked_port(profile, port)
    return queryset.filter(terminal__port=port) if port else queryset

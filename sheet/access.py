"""Who may see and change what."""

from . import ports
from .errors import BadRequest, Forbidden
from .models import PortClosure, Profile, Vessel


def profile_of(user):
    """The user's Profile, created on first use with no ports (least privilege: an admin gives them ports)."""
    try:
        return user.profile  # the same object the rest of the request sees
    except Profile.DoesNotExist:
        profile, _ = Profile.objects.get_or_create(user=user)
        user.profile = profile
        return profile


def require_edit(profile):
    if not profile.can_edit:
        raise Forbidden("Your account is read-only.")


def require_accounting(profile):
    """Accounting (Open / Closed on Calculations): admins only."""
    if not profile.is_admin:
        raise Forbidden("Only an admin can change this.")


def require_superuser(request):
    """Accounts (the Accounts page): superusers only, whatever their role says."""
    if not request.user.is_superuser:
        raise Forbidden("Only a superuser can manage accounts.")


def require_admin(profile):
    """For data shared by every port (e.g. exchange rates): only admins may change it."""
    if not profile.is_admin:
        raise Forbidden("Only an admin can change this.")


def ports_of(profile):
    """The ports a profile works in: None for an Admin (every port, no limit), else the User's port keys."""
    return None if profile.is_admin else list(profile.ports)


def asked_port(profile, port):
    """The port a request asks to narrow to, if it may: an existing port (Admins) or one of the User's own.
    Anything else is None (= no narrowing): asking for a port never widens what a User sees."""
    if not port or not isinstance(port, str):
        return None
    mine = ports_of(profile)
    if mine is None:
        return port if ports.exists(port) else None
    return port if port in mine else None


def _scoped(queryset, profile, port):
    mine = ports_of(profile)
    if mine is not None:
        queryset = queryset.filter(port__in=mine)
    port = asked_port(profile, port)
    return queryset.filter(port=port) if port else queryset


def require_port(profile, key, new=False):
    """A port this profile may write into: an existing port that is the User's own (Admins: any). `new`: a record
    going into the port (created or moved there) also needs the port to be turned on."""
    if not isinstance(key, str) or not key or not ports.exists(key):
        raise BadRequest("Unknown port.")
    mine = ports_of(profile)
    if mine is not None and key not in mine:
        raise Forbidden("You don't work in that port.")
    if new and not ports.exists(key, active_only=True):
        raise BadRequest("That port is turned off.")
    return key


def scoped_vessels(profile, port=None, prefetch=True):
    """Vessels this profile may see: a User only their ports' (narrowed to `port` when it is one of theirs),
    an Admin every port's (narrowed to any existing `port`)."""
    queryset = (Vessel.objects.prefetch_related("services__billing_party").select_related("ship") if prefetch
                else Vessel.objects.all())
    return _scoped(queryset, profile, port)


def scoped_closures(profile, port=None):
    """Port closures this profile may see, scoped like vessels."""
    return _scoped(PortClosure.objects.all(), profile, port)

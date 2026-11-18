"""Who may see and change what."""

from .constants import PORT_KEYS
from .errors import Forbidden
from .models import PortClosure, Profile, Vessel


def profile_of(user):
    """The user's Profile, created on first use. New accounts start read-only (least privilege)."""
    profile, _ = Profile.objects.get_or_create(
        user=user, defaults={"role": "admin" if user.is_superuser else "readonly"}
    )
    return profile


def require_edit(profile):
    if not profile.can_edit:
        raise Forbidden("Your account is read-only.")


def require_admin(profile):
    """For data shared by every port (e.g. exchange rates): only admins may change it."""
    if not profile.is_admin:
        raise Forbidden("Only an admin can change this.")


def scoped_vessels(profile, port=None, prefetch=True):
    """Vessels this profile may see. Port users only ever see their own port; others may filter."""
    queryset = Vessel.objects.prefetch_related("services") if prefetch else Vessel.objects.all()
    if profile.port:
        return queryset.filter(port=profile.port)
    if port in PORT_KEYS:
        return queryset.filter(port=port)
    return queryset


def scoped_closures(profile, port=None):
    """Port closures this profile may see: port users only their own port whatever they ask; others may filter."""
    if profile.port:
        return PortClosure.objects.filter(port=profile.port)
    if port in PORT_KEYS:
        return PortClosure.objects.filter(port=port)
    return PortClosure.objects.all()

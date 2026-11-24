"""The Accounts page (Admins = superusers only): every account, adding a person, changing their names / ports,
turning them off or on. Superuser and staff accounts are read-only here (they are managed in the admin pages); the
page never sets either flag. Passwords go in once, at creation, and never come back out. The History records every
change through the User / Profile signals (history.py)."""

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import ports
from .access import profile_of
from .constants import PAGES, PERMISSIONS, TEMPLATES
from .errors import BadRequest
from .models import Profile, RememberedComputer
from .serializers import local_iso
from .validators import clean_account

TAKEN = "That username is already used."
LOCKED_ACCOUNT = "Superuser and staff accounts are changed in the admin pages."


def _stored_profile(user):
    """The user's Profile, or None for an old account that has none yet (reading never creates one)."""
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


def _two_step(profile, confirmed, now):
    if profile is not None and profile.two_step_exempt:
        return "exempt"
    if confirmed:
        return "set_up"
    if profile is not None and profile.setup_until is not None and now < profile.setup_until:
        return "waiting"
    return "expired"


def account_to_dict(user, now=None, confirmed=None):
    now = now or timezone.now()
    if confirmed is None:
        confirmed = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
    profile = _stored_profile(user)
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "home_port": profile.home_port if profile else "",
        "ports": list(profile.ports) if profile else [],
        "permissions": list(profile.permissions) if profile else [],
        "pages": list(profile.pages) if profile else [],
        "superuser": user.is_superuser,
        "staff": user.is_staff,
        "active": user.is_active,
        "two_step": _two_step(profile, confirmed, now),
        "setup_until": local_iso(profile.setup_until) if profile else None,
        "last_login": local_iso(user.last_login),
    }


def list_response():
    now = timezone.now()
    confirmed = set(TOTPDevice.objects.filter(confirmed=True).values_list("user_id", flat=True))
    users = User.objects.select_related("profile").order_by("-is_active", "username", "id")
    return {
        "accounts": [account_to_dict(u, now, u.id in confirmed) for u in users],
        "ports": [[key, name, active] for key, name, active in ports.rows()],
        "permissions": [list(p) for p in PERMISSIONS],
        "pages": [list(p) for p in PAGES],
        # Templates only fill in the dialog's ticks; nothing links a person to one.
        "templates": [[key, label, list(perms), list(pages)] for key, label, perms, pages in TEMPLATES],
    }


def _save_profile(profile):
    try:
        profile.save()  # Profile.save runs clean() (the two-step exception rule)
    except ValidationError as error:
        raise BadRequest(" ".join(error.messages)) from None


def create_account(payload):
    values = clean_account(payload)
    if User.objects.filter(username__iexact=values["username"]).exists():
        raise BadRequest(TAKEN)
    user = User.objects.create_user(values["username"], password=values["password"],
                                    first_name=values["first_name"], last_name=values["last_name"])
    _save_profile(Profile(user=user, home_port=values["home_port"], ports=values["ports"],
                          permissions=values["permissions"], pages=values["pages"]))
    return user


def update_account(user, payload):
    if user.is_superuser or user.is_staff:
        raise BadRequest(LOCKED_ACCOUNT)
    values = clean_account(payload, existing=user)
    fields = [key for key in ("home_port", "ports", "permissions", "pages") if key in values]
    if fields:
        profile = profile_of(user)
        if any(getattr(profile, key) != values[key] for key in fields):
            for key in fields:
                setattr(profile, key, values[key])
            _save_profile(profile)  # one save, so the History has one record of the change
    changed = False
    for key in ("first_name", "last_name"):
        if key in values and getattr(user, key) != values[key]:
            setattr(user, key, values[key])
            changed = True
    if "active" in values and user.is_active != values["active"]:
        user.is_active = values["active"]
        changed = True
        if not user.is_active:
            for row in RememberedComputer.objects.filter(user=user):
                row.delete()  # one by one, so the History records each
    if changed:
        user.save()
    return user

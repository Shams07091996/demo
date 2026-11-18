"""Two-step login (OWASP A07): after the password, a six-digit code from an Authenticator app (TOTP, django-otp).

How a session passes the second step is kept in the session (`SESSION_KEY`): {"how": "code" | "remembered" |
"exempt", "ref": device / remembered-computer id}. It is checked again on every request, so a reset, a forgotten
computer or a removed exception ends sessions that relied on it. A password sign-in always clears it.

`next_step` says which page a signed-in person must see before anything else; `TwoStepMiddleware`
(sheet/middleware.py) enforces it for every page, API call and admin page."""

import hashlib
import logging
import secrets
from base64 import b32encode
from datetime import timedelta

import segno
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import history, throttle
from .access import profile_of
from .models import SETUP_WINDOW, RememberedComputer
from .netutils import client_ip

SESSION_KEY = "two_step"
REMEMBER_DAYS = 30
DEVICE_NAME = "Authenticator"
security_log = logging.getLogger("sheet.security")


# ---- session state ------------------------------------------------------------------------------------------------


def mark_passed(request, how, ref=None):
    """This session has passed the second step. A new session key, so a key seen before the step is worthless."""
    request.session.cycle_key()
    request.session[SESSION_KEY] = {"how": how, "ref": ref}


def _still_valid(user, state):
    how, ref = state.get("how"), state.get("ref")
    if how == "code":
        return TOTPDevice.objects.filter(pk=ref, user=user, confirmed=True).exists()
    if how == "remembered":
        remembered = RememberedComputer.objects.filter(pk=ref, user=user, expires_at__gt=timezone.now()).exists()
        return remembered and confirmed_device(user) is not None
    if how == "exempt":
        profile = profile_of(user)
        return profile.two_step_exempt and profile.may_be_exempt()
    return False


def has_passed(request):
    state = request.session.get(SESSION_KEY)
    if not isinstance(state, dict):
        return False
    if _still_valid(request.user, state):
        return True
    request.session.pop(SESSION_KEY, None)
    return False


def confirmed_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def next_step(request):
    """URL name of the page this signed-in person must see first, or None when they may use the app."""
    user = request.user
    profile = profile_of(user)
    passed = has_passed(request)
    if not passed:
        if profile.two_step_exempt and profile.may_be_exempt():
            mark_passed(request, "exempt")
            security_log.info("two-step exempt sign-in user=%s ip=%s", user.get_username(), client_ip(request))
            passed = True
        elif confirmed_device(user) is not None:
            row = remembered_row(request)
            if row is None:
                return "two_step_code"
            mark_passed(request, "remembered", row.pk)
            security_log.info("two-step remembered sign-in user=%s ip=%s", user.get_username(), client_ip(request))
            passed = True
    if profile.must_change_password:
        return "password_change"
    if not passed:
        return "two_step_setup" if setup_open(profile) else "two_step_blocked"
    return None


def setup_open(profile):
    return profile.setup_until is not None and timezone.now() < profile.setup_until


@receiver(user_logged_in, dispatch_uid="two-step-clear-on-login")
def _clear_on_login(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session.pop(SESSION_KEY, None)


# ---- codes --------------------------------------------------------------------------------------------------------


def clean_code(raw):
    code = "".join(str(raw or "").split())
    return code if len(code) == 6 and code.isdigit() else ""


def check_code(request, device, raw):
    """True when `raw` is the device's current code. Locked against a second request using the same code at once; a
    wrong code counts towards the sign-in lock-out like a wrong password."""
    code = clean_code(raw)
    ok = False
    if code:
        with transaction.atomic():
            locked = TOTPDevice.objects.select_for_update().get(pk=device.pk)
            ok = locked.verify_token(code)
    username = request.user.get_username()
    ip = client_ip(request)
    if ok:
        throttle.reset(ip, username)
        security_log.info("two-step code ok user=%s ip=%s", username, ip)
    else:
        throttle.record_failure(ip, username)
        security_log.warning("two-step code wrong user=%s ip=%s", username, ip)
    return ok


def confirm_setup(device):
    """The first right code: the Authenticator is active and the setup window closes (only a reset reopens it).
    Saved from a fresh copy, so the code's time step that `check_code` stored (no reuse) is kept."""
    with transaction.atomic():
        fresh = TOTPDevice.objects.select_for_update().get(pk=device.pk)
        fresh.confirmed = True
        fresh.save()
        profile = profile_of(device.user)
        profile.setup_until = None
        profile.save()
    return fresh


def new_device(user):
    """The person's unconfirmed device (a fresh secret the first time), shown on the setup page until confirmed."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("id").first()
    return device or TOTPDevice.objects.create(user=user, name=DEVICE_NAME, confirmed=False)


def secret_text(device):
    """The secret in the form Authenticator accepts when typed by hand, in groups of four."""
    key = b32encode(device.bin_key).decode("ascii").rstrip("=")
    return " ".join(key[i : i + 4] for i in range(0, len(key), 4))


def qr_data_url(device):
    """The setup QR code as an SVG data: URL; always dark on white with a quiet zone, whatever the page's colours."""
    return segno.make(device.config_url, error="m").svg_data_uri(scale=5, border=4, dark="black", light="white")


# ---- remember this computer ---------------------------------------------------------------------------------------


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def remembered_row(request):
    """The signed-in user's valid remembered-computer row for this browser, or None."""
    token = request.COOKIES.get(settings.REMEMBER_COOKIE_NAME, "")
    if not token or len(token) > 100:
        return None
    row = RememberedComputer.objects.filter(
        token_hash=_hash(token), user=request.user, expires_at__gt=timezone.now()
    ).first()
    if row is not None:
        RememberedComputer.objects.filter(pk=row.pk).update(last_used_at=timezone.now())
    return row


def remember(request, response):
    """Remember this browser for this user for 30 days (replacing whatever this browser remembered before)."""
    old = request.COOKIES.get(settings.REMEMBER_COOKIE_NAME, "")
    if old and len(old) <= 100:
        RememberedComputer.objects.filter(token_hash=_hash(old)).delete()
    token = secrets.token_urlsafe(32)
    row = RememberedComputer.objects.create(
        user=request.user,
        token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(days=REMEMBER_DAYS),
        ip=client_ip(request)[:45],
        agent=request.META.get("HTTP_USER_AGENT", "")[:200],
    )
    response.set_cookie(
        settings.REMEMBER_COOKIE_NAME,
        token,
        max_age=REMEMBER_DAYS * 24 * 3600,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Lax",
    )
    return row


def forget(request, response):
    token = request.COOKIES.get(settings.REMEMBER_COOKIE_NAME, "")
    if token and len(token) <= 100:
        RememberedComputer.objects.filter(token_hash=_hash(token), user=request.user).delete()
    response.delete_cookie(settings.REMEMBER_COOKIE_NAME, samesite="Lax")
    security_log.info("two-step forget computer user=%s ip=%s", request.user.get_username(), client_ip(request))


# ---- reset --------------------------------------------------------------------------------------------------------


def reset(user):
    """Lost phone: remove the person's Authenticator and remembered computers, open a new 72-hour setup window."""
    with transaction.atomic():
        for device in TOTPDevice.objects.filter(user=user):
            device.delete()
        for row in RememberedComputer.objects.filter(user=user):
            row.delete()
        profile = profile_of(user)
        profile.setup_until = timezone.now() + SETUP_WINDOW
        profile.save()
    security_log.info("two-step reset user=%s", user.get_username())


# ---- passwords ----------------------------------------------------------------------------------------------------


@receiver(pre_save, sender=User, dispatch_uid="two-step-password-before")
def _password_before(sender, instance, raw=False, **kwargs):
    instance._two_step_old_hash = None
    if not raw and instance.pk is not None:
        instance._two_step_old_hash = User.objects.filter(pk=instance.pk).values_list("password", flat=True).first()


@receiver(post_save, sender=User, dispatch_uid="two-step-password-after")
def _password_after(sender, instance, created, raw=False, **kwargs):
    """A password set by someone else (an admin) must be replaced by the person's own at their next sign-in; their own
    change clears that. Any password change ends every remembered computer. Commands (no request) force nothing."""
    if raw:
        return
    changed = created or (instance._two_step_old_hash not in (None, instance.password))
    if not changed:
        return
    request = history.current_request()
    actor = getattr(request, "user", None) if request is not None else None
    signed_in = actor is not None and actor.is_authenticated
    update_fields = kwargs.get("update_fields")
    if not signed_in and update_fields is not None and set(update_fields) == {"password"}:
        return  # Django re-hashing the same password at sign-in (a stronger hasher), not a new password
    if not created:
        for row in RememberedComputer.objects.filter(user=instance):
            row.delete()
    if not signed_in:
        return
    must_change = actor.pk != instance.pk
    if created:
        # The admin's add page saves the profile (its inline) after the user: set the flag once both are saved.
        transaction.on_commit(lambda: _set_must_change(instance, must_change))
    else:
        _set_must_change(instance, must_change)


def _set_must_change(user, must_change):
    profile = profile_of(user)
    if profile.must_change_password != must_change:
        profile.must_change_password = must_change
        profile.save()

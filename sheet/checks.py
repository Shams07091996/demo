"""Deployment checks (`manage.py check --deploy`) for settings Django itself does not know about."""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import DatabaseError


@register(deploy=True)
def proxy_client_ip_header(app_configs, **kwargs):
    """Behind a proxy every request comes from the proxy: rate limits, lock-outs and history would all see one
    address unless the client-IP header is named."""
    if getattr(settings, "BEHIND_PROXY", False) and not settings.CLIENT_IP_META_KEY:
        return [
            Error(
                "DJANGO_BEHIND_PROXY=1 is set but DJANGO_CLIENT_IP_HEADER is not.",
                hint="Name the header your proxy sets with the client's address, "
                "e.g. DJANGO_CLIENT_IP_HEADER=X-Forwarded-For.",
                id="sheet.E001",
            )
        ]
    return []


@register(Tags.database, deploy=True)
def two_step_key_holders(app_configs, databases=None, **kwargs):
    """Superusers reset each other's two-step login: with fewer than two who can sign in, one lost phone leaves only
    the server command. Reads the database, so it runs with `check --deploy --database default`."""
    if not databases:
        return []
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    try:
        holders = (
            User.objects.filter(is_superuser=True, is_active=True)
            .filter(pk__in=TOTPDevice.objects.filter(confirmed=True).values("user_id"))
            .count()
        )
    except DatabaseError:
        return []  # no database (yet): nothing to check
    if holders >= 2:
        return []
    return [
        Warning(
            f"Only {holders} active superuser(s) with a confirmed Authenticator.",
            hint="Keep at least two, so one can reset the other's two-step login after a lost phone.",
            id="sheet.W002",
        )
    ]

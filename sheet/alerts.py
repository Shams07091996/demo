"""Alerting (A09): when lock-outs, denied requests or server errors pass a threshold within a time window, write one
`sheet.alert` ERROR record and, if ADMINS is set (DJANGO_ALERT_EMAILS), e-mail the admins. Never raises."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import mail_admins
from django.db import DatabaseError

from . import ratelimit

KINDS = {"login_lockout", "denied", "server_error"}
alert_log = logging.getLogger("sheet.alert")
security_log = logging.getLogger("sheet.security")


def note(kind):
    """Count one event of `kind`; alert once when the count reaches the threshold in the current window."""
    if kind not in KINDS:
        raise ValueError(kind)
    span = timedelta(seconds=settings.ALERT_WINDOW_SECONDS)
    try:
        count = ratelimit.hit(f"alert|{kind}", span)
    except DatabaseError:
        security_log.error("alert counter failed kind=%s", kind)
        return
    if count != settings.ALERT_THRESHOLD:
        return
    minutes = settings.ALERT_WINDOW_SECONDS // 60
    message = f"{count} {kind} events within {minutes} minutes."
    alert_log.error("alert kind=%s count=%s window_minutes=%s", kind, count, minutes)
    if settings.ADMINS:
        mail_admins(f"Security alert: {kind}", message, fail_silently=True)

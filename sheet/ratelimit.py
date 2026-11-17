"""API rate limits (A06): writes per user and per address, CSV exports per user, counted in the database.

Requests are counted, not rows (a 200-row bulk add is one request). If the counter table fails, writes are refused
(fail closed) and reads go through (fail open)."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .errors import ServiceUnavailable, TooManyRequests
from .models import RateCounter
from .netutils import client_ip

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
TIDY_AFTER = timedelta(hours=1)
security_log = logging.getLogger("sheet.security")


def window():
    return timedelta(seconds=settings.RATE_LIMIT_WINDOW_SECONDS)


def hit(key, span):
    """Count one request for `key` in a window of length `span`; returns the count in the current window."""
    now = timezone.now()
    with transaction.atomic():
        keep = max(span, TIDY_AFTER, window(), timedelta(seconds=settings.ALERT_WINDOW_SECONDS))
        RateCounter.objects.filter(window_start__lte=now - keep).delete()  # only counters no window can still use
        if not RateCounter.objects.filter(key=key, window_start__gt=now - span).update(count=F("count") + 1):
            # No counter yet, or its window is over: start a new window.
            if not RateCounter.objects.filter(key=key).update(count=1, window_start=now):
                try:
                    with transaction.atomic():
                        RateCounter.objects.create(key=key, count=1, window_start=now)
                except IntegrityError:  # another request created it first
                    RateCounter.objects.filter(key=key).update(count=F("count") + 1)
        return RateCounter.objects.filter(key=key).values_list("count", flat=True).first() or 0


def _limits(request, scope):
    ip = client_ip(request)
    if scope == "export":
        return {f"export|user|{request.user.pk}": settings.RATE_LIMIT_EXPORTS_PER_USER}
    return {
        f"write|user|{request.user.pk}": settings.RATE_LIMIT_WRITES_PER_USER,
        f"write|ip|{ip}": settings.RATE_LIMIT_WRITES_PER_IP,
    }


def check(request, scope=None):
    """Count this request; raise TooManyRequests (429) over a limit. scope None = API call (only writes count)."""
    if scope is None:
        if request.method not in WRITE_METHODS:
            return
        scope = "write"
    try:
        over = [key for key, limit in _limits(request, scope).items() if hit(key, window()) > limit]
    except DatabaseError:
        security_log.error("rate limit store failed scope=%s user=%s", scope, request.user)
        if scope == "write":
            raise ServiceUnavailable() from None
        return
    if over:
        security_log.warning("rate limited scope=%s user=%s ip=%s", scope, request.user, client_ip(request))
        raise TooManyRequests()

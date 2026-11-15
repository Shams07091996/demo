"""Slow down password guessing: lock a (IP, username) pair, and an IP overall, after repeated failures."""

from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import LoginAttempt

MAX_PAIR_FAILURES = 5  # same IP + same username
MAX_IP_FAILURES = 30  # same IP, any username
WINDOW = timedelta(minutes=15)


def _keys(ip, username):
    return {f"pair|{ip}|{username.strip().lower()[:100]}": MAX_PAIR_FAILURES, f"ip|{ip}": MAX_IP_FAILURES}


def is_blocked(ip, username):
    now = timezone.now()
    for key, limit in _keys(ip, username).items():
        attempt = LoginAttempt.objects.filter(key=key, window_start__gt=now - WINDOW).first()
        if attempt and attempt.failures >= limit:
            return True
    return False


def record_failure(ip, username):
    now = timezone.now()
    with transaction.atomic():
        LoginAttempt.objects.filter(window_start__lte=now - WINDOW).delete()  # tidy expired rows
        for key in _keys(ip, username):
            attempt, created = LoginAttempt.objects.get_or_create(
                key=key, defaults={"failures": 1, "window_start": now}
            )
            if not created:
                LoginAttempt.objects.filter(pk=attempt.pk).update(failures=F("failures") + 1)


def reset(ip, username):
    LoginAttempt.objects.filter(key=f"pair|{ip}|{username.strip().lower()[:100]}").delete()

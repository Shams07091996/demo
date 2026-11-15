"""Security events: failed / successful logins feed the throttle and the logs (OWASP A07, A09)."""

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import throttle
from .netutils import client_ip

security_log = logging.getLogger("sheet.security")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    ip = client_ip(request) if request is not None else "unknown"
    username = str(credentials.get("username", ""))
    throttle.record_failure(ip, username)
    security_log.warning("login failed ip=%s username=%r", ip, username[:50])  # %r stops log injection


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    ip = client_ip(request)
    throttle.reset(ip, user.get_username())
    security_log.info("login ok user=%s ip=%s", user.get_username(), ip)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        security_log.info("logout user=%s ip=%s", user.get_username(), client_ip(request))

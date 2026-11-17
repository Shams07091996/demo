"""Deployment checks (`manage.py check --deploy`) for settings Django itself does not know about."""

from django.conf import settings
from django.core.checks import Error, register


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

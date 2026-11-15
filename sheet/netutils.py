import ipaddress

from django.conf import settings


def client_ip(request):
    """The caller's IP. Only trusts a proxy header if DJANGO_CLIENT_IP_HEADER is configured."""
    if settings.CLIENT_IP_META_KEY:
        candidate = request.META.get(settings.CLIENT_IP_META_KEY, "").split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass  # missing or malformed: fall back to the socket address
    return request.META.get("REMOTE_ADDR", "unknown")

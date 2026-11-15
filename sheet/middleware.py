"""Request / response hardening: login lock-out, security headers, no caching of private pages."""

import logging

from django.conf import settings
from django.shortcuts import render

from . import throttle
from .netutils import client_ip

security_log = logging.getLogger("sheet.security")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # Modern browsers use the two precise rules below; the plain style-src is the fallback for old ones.
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "style-src-elem 'self' https://fonts.googleapis.com",
        "style-src-attr 'unsafe-inline'",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


class LoginThrottleMiddleware:
    """Refuse login attempts from an address that has failed too often. Covers /login/ AND the admin login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        login_paths = (settings.LOGIN_URL, f"/{settings.ADMIN_URL}login/")
        if request.method == "POST" and request.path in login_paths:
            ip = client_ip(request)
            if throttle.is_blocked(ip, request.POST.get("username", "")):
                security_log.warning("login locked ip=%s path=%s", ip, request.path)
                return render(request, "sheet/locked.html", status=429)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # The Django admin ships its own scripts and styles; leave it on Django's defaults.
        if not request.path.startswith(f"/{settings.ADMIN_URL}"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        # Pages and API answers contain private data: never keep them in a browser or proxy cache.
        if not request.path.startswith(f"/{settings.STATIC_URL.lstrip('/')}"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

"""Request / response hardening: login lock-out, security headers, no caching of private pages."""

import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from . import alerts, throttle, twostep
from .netutils import client_ip

security_log = logging.getLogger("sheet.security")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # No inline styles at all: screens set styles through el.style (CSSOM), which this does not block.
        "style-src 'self'",
        "style-src-elem 'self'",
        "style-src-attr 'none'",
        # Trusted Types: the browser refuses every HTML-string sink (innerHTML …), and no policy may be created.
        "require-trusted-types-for 'script'",
        "trusted-types 'none'",
        "font-src 'none'",  # the system font: no web fonts at all
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

# The Django admin: same rules, except that its own scripts (jQuery, select2…) build HTML from text and may set style
# attributes, so no Trusted Types there and style attributes allowed. Scripts still come only from this site.
ADMIN_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "style-src-elem 'self'",
        "style-src-attr 'unsafe-inline'",
        "font-src 'none'",
        "img-src 'self' data:",
        "connect-src 'self'",
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
                alerts.note("login_lockout")
                return render(request, "sheet/locked.html", status=429)
        return self.get_response(request)


class TwoStepMiddleware:
    """The one gate of the two-step login: a signed-in person who hasn't passed the code step (or must still choose
    their own password) reaches only the page of that step, the sign-in pages, Log out and static files. API calls
    answer 401 (the page then goes back to sign-in), the CSV export 401, every other page (admin pages included)
    redirects to the step."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated or self._always_open(request.path):
            return self.get_response(request)
        step = twostep.next_step(request)
        if step is None or request.path == reverse(step):
            return self.get_response(request)
        if request.path.startswith("/api/"):
            return JsonResponse({"error": "Please log in again."}, status=401)
        if request.path == reverse("export_csv"):
            return HttpResponse(status=401)
        return redirect(step)

    @staticmethod
    def _always_open(path):
        admin = f"/{settings.ADMIN_URL}"
        open_paths = (settings.LOGIN_URL, reverse("logout"), f"{admin}login/", f"{admin}logout/")
        return path in open_paths or path.startswith(f"/{settings.STATIC_URL.lstrip('/')}")


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        admin = request.path.startswith(f"/{settings.ADMIN_URL}")
        response.headers.setdefault("Content-Security-Policy", ADMIN_CSP if admin else CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        # Pages and API answers contain private data: never keep them in a browser or proxy cache.
        if not request.path.startswith(f"/{settings.STATIC_URL.lstrip('/')}"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

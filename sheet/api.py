"""Plumbing shared by the JSON endpoints: authentication, error mapping, parsing, audit log."""

import json
import logging
from functools import wraps

from django.http import JsonResponse

from . import ratelimit
from .access import profile_of
from .errors import ApiError, BadRequest
from .netutils import client_ip

audit_log = logging.getLogger("sheet.audit")


def log_safe(value):
    """Text for a log line: control characters (newlines, tabs...) are escaped, so a value typed by a user
    can never start a fake log line of its own."""
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in str(value))


def json_api(view):
    """Require a logged-in user, attach request.profile, and map our exceptions to JSON errors."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Please log in again."}, status=401)
        request.profile = profile_of(request.user)
        try:
            ratelimit.check(request)
            return view(request, *args, **kwargs)
        except ApiError as error:
            if error.status == 403:
                audit_log.warning(
                    "denied user=%s ip=%s path=%s", request.user, client_ip(request), log_safe(request.path)
                )
            return JsonResponse({"error": str(error), **error.extra}, status=error.status)

    return wrapper


def read_json(request):
    """Parse the request body as a JSON object."""
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, RecursionError):  # includes bad JSON, bad encoding, absurd nesting
        raise BadRequest("Invalid JSON.") from None
    if not isinstance(data, dict):
        raise BadRequest("Expected a JSON object.")
    return data


def audit(request, action, **details):
    """Record who changed what."""
    extra = " ".join(f"{k}={log_safe(v)}" for k, v in details.items())
    audit_log.info("user=%s ip=%s action=%s %s", request.user, client_ip(request), action, extra)

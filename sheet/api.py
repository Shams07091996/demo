"""Plumbing shared by the JSON endpoints: authentication, error mapping, parsing, audit log."""

import json
import logging
import secrets
from functools import wraps

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.db import transaction
from django.http import Http404, JsonResponse

from . import alerts, ratelimit
from .access import profile_of
from .errors import ApiError, BadRequest
from .netutils import client_ip

audit_log = logging.getLogger("sheet.audit")
security_log = logging.getLogger("sheet.security")


def log_safe(value):
    """Text for a log line: control characters (newlines, tabs...) are escaped, so a value typed by a user
    can never start a fake log line of its own."""
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in str(value))


def server_error_response(request, as_json=True):
    """Log an unexpected exception with a short reference and answer with that reference (never a stack trace)."""
    ref = secrets.token_hex(4)
    try:
        user = str(request.user)
    except Exception:  # noqa: BLE001 - the user lookup itself may be what failed
        user = "?"
    security_log.error(
        "server error ref=%s user=%s ip=%s path=%s",
        ref,
        user,
        client_ip(request),
        log_safe(request.path),
        exc_info=True,
    )
    alerts.note("server_error")
    return ref, JsonResponse({"error": "Something went wrong.", "ref": ref}, status=500) if as_json else None


def json_api(view):
    """Require a logged-in user, attach request.profile, and map our exceptions to JSON errors."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Please log in again."}, status=401)
        request.profile = profile_of(request.user)
        try:
            ratelimit.check(request)
            if request.method in ratelimit.WRITE_METHODS:
                # One transaction per write: the change and its history record are saved together or not at all.
                with transaction.atomic():
                    return view(request, *args, **kwargs)
            return view(request, *args, **kwargs)
        except ApiError as error:
            if error.status == 403:
                audit_log.warning(
                    "denied user=%s ip=%s path=%s", request.user, client_ip(request), log_safe(request.path)
                )
                alerts.note("denied")
            return JsonResponse({"error": str(error), **error.extra}, status=error.status)
        except (Http404, PermissionDenied, SuspiciousOperation):
            raise  # Django answers these itself (handler404 → JSON for /api/)
        except Exception:  # anything unexpected: JSON with a reference, the details only in the log
            return server_error_response(request)[1]

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

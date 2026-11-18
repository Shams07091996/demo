"""HTTP handlers: the page, the JSON API and the CSV export."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from django.contrib.auth.views import redirect_to_login
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import csrf, defaults
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from . import calculations, listing, logistics, ratelimit, twostep
from . import dashboard as dashboard_figures
from .access import profile_of, require_admin, require_edit, scoped_vessels
from .api import audit, json_api, read_json, server_error_response
from .constants import (
    NO_AGENT,
    OPTION_KIND_KEYS,
    OPTION_KINDS,
    PORT_KEYS,
    PORT_LABELS,
    PORTS,
    SERVICE_TYPES,
    SUMMARY_FIELDS,
    TIME_FIELDS,
    TIME_KEYS,
)
from .errors import BadRequest, Forbidden, TooManyRequests
from .models import ChangeRecord, ExchangeRate, HotelStay, Option, Service, Transfer, Vessel
from .serializers import month_rates, option_to_dict, rate_to_dict, vessel_to_dict
from .validators import clean_agent, clean_service_data, clean_vessel

# ---- page -----------------------------------------------------------------------------------


@cache
def script_modules():
    """Every script file of the page ("sheet/js/....js"). The page lists them all as modulepreload links, so the
    browser fetches them at the same time instead of discovering them one import at a time."""
    js_dir = Path(__file__).resolve().parent / "static" / "sheet" / "js"
    return tuple(sorted("sheet/" + path.relative_to(js_dir.parent).as_posix() for path in js_dir.rglob("*.js")))


@ensure_csrf_cookie
def index(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    profile = profile_of(request.user)
    context = {
        "me": {
            "username": request.user.get_username(),
            "role": profile.role,
            "port": profile.port,
            "canEdit": profile.can_edit,
            "isAdmin": profile.is_admin,
            "seesAll": profile.port is None,
        },
        "ports": [{"key": key, "label": label} for key, label in PORTS],
        "service_types": SERVICE_TYPES,
        "no_agent": NO_AGENT,
        "summary_fields": list(SUMMARY_FIELDS),
        "option_kinds": [{"key": key, "label": label} for key, label in OPTION_KINDS],
        "time_fields": [{"key": key, "label": label} for key, label in TIME_FIELDS],
        # (element id prefix, page name, API name, Add button, empty-list text) for the two booking pages
        "booking_pages": [
            ("h", "hotels", "hotels", "+ Add hotel stay", "No hotel stays in this range."),
            ("t", "transport", "transfers", "+ Add transfer", "No transfers in this range."),
        ],
        "remembered": twostep.remembered_row(request) is not None,
        "script_modules": script_modules(),
    }
    return render(request, "sheet/index.html", context)


# ---- vessels --------------------------------------------------------------------------------


def _vessel_json(pk, status=200):
    """Re-read a vessel (with its services) and return it as a JSON response."""
    vessel = Vessel.objects.prefetch_related("services").get(pk=pk)
    return JsonResponse(vessel_to_dict(vessel, month_rates()), status=status)


@json_api
@require_http_methods(["GET", "POST"])
def vessels(request):
    if request.method == "GET":
        return JsonResponse(listing.list_response(request.profile, request.GET))

    require_edit(request.profile)
    vessel = Vessel.objects.create(**clean_vessel(read_json(request), request.profile))
    audit(request, "vessel.create", id=vessel.id, port=vessel.port)
    return _vessel_json(vessel.pk, status=201)


@json_api
@require_http_methods(["GET"])
def vessel_alerts(request):
    return JsonResponse(listing.alerts_response(request.profile, request.GET))


@json_api
@require_http_methods(["GET"])
def dashboard(request):
    return JsonResponse(dashboard_figures.response(request.profile, request.GET))


@json_api
@require_http_methods(["GET"])
def dashboard_jobs(request):
    return JsonResponse(dashboard_figures.jobs_response(request.profile, request.GET))


@json_api
@require_http_methods(["GET", "PUT", "PATCH", "DELETE"])
def vessel_detail(request, pk):
    vessel = get_object_or_404(scoped_vessels(request.profile), pk=pk)
    if request.method == "GET":
        return JsonResponse(vessel_to_dict(vessel, month_rates()))

    require_edit(request.profile)
    if request.method == "DELETE":
        vessel.delete()
        audit(request, "vessel.delete", id=pk)
        return JsonResponse({"ok": True})

    for field, value in clean_vessel(read_json(request), request.profile, vessel).items():
        setattr(vessel, field, value)
    vessel.save()
    audit(request, "vessel.update", id=vessel.id)
    return _vessel_json(vessel.pk)


# ---- services -------------------------------------------------------------------------------


def _read_service(request, vessel, current_agent=""):
    """(type, agent, data) of a service sent by the browser for `vessel`."""
    payload = read_json(request)
    service_type = payload.get("type")
    if service_type not in SERVICE_TYPES:
        raise BadRequest("Choose a service type.")
    agent = clean_agent(payload.get("agent"), vessel.port, current_agent)
    return service_type, agent, clean_service_data(service_type, payload.get("data"))


@json_api
@require_http_methods(["POST"])
def service_create(request, pk):
    require_edit(request.profile)
    vessel = get_object_or_404(scoped_vessels(request.profile, prefetch=False), pk=pk)
    service_type, agent, data = _read_service(request, vessel)
    service = Service.objects.create(vessel=vessel, service_type=service_type, agent=agent, data=data)
    audit(request, "service.create", id=service.id, vessel=vessel.id, type=service_type)
    return _vessel_json(vessel.pk, status=201)


@json_api
@require_http_methods(["PUT", "PATCH", "DELETE"])
def service_detail(request, pk):
    require_edit(request.profile)
    allowed = scoped_vessels(request.profile, prefetch=False)
    service = get_object_or_404(Service.objects.filter(vessel__in=allowed), pk=pk)
    if request.method == "DELETE":
        service.delete()
        audit(request, "service.delete", id=pk, vessel=service.vessel_id)
    else:
        service.service_type, service.agent, service.data = _read_service(request, service.vessel, service.agent)
        service.save()
        audit(request, "service.update", id=service.id, vessel=service.vessel_id)
    return _vessel_json(service.vessel_id)


# ---- exchange rates -------------------------------------------------------------------------


def _rates_json():
    return JsonResponse({"rates": [rate_to_dict(r) for r in ExchangeRate.objects.all()]})


def _read_rate(payload):
    try:
        year, month = str(payload.get("month", "")).split("-")
        first_of_month = date(int(year), int(month), 1)
        rate = Decimal(str(payload.get("rate")))
    except (ValueError, InvalidOperation):
        raise BadRequest("Enter a month and a rate.") from None
    if not rate.is_finite() or not 0 < rate < 1_000_000:
        raise BadRequest("Rate must be a positive number.")
    return first_of_month, rate


@json_api
@require_http_methods(["GET", "POST"])
def rates(request):
    if request.method == "POST":
        require_admin(request.profile)  # one rate per month, shared by every port
        first_of_month, rate = _read_rate(read_json(request))
        ExchangeRate.objects.update_or_create(month=first_of_month, defaults={"rate": rate})
        audit(request, "rate.save", month=first_of_month.isoformat(), rate=rate)
    return _rates_json()


@json_api
@require_http_methods(["DELETE"])
def rate_delete(request, pk):
    require_admin(request.profile)
    get_object_or_404(ExchangeRate, pk=pk).delete()
    audit(request, "rate.delete", id=pk)
    return _rates_json()


# ---- master data (OPR / POC options) --------------------------------------------------------


def _usage_counts(profile):
    """{kind: {value: how many visible vessels (OPR / POC / Agent) or bookings (Hotel / Airport / Port) use it}}"""
    vessels = scoped_vessels(profile, prefetch=False)
    counts = {
        kind: {row[kind]: row["n"] for row in vessels.values(kind).annotate(n=Count("id")).order_by()}
        for kind in OPTION_KIND_KEYS
        if kind not in BOOKING_KINDS and kind != "agent"
    }
    # An agent is used by a vessel when it entered it, sailed it or did any of its services (each vessel once).
    agent_vessels = {}
    for field in ("arrival_agent", "sailing_agent", "services__agent"):
        # No .exclude(): on services__agent it would drop a vessel when *any* of its services has no agent.
        for value, vessel_id in vessels.values_list(field, "id").order_by():
            if value:  # empty, or None for a vessel without services
                agent_vessels.setdefault(value, set()).add(vessel_id)
    counts["agent"] = {value: len(ids) for value, ids in agent_vessels.items()}
    for kind, field, models_using in (("hotel", "hotel", (HotelStay, Transfer)), ("airport", "airport", (Transfer,)),
                                      ("port", "port_name", (Transfer,))):
        found = {}
        for model in models_using:
            used = model.objects.filter(vessel__in=vessels).exclude(**{field: ""}).values(field).annotate(n=Count("id"))
            for row in used.order_by():
                found[row[field]] = found.get(row[field], 0) + row["n"]
        counts[kind] = found
    return counts


# Master-data kinds used by hotel stays / transfers rather than by vessels ("used by N bookings").
BOOKING_KINDS = ("hotel", "airport", "port")


def _options_json(profile):
    queryset = Option.objects.all()
    if profile.port:
        queryset = queryset.filter(port__in=["", profile.port])
    usage = _usage_counts(profile)
    options = [option_to_dict(o, profile, usage[o.kind].get(o.value, 0)) for o in queryset]
    return JsonResponse({"options": options})


@json_api
@require_http_methods(["GET", "POST"])
def options(request):
    profile = request.profile
    if request.method == "POST":
        require_edit(profile)
        payload = read_json(request)
        kind = payload.get("kind")
        value = str(payload.get("value", "")).strip()
        if len(value) > 100:
            raise BadRequest("The value is too long (at most 100 characters).")
        if kind not in OPTION_KIND_KEYS or not value:
            raise BadRequest("Enter a value.")
        scope = profile.port or payload.get("port") or ""
        if scope and scope not in PORT_KEYS:
            raise BadRequest("Unknown port.")
        last = Option.objects.filter(kind=kind).order_by("-position").first()
        _, created = Option.objects.get_or_create(
            kind=kind, value=value, port=scope, defaults={"position": last.position + 1 if last else 0}
        )
        if created:
            audit(request, "option.create", kind=kind, value=value, port=scope or "all")
    return _options_json(profile)


@json_api
@require_http_methods(["PATCH", "DELETE"])
def option_detail(request, pk):
    """DELETE removes a value (port users: their port's only); PATCH {port} moves it to a port or to all ports
    ("") — admins only."""
    profile = request.profile
    require_edit(profile)
    option = get_object_or_404(Option, pk=pk)
    if request.method == "PATCH":
        require_admin(profile)
        port = read_json(request).get("port") or ""
        if port and port not in PORT_KEYS:
            raise BadRequest("Unknown port.")
        if Option.objects.filter(kind=option.kind, value=option.value, port=port).exclude(pk=pk).exists():
            raise BadRequest("That value already exists for that port.")
        option.port = port
        option.save(update_fields=["port"])
        audit(request, "option.port", id=pk, port=port or "all")
        return _options_json(profile)
    if not profile.is_admin and option.port != profile.port:
        raise Forbidden("You can only remove options for your own port.")
    option.delete()
    audit(request, "option.delete", id=pk)
    return _options_json(profile)


# ---- CSV export -----------------------------------------------------------------------------


def _csv_safe(cell):
    """Stop spreadsheet formula injection when the file is opened in Excel."""
    cell = str(cell)
    return "'" + cell if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell


def _display_time(local_iso_value):
    """'2026-11-13T08:30' -> '13.11.2026 08:30'"""
    if not local_iso_value:
        return ""
    day, clock = local_iso_value.split("T")
    return f"{'.'.join(reversed(day.split('-')))} {clock}"


@require_http_methods(["GET"])
def export_csv(request):
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    try:
        ratelimit.check(request, "export")
    except TooManyRequests as error:
        return JsonResponse({"error": str(error)}, status=error.status)
    profile = profile_of(request.user)
    try:
        filters = listing.parse_filters(request.GET, paged=False)
    except BadRequest as error:
        return HttpResponse(str(error), status=400, content_type="text/plain; charset=utf-8")
    rows = listing.matching(listing.range_rows(profile, filters), filters)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="vessels.csv"'
    response.write("\ufeff")  # byte-order mark so Excel reads UTF-8
    writer = csv.writer(response)
    writer.writerow(
        ["Vessel", "OPR", "POC", "Arrival agent", "Sailing agent", "Port", "Date", "Status"]
        + [label for _, label in TIME_FIELDS]
        + ["Services", "Total Cost LE", "Total Profit LE"]
    )
    for data in rows:
        writer.writerow(
            [
                _csv_safe(data["name"]),
                _csv_safe(data["opr"]),
                _csv_safe(data["poc"]),
                _csv_safe(data["arrival_agent"]),
                _csv_safe(data["sailing_agent"]),
                PORT_LABELS.get(data["port"], data["port"]),
                date.fromisoformat(data["date"]).strftime("%d.%m.%Y"),
                data["status"],
                *[_display_time(data[key]) for key in TIME_KEYS],
                _csv_safe(", ".join(s["type"] for s in data["services"])),
                data["total_cost_egp"],
                data["total_profit_egp"],
            ]
        )
    audit(request, "export.csv")
    return response


# ---- hotels and transport (see logistics.py) ---------------------------------------------------

_AUDIT_NAME = {"hotels": "hotel", "transfers": "transfer"}


@json_api
@require_http_methods(["GET", "POST"])
def bookings(request, kind):
    profile = request.profile
    if request.method == "GET":
        return JsonResponse(logistics.list_response(kind, profile, request.GET))
    require_edit(profile)
    booking = logistics.save_booking(kind, profile, read_json(request))
    audit(request, f"{_AUDIT_NAME[kind]}.create", id=booking.id, vessel=booking.vessel_id)
    return JsonResponse(logistics.booking_to_dict(kind, booking, profile), status=201)


@json_api
@require_http_methods(["GET", "PUT", "DELETE"])
def booking_detail(request, kind, pk):
    profile = request.profile
    booking = logistics.get_booking(kind, profile, pk)
    if request.method == "GET":
        return JsonResponse(logistics.booking_to_dict(kind, booking, profile))
    require_edit(profile)
    if request.method == "DELETE":
        booking.delete()
        audit(request, f"{_AUDIT_NAME[kind]}.delete", id=pk)
        return JsonResponse({"ok": True})
    booking = logistics.save_booking(kind, profile, read_json(request), existing=booking)
    audit(request, f"{_AUDIT_NAME[kind]}.update", id=booking.id)
    return JsonResponse(logistics.booking_to_dict(kind, booking, profile))


@json_api
@require_http_methods(["GET"])
def vessel_crew(request, pk):
    """The vessel's crew-change guests, for picking hotel / transfer guests."""
    vessel = get_object_or_404(scoped_vessels(request.profile, prefetch=False), pk=pk)
    return JsonResponse({"crew": logistics.crew_of(vessel)})


# ---- calculations (see calculations.py) --------------------------------------------------------


@json_api
@require_http_methods(["GET"])
def calculations_list(request):
    """Every money line of the vessels in range / OPR / port, with totals. Every role may read it."""
    return JsonResponse(calculations.response(request.profile, request.GET))


def _is_api(request):
    return request.path.startswith("/api/")


def bad_request(request, exception=None):
    if _is_api(request):
        return JsonResponse({"error": "Bad request."}, status=400)
    return defaults.bad_request(request, exception)


def forbidden(request, exception=None):
    if _is_api(request):
        return JsonResponse({"error": "You do not have permission to do that."}, status=403)
    return defaults.permission_denied(request, exception)


def csrf_failure(request, reason=""):
    """A missing or stale CSRF token: under /api/ the page shows the message (e.g. after signing in in another tab)."""
    if _is_api(request):
        return JsonResponse({"error": "Your session changed — reload the page and try again."}, status=403)
    return csrf.csrf_failure(request, reason)


def not_found(request, exception=None):
    if _is_api(request):
        return JsonResponse({"error": "Not found."}, status=404)
    return HttpResponse(render_to_string("404.html"), status=404)


def server_error(request):
    """handler500: errors outside json_api (pages, CSV export). Logged with a reference, shown without details."""
    ref, response = server_error_response(request, as_json=_is_api(request))
    if response is not None:
        return response
    return HttpResponse(render_to_string("500.html", {"ref": ref}), status=500)


HISTORY_PAGE_SIZES = (10, 25, 50, 100)


@json_api
@require_http_methods(["GET"])
def history_list(request):
    """The change history, newest first; admins only (it spans every port). Filters: from / to (dates, Cairo time),
    type (object type), user (username), page, page_size."""
    require_admin(request.profile)
    params = request.GET
    date_from, date_to = listing.date_param(params, "from"), listing.date_param(params, "to")
    if date_from and date_to and date_from > date_to:
        raise BadRequest("From must be on or before To.")
    page = listing.int_param(params, "page", 1, 1, 10**9, "Page must be a whole number from 1.")
    page_size = listing.int_param(params, "page_size", 25, 1, 100, "Rows per page must be 10, 25, 50 or 100.")
    if page_size not in HISTORY_PAGE_SIZES:
        raise BadRequest("Rows per page must be 10, 25, 50 or 100.")
    rows = ChangeRecord.objects.all()
    if date_from:
        rows = rows.filter(at__date__gte=date_from)
    if date_to:
        rows = rows.filter(at__date__lte=date_to)
    if params.get("type"):
        rows = rows.filter(object_type=params["type"][:30])
    if params.get("user"):
        rows = rows.filter(username=params["user"][:150])
    count = rows.count()
    pages = max(1, -(-count // page_size))
    page = min(page, pages)
    start = (page - 1) * page_size
    records = [
        {
            "id": r.id,
            "at": timezone.localtime(r.at).isoformat(),
            "username": r.username,
            "ip": r.ip,
            "action": r.action,
            "object_type": r.object_type,
            "object_id": r.object_id,
            "port": r.port,
            "changes": r.changes,
        }
        for r in rows.order_by("-id")[start : start + page_size]
    ]
    return JsonResponse({"records": records, "count": count, "pages": pages, "page": page})

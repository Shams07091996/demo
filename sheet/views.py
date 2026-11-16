"""HTTP handlers: the page, the JSON API and the CSV export."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from . import calculations, listing, logistics
from .access import profile_of, require_admin, require_edit, scoped_vessels
from .api import audit, json_api, read_json
from .constants import (
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
from .errors import BadRequest, Forbidden
from .models import ExchangeRate, HotelStay, Option, Service, Transfer, Vessel
from .serializers import month_rates, option_to_dict, rate_to_dict, vessel_to_dict
from .validators import clean_bulk, clean_service_data, clean_vessel

# ---- page -----------------------------------------------------------------------------------


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
        "summary_fields": list(SUMMARY_FIELDS),
        "option_kinds": [{"key": key, "label": label} for key, label in OPTION_KINDS],
        "time_fields": [{"key": key, "label": label} for key, label in TIME_FIELDS],
        # (element id prefix, page name, API name, Add button, empty-list text) for the two booking pages
        "booking_pages": [
            ("h", "hotels", "hotels", "+ Add hotel stay", "No hotel stays in this range."),
            ("t", "transport", "transfers", "+ Add transfer", "No transfers in this range."),
        ],
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
@require_http_methods(["POST"])
def vessels_bulk(request):
    """Create many vessels in one go (e.g. pasted from Excel). All-or-nothing."""
    require_edit(request.profile)
    payload = read_json(request)
    rows = clean_bulk(payload.get("rows"), request.profile, default_port=payload.get("port"))
    with transaction.atomic():
        created = Vessel.objects.bulk_create([Vessel(**fields) for fields in rows])
    audit(request, "vessel.bulk_create", count=len(created), port=request.profile.port or "any")
    rates = month_rates()
    return JsonResponse({"vessels": [vessel_to_dict(v, rates) for v in created]}, status=201)


@json_api
@require_http_methods(["POST"])
def vessels_bulk_check(request):
    """Which pasted rows already exist (bulk-add preview marks them as duplicates). Changes nothing."""
    require_edit(request.profile)
    payload = read_json(request)
    existing = listing.existing_rows(request.profile, payload.get("rows"), payload.get("port"))
    return JsonResponse({"existing": existing})


@json_api
@require_http_methods(["GET"])
def vessel_alerts(request):
    return JsonResponse(listing.alerts_response(request.profile, request.GET))


@json_api
@require_http_methods(["GET"])
def dashboard(request):
    return JsonResponse(listing.dashboard_response(request.profile, request.GET))


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


def _read_service(request):
    payload = read_json(request)
    service_type = payload.get("type")
    if service_type not in SERVICE_TYPES:
        raise BadRequest("Choose a service type.")
    return service_type, clean_service_data(service_type, payload.get("data"))


@json_api
@require_http_methods(["POST"])
def service_create(request, pk):
    require_edit(request.profile)
    vessel = get_object_or_404(scoped_vessels(request.profile, prefetch=False), pk=pk)
    service_type, data = _read_service(request)
    service = Service.objects.create(vessel=vessel, service_type=service_type, data=data)
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
        service.service_type, service.data = _read_service(request)
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
        if kind not in BOOKING_KINDS
    }
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
        value = str(payload.get("value", "")).strip()[:100]
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
@require_http_methods(["DELETE"])
def option_delete(request, pk):
    profile = request.profile
    require_edit(profile)
    option = get_object_or_404(Option, pk=pk)
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
        ["Vessel", "OPR", "POC", "Agent", "Port", "Date", "Status"]
        + [label for _, label in TIME_FIELDS]
        + ["Services", "Total Cost LE", "Total Profit LE"]
    )
    for data in rows:
        writer.writerow(
            [
                _csv_safe(data["name"]),
                _csv_safe(data["opr"]),
                _csv_safe(data["poc"]),
                _csv_safe(data["agent"]),
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

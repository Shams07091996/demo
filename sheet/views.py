"""HTTP handlers: the page, the JSON API and the CSV export."""

import csv
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import csrf, defaults
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from . import (
    accounting,
    branding,
    calculations,
    closures,
    conflicts,
    crewbookings,
    dataexport,
    disposal,
    history,
    listing,
    logistics,
    logpdf,
    ratelimit,
    receipt,
    report,
    twostep,
)
from . import dashboard as dashboard_figures
from .access import profile_of, require_accounting, require_admin, require_edit, scoped_closures, scoped_vessels
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
from .models import (
    ChangeRecord,
    DisposalPrice,
    ExchangeRate,
    HotelStay,
    Option,
    Service,
    Transfer,
    Vessel,
    VesselDisposal,
)
from .serializers import month_rates, option_to_dict, rate_to_dict, vessel_to_dict
from .validators import (
    clean_agent,
    clean_booking_refs,
    clean_disposal_price,
    clean_disposal_quantities,
    clean_receipt,
    clean_service_data,
    clean_service_status,
    clean_vessel,
)

security_log = logging.getLogger("sheet.security")

# ---- page -----------------------------------------------------------------------------------


@cache
def script_modules():
    """Every script file of the page ("sheet/js/....js"). The page lists them all as modulepreload links, so the
    browser fetches them at the same time instead of discovering them one import at a time."""
    js_dir = Path(__file__).resolve().parent / "static" / "sheet" / "js"
    return tuple(sorted("sheet/" + path.relative_to(js_dir.parent).as_posix() for path in js_dir.rglob("*.js")))


@require_http_methods(["GET", "HEAD"])
def brand_logo(request):
    """The company logo from the letterhead folder (branding.py); open without sign-in, as the sign-in page shows it."""
    data = branding.logo_bytes()
    if data is None:
        raise Http404
    response = HttpResponse(data, content_type="image/png")
    response["Cache-Control"] = "max-age=3600"
    return response


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


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _export_range(request):
    """(from, to, port) of a workbook request: both dates required, at most 24 months; port users get their port."""
    date_from, date_to = listing.date_param(request.GET, "from"), listing.date_param(request.GET, "to")
    if not date_from or not date_to:
        raise BadRequest("Choose a From and To date.")
    if date_from > date_to:
        raise BadRequest("From must be on or before To.")
    if (date_to.year * 12 + date_to.month) - (date_from.year * 12 + date_from.month) >= 24:
        raise BadRequest("Choose a range of at most 24 months.")
    port = request.profile.port or (request.GET.get("port") if request.GET.get("port") in PORT_LABELS else None)
    return date_from, date_to, port


def _xlsx_response(content, filename):
    response = HttpResponse(content, content_type=XLSX_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@json_api
@require_http_methods(["GET"])
def dashboard_export(request):
    """The management workbook (.xlsx) for a From–To range and port. Every role may download it; port users get
    their own port whatever they ask."""
    ratelimit.check(request, "export")
    date_from, date_to, port = _export_range(request)
    r = report.Range(date_from, date_to, port)
    content = report.workbook(request.profile, r, timezone.now())
    audit(request, "dashboard.export", date_from=date_from, date_to=date_to, port=port or "all")
    return _xlsx_response(content, f"Management {report.port_label(r)} {date_from.isoformat()} to "
                                   f"{date_to.isoformat()}.xlsx")


@json_api
@require_http_methods(["GET"])
def data_export(request, page):
    """One page's rows (its own list query, every page of it) as a plain-table .xlsx for other programs."""
    if page not in dataexport.PAGES:
        raise Http404
    ratelimit.check(request, "export")
    content = dataexport.page_file(page, request.profile, request.GET)
    # Which filters were used, not their values: a search is often a person's name.
    audit(request, "data.export", page=page, filters=",".join(sorted(request.GET))[:200])
    today = timezone.localdate().isoformat()
    return _xlsx_response(content, f"{dataexport.TITLES[page]} {today}.xlsx")


@json_api
@require_http_methods(["GET"])
def data_export_all(request):
    """The five pages' rows for a From–To range and port, one sheet each."""
    ratelimit.check(request, "export")
    date_from, date_to, port = _export_range(request)
    content = dataexport.all_file(request.profile, date_from, date_to, port)
    audit(request, "data.export", page="all", date_from=date_from, date_to=date_to, port=port or "all")
    label = PORT_LABELS.get(port, "All ports") if port else "All ports"
    return _xlsx_response(content, f"All data {label} {date_from.isoformat()} to {date_to.isoformat()}.xlsx")


@json_api
@require_http_methods(["GET", "PUT", "PATCH", "DELETE"])
def vessel_detail(request, pk):
    vessel = get_object_or_404(scoped_vessels(request.profile), pk=pk)
    if request.method == "GET":
        return JsonResponse(vessel_to_dict(vessel, month_rates()))

    require_edit(request.profile)
    if request.method == "DELETE":
        accounting.require_vessel_open(vessel)
        vessel.delete()
        audit(request, "vessel.delete", id=pk)
        return JsonResponse({"ok": True})

    payload = read_json(request)
    vessel = conflicts.locked(vessel, payload, request.user)
    before = conflicts.snapshot(vessel)
    for field, value in clean_vessel(payload, request.profile, vessel).items():
        setattr(vessel, field, value)
    conflicts.bump_if_changed(vessel, before)
    vessel.save()
    crewbookings.sync(vessel)  # draft dates follow the vessel date (e.g. it became the sailing day)
    audit(request, "vessel.update", id=vessel.id)
    return _vessel_json(vessel.pk)


# ---- services -------------------------------------------------------------------------------


def _read_service(request, vessel, existing=None):
    """{service_type, agent, data, status, cancel_reason} of a service sent by the browser for `vessel`."""
    payload = read_json(request)
    service_type = payload.get("type")
    if service_type not in SERVICE_TYPES:
        raise BadRequest("Choose a service type.")
    agent = clean_agent(payload.get("agent"), vessel.port, getattr(existing, "agent", ""))
    status, reason = clean_service_status(payload, existing)
    return {"service_type": service_type, "agent": agent, "data": clean_service_data(service_type, payload.get("data")),
            "status": status, "cancel_reason": reason}


@json_api
@require_http_methods(["POST"])
def service_create(request, pk):
    require_edit(request.profile)
    vessel = get_object_or_404(scoped_vessels(request.profile, prefetch=False), pk=pk)
    fields = _read_service(request, vessel)
    service = Service.objects.create(vessel=vessel, **fields)
    crewbookings.sync(vessel)
    audit(request, "service.create", id=service.id, vessel=vessel.id, type=service.service_type)
    return _vessel_json(vessel.pk, status=201)


@json_api
@require_http_methods(["PUT", "PATCH", "DELETE"])
def service_detail(request, pk):
    require_edit(request.profile)
    allowed = scoped_vessels(request.profile, prefetch=False)
    service = get_object_or_404(Service.objects.filter(vessel__in=allowed), pk=pk)
    if request.method == "DELETE":
        accounting.require_open(service)
        service.delete()
        audit(request, "service.delete", id=pk, vessel=service.vessel_id)
    else:
        payload = read_json(request)
        service = conflicts.locked(service, payload, request.user)
        accounting.require_open(service)  # the fresh row: a dialog opened before accounting closed it is refused too
        refs = clean_booking_refs(payload.get("cancel_bookings"))
        before = conflicts.snapshot(service)
        for field, value in _read_service(request, service.vessel, service).items():
            setattr(service, field, value)
        conflicts.bump_if_changed(service, before)
        service.save()
        cancelled = crewbookings.cancel_bookings(service, refs)
        extra = {"cancelled_bookings": ",".join(f"{kind}:{pk}" for kind, pk in cancelled)} if cancelled else {}
        audit(request, "service.update", id=service.id, vessel=service.vessel_id, **extra)
    crewbookings.sync(service.vessel)  # automatic bookings follow the crew (a deleted service drops its drafts)
    return _vessel_json(service.vessel_id)


@json_api
@require_http_methods(["GET"])
def service_bookings(request, pk):
    """A Crew Change's saved hotel stays and transfers, for the dialog's "cancel these too" list."""
    allowed = scoped_vessels(request.profile, prefetch=False)
    service = get_object_or_404(Service.objects.filter(vessel__in=allowed), pk=pk)
    bookings = crewbookings.saved_bookings(service)
    return JsonResponse({"bookings": [crewbookings.booking_ref(kind, booking) for kind, booking in bookings]})


# ---- LOG letter (see logpdf.py) --------------------------------------------------------------

_LETTERHEAD_FILES = {"logo": "logo.jpg", "stamp": "stamp.jpg", "footer": "footer.jpg"}
_MAX_IMAGE_BYTES = 2_000_000


def _letterhead_images():
    """The letterhead JPEGs from settings.LETTERHEAD_DIR (fixed names only); a missing / unreadable one is None."""
    folder = settings.LETTERHEAD_DIR
    images = {}
    for name, file_name in _LETTERHEAD_FILES.items():
        images[name] = None
        if not folder:
            continue
        try:
            path = Path(folder, file_name)
            if path.is_file() and path.stat().st_size <= _MAX_IMAGE_BYTES:
                images[name] = path.read_bytes()
        except OSError:
            security_log.warning("letterhead image unreadable name=%s", name)
    return images


def _file_name_part(text):
    return " ".join(re.sub(r"[^A-Za-z0-9 -]", "", str(text)).split())[:60]


# The date that followed the airline on a pasted FLIGHT line ("EMIRATES   TUE 17 NOVEMBER 2026"); crew saved before the
# parser fix (crewParsing.js FLIGHT_DATE_TAIL, same rule) still have it in the airline.
AIRLINE_DATE_TAIL = re.compile(
    r"\s+(?:(?:MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*\s+\d{1,2}\b|\d{1,2}\s+[A-Z]{3,}\s+\d{2,4}\b).*$", re.I | re.S
)


@json_api
@require_http_methods(["GET"])
def service_log(request, pk, uid):
    """The LOG letter (PDF) of one on-signer of a Crew Change. Anyone who can edit the vessel may make it."""
    require_edit(request.profile)
    ratelimit.check(request, "export")
    allowed = scoped_vessels(request.profile, prefetch=False)
    service = get_object_or_404(Service.objects.filter(vessel__in=allowed, service_type="Crew Change")
                                .select_related("vessel"), pk=pk)
    person = next((m for m in (service.data or {}).get("onSigners") or []
                   if isinstance(m, dict) and m.get("uid") == uid), None)
    if person is None:
        raise Http404
    segments = (person.get("flightStructured") or {}).get("segments") or []
    airline = (segments[0].get("airline") if segments and isinstance(segments[0], dict) else "") or ""
    vessel = service.vessel
    fields = {
        "to": AIRLINE_DATE_TAIL.sub("", str(airline)).strip(),
        "date": timezone.localdate().strftime("%d/%m/%Y"),
        "vessel": vessel.name,
        "flight": person.get("flightData") or "",
        "personal": person.get("personalData") or "",
    }
    pdf = logpdf.build(fields, _letterhead_images())
    name = person.get("name") or ""
    history.record("letter", service, {"LOG letter": [None, name]})
    audit(request, "service.log", id=service.id, vessel=vessel.id, crew=name)
    response = HttpResponse(pdf, content_type="application/pdf")
    file_name = " ".join(part for part in ("LOG", _file_name_part(vessel.name), _file_name_part(name)) if part)
    response["Content-Disposition"] = f'attachment; filename="{file_name}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@json_api
@require_http_methods(["GET", "POST"])
def service_receipt(request, pk):
    """The master receipt of a service: GET the pre-filled text, POST the edited text to get the PDF (no stamp).
    Nothing typed is stored; making one is recorded in the History."""
    require_edit(request.profile)
    allowed = scoped_vessels(request.profile, prefetch=False)
    service = get_object_or_404(Service.objects.filter(vessel__in=allowed).select_related("vessel"), pk=pk)
    if request.method == "GET":
        return JsonResponse({"receipt": receipt.prefill(service)})
    ratelimit.check(request, "export")
    fields = clean_receipt(read_json(request))
    pdf = logpdf.build_receipt(fields, _letterhead_images())
    vessel = service.vessel
    history.record("receipt", service, {"Master receipt": [None, service.service_type]})
    audit(request, "service.receipt", id=service.id, vessel=vessel.id)
    response = HttpResponse(pdf, content_type="application/pdf")
    file_name = " ".join(part for part in ("Receipt", _file_name_part(vessel.name),
                                           timezone.localdate().isoformat()) if part)
    response["Content-Disposition"] = f'attachment; filename="{file_name}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


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


# ---- Garbage & Sludge: monthly prices per port, quantities per vessel (see disposal.py) ---------


def _disposal_prices_json(profile):
    return JsonResponse({"prices": disposal.prices_for(profile)})


@json_api
@require_http_methods(["GET", "POST"])
def disposal_prices_list(request):
    if request.method == "POST":
        require_admin(request.profile)  # money settings, like exchange rates
        month, port, fields = clean_disposal_price(read_json(request))
        DisposalPrice.objects.update_or_create(month=month, port=port, defaults=fields)
        audit(request, "disposal_price.save", month=month.isoformat(), port=port)
    return _disposal_prices_json(request.profile)


@json_api
@require_http_methods(["DELETE"])
def disposal_price_delete(request, pk):
    require_admin(request.profile)
    get_object_or_404(DisposalPrice, pk=pk).delete()
    audit(request, "disposal_price.delete", id=pk)
    return _disposal_prices_json(request.profile)


@json_api
@require_http_methods(["GET"])
def disposal_list(request):
    return JsonResponse(disposal.response(request.profile, request.GET))


@json_api
@require_http_methods(["PUT"])
def disposal_update(request, vessel_id):
    require_edit(request.profile)
    vessel = get_object_or_404(scoped_vessels(request.profile, prefetch=False), pk=vessel_id)
    accounting.require_open(VesselDisposal.objects.filter(vessel=vessel).select_for_update().first())
    changes = clean_disposal_quantities(read_json(request))
    result = disposal.save(vessel, changes)
    audit(request, "disposal.save", vessel=vessel.id, **changes)
    return JsonResponse(result)


# ---- master data (OPR / POC options) --------------------------------------------------------


def _usage_counts(profile):
    """{kind: {value: how many visible vessels (OPR / POC / Agent / Delay reason), bookings (Hotel / Airport / Port) or
    port closures (Closure reason) use it}}"""
    vessels = scoped_vessels(profile, prefetch=False)
    counts = {
        kind: {row[kind]: row["n"] for row in vessels.values(kind).annotate(n=Count("id")).order_by()}
        for kind in OPTION_KIND_KEYS
        if kind not in BOOKING_KINDS and kind not in ("agent", "delay", "closure")
    }
    # Delay reasons are used by vessels, closure reasons by port closures (fields not named after the kind).
    delays = vessels.exclude(delay_reason="").values("delay_reason").annotate(n=Count("id")).order_by()
    counts["delay"] = {row["delay_reason"]: row["n"] for row in delays}
    closures_in_scope = scoped_closures(profile).values("reason").annotate(n=Count("id")).order_by()
    counts["closure"] = {row["reason"]: row["n"] for row in closures_in_scope}
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
        + ["Delay reason", "Services", "Total Cost LE", "Total Profit LE"]
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
                _csv_safe(data["delay_reason"]),
                _csv_safe(", ".join(s["type"] for s in data["services"])),
                data["total_cost_egp"],
                data["total_profit_egp"],
            ]
        )
    audit(request, "export.csv")
    return response


# ---- port closures (see closures.py) -----------------------------------------------------------


@json_api
@require_http_methods(["GET", "POST"])
def closures_list(request):
    profile = request.profile
    if request.method == "GET":
        return JsonResponse(closures.list_response(profile, request.GET))
    require_edit(profile)
    closure = closures.save_closure(profile, read_json(request))
    audit(request, "closure.create", id=closure.id, port=closure.port)
    return JsonResponse(closures.closure_to_dict(closure, profile), status=201)


@json_api
@require_http_methods(["PUT", "DELETE"])
def closure_detail(request, pk):
    profile = request.profile
    require_edit(profile)
    closure = closures.get_closure(profile, pk)
    if request.method == "DELETE":
        closure.delete()
        audit(request, "closure.delete", id=pk)
        return JsonResponse({"ok": True})
    payload = read_json(request)
    closure = closures.save_closure(profile, payload, existing=conflicts.locked(closure, payload, request.user))
    audit(request, "closure.update", id=closure.id)
    return JsonResponse(closures.closure_to_dict(closure, profile))


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
        accounting.require_open(booking)
        booking.delete()
        audit(request, f"{_AUDIT_NAME[kind]}.delete", id=pk)
        return JsonResponse({"ok": True})
    payload = read_json(request)
    existing = conflicts.locked(booking, payload, request.user)
    accounting.require_open(existing)
    booking = logistics.save_booking(kind, profile, payload, existing=existing)
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
@require_http_methods(["POST"])
def accounting_set(request):
    """Close or reopen one Calculations row (accounting.py): read-only (accounting) and admins only."""
    require_accounting(request.profile)
    kind, pk, closed = accounting.clean_request(read_json(request))
    accounting.set_closed(request.profile, kind, pk, closed)
    audit(request, "accounting.close" if closed else "accounting.open", kind=kind, id=pk)
    return JsonResponse({"ok": True, "closed": closed})


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
    return HttpResponse(render_to_string("404.html", {"brand_logo": branding.logo_available()}), status=404)


def server_error(request):
    """handler500: errors outside json_api (pages, CSV export). Logged with a reference, shown without details."""
    ref, response = server_error_response(request, as_json=_is_api(request))
    if response is not None:
        return response
    return HttpResponse(render_to_string("500.html", {"ref": ref, "brand_logo": branding.logo_available()}), status=500)


HISTORY_PAGE_SIZES = (10, 25, 50, 100)


def _shown_changes(record):
    """The History page never shows the edit counter (conflicts.py); a booking save that only changed its guests
    is shown as such."""
    changes = {k: v for k, v in record.changes.items() if k != "version"}
    if not changes and "version" in record.changes and record.object_type in ("hotelstay", "transfer"):
        return {"guests": [None, "changed"]}
    return changes


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
            "changes": _shown_changes(r),
        }
        for r in rows.order_by("-id")[start : start + page_size]
    ]
    return JsonResponse({"records": records, "count": count, "pages": pages, "page": page})

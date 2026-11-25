"""Vessel Data: the visits list (filters, sort, pages; also the export) and saving one visit."""

import math
from decimal import Decimal

from django.http import Http404

from sheet import conflicts, ports, xlsx
from sheet.errors import BadRequest
from sheet.listing import date_param, int_param
from sheet.serializers import local_iso

from .access import scoped_visits
from .figures import figures, report_date
from .models import Visit
from .validators import clean_visit

STATUSES = ("Planned", "Working", "Completed")
TIME_FIELDS = ("eta", "ata", "etb", "etc", "atb", "atd")
STORED_SORTS = ("id", "vessel_name", "shipping_line", "eta", "ata", "atb", "atd")
FIGURE_SORTS = ("status", "waiting", "operation", "port_stay", "total_moves", "productivity")
SORTS = (*STORED_SORTS, "terminal", *FIGURE_SORTS)


def visit_to_dict(visit, profile, numbers=None):
    numbers = numbers or figures(visit)
    port = visit.terminal.port
    return {
        "id": visit.id,
        "terminal": visit.terminal_id,
        "terminal_name": visit.terminal.name,
        "port": port,
        "port_label": ports.label(port),
        "vessel_name": visit.vessel_name,
        "shipping_line": visit.shipping_line,
        "loa": float(visit.loa) if visit.loa is not None else None,
        **{field: local_iso(getattr(visit, field)) for field in TIME_FIELDS},
        "planned_berth": visit.planned_berth,
        "actual_berth": visit.actual_berth,
        "cranes": visit.cranes,
        "discharge": visit.discharge,
        "loading": visit.loading,
        **numbers,
        "report_date": report_date(visit).isoformat(),
        "version": visit.version,
        "can_edit": profile.can("operation.edit"),
        "can_delete": profile.can("operation.delete"),
    }


def _statuses(params):
    text = params.get("status") or ""
    chosen = [item.strip() for item in text.split(",") if item.strip()]
    if any(item not in STATUSES for item in chosen):
        raise BadRequest("Unknown status.")
    return set(chosen)


def _sort_value(visit, numbers, key):
    if key in FIGURE_SORTS:
        return numbers[key]
    if key == "terminal":
        return visit.terminal.name
    return getattr(visit, key)


def filtered(profile, params):
    """[(visit, figures)] the page shows: scoped, filtered, sorted (blanks last); the export uses it unpaged."""
    date_from, date_to = date_param(params, "from"), date_param(params, "to")
    if date_from and date_to and date_from > date_to:
        raise BadRequest("From must be on or before To.")
    statuses = _statuses(params)
    sort = params.get("sort") or "eta"
    if sort not in SORTS:
        raise BadRequest("Unknown sort.")
    descending = (params.get("dir") or ("desc" if sort == "eta" else "asc")) == "desc"
    queryset = scoped_visits(profile, params.get("port") or None)
    terminal = (params.get("terminal") or "").strip()
    if terminal:
        if not terminal.isdigit():
            raise BadRequest("Unknown terminal.")
        queryset = queryset.filter(terminal_id=int(terminal))
    if params.get("line"):
        queryset = queryset.filter(shipping_line=params["line"][:100])
    needle = (params.get("q") or "").strip().lower()
    rows = []
    for visit in queryset.order_by("-id"):
        if needle and needle not in visit.vessel_name.lower():
            continue
        day = report_date(visit)
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        numbers = figures(visit)
        if statuses and numbers["status"] not in statuses:
            continue
        rows.append((visit, numbers))
    known = [r for r in rows if _sort_value(*r, sort) is not None]
    blank = [r for r in rows if _sort_value(*r, sort) is None]
    known.sort(key=lambda r: _sort_value(*r, sort), reverse=descending)  # stable: ties stay newest id first
    return known + blank


def list_response(profile, params):
    rows = filtered(profile, params)
    size = int_param(params, "page_size", 50, 1, 200, "Page size must be 1 to 200.")
    pages = max(1, math.ceil(len(rows) / size))
    page = min(int_param(params, "page", 1, 1, 100000, "Unknown page."), pages)
    shown = rows[(page - 1) * size : page * size]
    lines = sorted(set(scoped_visits(profile, params.get("port") or None).values_list("shipping_line", flat=True)))
    return {"visits": [visit_to_dict(v, profile, n) for v, n in shown], "total": len(rows), "page": page,
            "pages": pages, "lines": lines}


def get_visit(profile, pk):
    try:
        return scoped_visits(profile).get(pk=pk)
    except Visit.DoesNotExist:
        raise Http404 from None


def save_visit(profile, data, existing=None):
    visit = existing or Visit()
    before = conflicts.snapshot(visit)
    for field, value in clean_visit(data, profile, existing).items():
        setattr(visit, field, value)
    if existing:
        conflicts.bump_if_changed(visit, before)
    visit.save()
    return visit


EXPORT_HEAD = ["ID", "Vessel", "Line", "Terminal", "LOA (m)", "ETA", "ATA", "Planned berth", "ETB", "ETC", "ATB",
               "Actual berth", "Cranes", "ATD", "Status", "Waiting (hrs)", "Operation (hrs)", "Discharge", "Loading",
               "Total moves", "Moves/hr", "Port stay (hrs)"]


def export_file(profile, params):
    """The filtered visits (every page of them) as a plain-table .xlsx: one header row, numbers as numbers."""
    def number(value):
        return xlsx.Number(float(value) if isinstance(value, Decimal) else value)

    rows = [EXPORT_HEAD]
    for visit, n in filtered(profile, params):
        rows.append([
            number(visit.id), visit.vessel_name, visit.shipping_line, visit.terminal.name, number(visit.loa),
            xlsx.Moment(visit.eta), xlsx.Moment(visit.ata), visit.planned_berth, xlsx.Moment(visit.etb),
            xlsx.Moment(visit.etc), xlsx.Moment(visit.atb), visit.actual_berth, number(visit.cranes),
            xlsx.Moment(visit.atd), n["status"], number(n["waiting"]), number(n["operation"]), number(visit.discharge),
            number(visit.loading), number(n["total_moves"]), number(n["productivity"]), number(n["port_stay"]),
        ])
    return xlsx.build([xlsx.Sheet("Vessel Data", rows, widths=[14] * len(EXPORT_HEAD))])

"""Berthing windows: weekly slots of a line at a terminal (Cairo time), kept on the Berthing windows page by the
people who keep terminals, read by everyone with Vessel Data; and the window nearest a visit's ETA (worked out on
read, never stored on the visit)."""

from datetime import datetime, timedelta

from django.http import Http404
from django.utils import timezone

from sheet import ports
from sheet.errors import BadRequest
from sheet.validators import _local_datetime

from .access import scoped_terminals
from .models import BerthingWindow
from .validators import clean_window, week_span


def _hhmm(value):
    return value.strftime("%H:%M")


def window_to_dict(window):
    start, end = week_span(window.start_day, window.start_time, window.end_day, window.end_time)
    port = window.terminal.port
    return {
        "id": window.id, "terminal": window.terminal_id, "terminal_name": window.terminal.name,
        "port": port, "port_label": ports.label(port), "line": window.line,
        "start_day": window.start_day, "start_time": _hhmm(window.start_time),
        "end_day": window.end_day, "end_time": _hhmm(window.end_time), "hours": round((end - start) / 60, 1),
    }


def scoped_windows(profile, port=None):
    return BerthingWindow.objects.filter(terminal__in=scoped_terminals(profile, port)).select_related("terminal")


def list_response(profile, params):
    windows = scoped_windows(profile, params.get("port") or None)
    terminal = params.get("terminal") or ""
    if terminal.isdigit():
        windows = windows.filter(terminal_id=int(terminal))
    return {"windows": [window_to_dict(w) for w in windows]}


def get_window(profile, pk):
    try:
        return scoped_windows(profile).get(pk=pk)
    except BerthingWindow.DoesNotExist:
        raise Http404 from None


def save_window(profile, data, existing=None):
    window = existing or BerthingWindow()
    for field, value in clean_window(data, profile, existing).items():
        setattr(window, field, value)
    window.save()
    return window


def _local(moment):
    return timezone.localtime(moment).strftime("%Y-%m-%dT%H:%M")


def nearest(windows, eta):
    """The occurrence of `windows` (repeated weekly) holding `eta`, else the next one to start after it (never one
    that started before it); None without windows."""
    local = timezone.localtime(eta).replace(tzinfo=None)
    monday = datetime.combine(local.date() - timedelta(days=local.weekday()), datetime.min.time())
    best = None
    for window in windows:
        start_min, end_min = week_span(window.start_day, window.start_time, window.end_day, window.end_time)
        for week in (-1, 0, 1):
            start = timezone.make_aware(monday + timedelta(weeks=week, minutes=start_min))
            end = timezone.make_aware(monday + timedelta(weeks=week, minutes=end_min))
            inside = start <= eta < end
            if not inside and start < eta:
                continue
            key = (not inside, abs((start - eta).total_seconds()))
            if best is None or key < best[0]:
                best = (key, window, start, end, inside)
    if best is None:
        return None
    _key, window, start, end, inside = best
    return {
        "window": window_to_dict(window), "start": _local(start), "end": _local(end),
        "position": "inside" if inside else "before",
        "hours": round(abs((start - eta).total_seconds()) / 3600, 1),
    }


def nearest_response(profile, params):
    terminal = params.get("terminal") or ""
    line = (params.get("line") or "").strip()
    eta = _local_datetime(params.get("eta"), "ETA")
    if not terminal.isdigit():
        raise BadRequest("Choose a terminal.")
    if not scoped_terminals(profile).filter(pk=int(terminal)).exists():
        raise Http404
    if not line or eta is None:
        return {"nearest": None}
    found = BerthingWindow.objects.filter(terminal_id=int(terminal), line=line).select_related("terminal")
    return {"nearest": nearest(list(found), eta)}

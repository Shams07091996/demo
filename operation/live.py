"""Live data (the Excel's Dashboard): one card per turned-on terminal of the person's ports, with the vessels
under operation (ATB, no ATD) and the next 7 days: not berthed (no ATB), ETA from today 00:00 Cairo to the end of
the 6th day after today, plus any vessel that has arrived (ATA) and is waiting to berth, marked `arrived`, and any
whose ETA has passed without an ATA, marked `overdue` (it stays until someone types its times).

The page's Excel (`export_file`) has one sheet per card, laid out like a terminal block of the user's workbook: the
terminal line, its picture when the server has one, Under operation and Next 7 days."""

import math
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.http import Http404
from django.utils import timezone

from sheet import xlsx
from sheet.errors import BadRequest

from . import pictures
from .access import scoped_terminals, scoped_visits
from .figures import live_rate
from .terminals import terminal_to_dict
from .visits import visit_to_dict

DAYS = 7
WORKING_HEAD = ["Vessel", "Line", "Actual berth", "ATB", "Cranes", "Discharge", "Loading", "Moves/hr"]
UPCOMING_HEAD = ["Vessel", "Line", "ETA", "LOA (m)", "Planned berth", "ETB", "ETC", "Status"]
PICTURE_WIDTH = 1000  # pixels at most, about the width of the two tables
ROW_PIXELS = 20  # Excel's default row height


def _cards(profile, port, now):
    """[(terminal, calls in 7 days, working visits, upcoming visits)] in terminal order."""
    today = timezone.localdate(now)
    week_start = timezone.make_aware(datetime.combine(today - timedelta(days=6), time.min))
    week_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    next_end = timezone.make_aware(datetime.combine(today + timedelta(days=DAYS), time.min))
    terminals = list(scoped_terminals(profile, port).filter(active=True))
    cards = {t.id: [t, 0, [], []] for t in terminals}
    for visit in scoped_visits(profile, port).filter(terminal__in=terminals).order_by("atb", "eta", "id"):
        card = cards[visit.terminal_id]
        if week_start <= visit.eta < week_end:
            card[1] += 1
        if visit.atb and not visit.atd:
            card[2].append(visit)
        elif not visit.atb and (visit.ata or visit.eta < next_end):
            card[3].append(visit)
    for card in cards.values():
        card[3].sort(key=lambda v: (v.eta, v.id))
    return list(cards.values())


def _overdue(visit, now):
    return visit.ata is None and visit.eta < now


def response(profile, port, now):
    return {"terminals": [
        {**terminal_to_dict(t), "calls_7d": calls,
         "working": [{**visit_to_dict(v, profile), "live_rate": live_rate(v, now)} for v in working],
         "upcoming": [{**visit_to_dict(v, profile), "arrived": v.ata is not None, "overdue": _overdue(v, now)}
                      for v in upcoming]}
        for t, calls, working, upcoming in _cards(profile, port, now)
    ]}


def title_line(card):
    """"ACCHCO - ALX | Berth No. 23 / 24 | Quay 500 m | Gantry Cranes: 4", leaving out a part with no value."""
    parts = [card["name"]]
    if card.get("berths"):
        parts.append("Berth No. " + " / ".join(card["berths"]))
    if card.get("quay_length"):
        parts.append(f"Quay {card['quay_length']:,} m")
    if card.get("cranes"):
        parts.append(f"Gantry Cranes: {card['cranes']}")
    return " | ".join(parts)


def _number(value):
    return xlsx.Number(float(value) if isinstance(value, Decimal) else value)


def _picture(terminal):
    found = pictures.picture(terminal)
    size = xlsx.picture_size(found[0]) if found else None
    if not size:
        return None
    width, height = size
    scale = min(1, PICTURE_WIDTH / width)
    kind = "png" if found[1] == "image/png" else "jpeg"
    return xlsx.Picture(data=found[0], kind=kind, width=round(width * scale), height=max(1, round(height * scale)),
                        anchor=(0, 2))


def _sheet(terminal, calls, working, upcoming, now):
    rows = [[xlsx.Title(title_line({"name": terminal.name, "berths": list(terminal.berths),
                                    "quay_length": terminal.quay_length, "cranes": terminal.cranes}))],
            [f"Live data · {timezone.localtime(now):%d.%m.%Y %H:%M} · Calls in 7 days: {calls}"]]
    looks = {0: "title", 1: "muted"}
    picture = _picture(terminal)
    if picture:
        rows += [[] for _ in range(math.ceil(picture.height / ROW_PIXELS) + 1)]
    else:
        rows.append([])
    tables = []

    def table(title, head, lines):
        rows.append([xlsx.Bold(title)])
        looks[len(rows)] = "header"
        rows.append(list(head))
        if not lines:
            looks[len(rows)] = "muted"
            rows.append(["No vessels"])
        for line in lines:
            looks[len(rows)] = "body"
            rows.append(line)
        tables.extend([head, *lines])
        rows.append([])

    table("Under operation", WORKING_HEAD, [
        [v.vessel_name, v.shipping_line or None, v.actual_berth or None, xlsx.Moment(v.atb), _number(v.cranes),
         _number(v.discharge), _number(v.loading), _number(live_rate(v, now))] for v in working])

    def status(v):
        if v.ata is not None:
            return xlsx.Status("Arrived", "progress")
        return xlsx.Status("Overdue", "danger") if _overdue(v, now) else None

    table("Next 7 days", UPCOMING_HEAD, [
        [v.vessel_name, v.shipping_line or None, xlsx.Moment(v.eta), _number(v.loa), v.planned_berth or None,
         xlsx.Moment(v.etb), xlsx.Moment(v.etc), status(v)] for v in upcoming])
    return xlsx.Sheet(name=terminal.code or terminal.name, rows=rows, widths=xlsx.fit_widths(tables), looks=looks,
                      pictures=[picture] if picture else [])


def export_file(profile, port, terminal, now):
    """The Live data cards (all, or the one `terminal` id) as a workbook of one sheet per terminal."""
    cards = _cards(profile, port, now)
    if terminal:
        if not terminal.isdigit():
            raise BadRequest("Choose a terminal.")
        cards = [card for card in cards if card[0].id == int(terminal)]
        if not cards:
            raise Http404
    if not cards:
        return xlsx.build([xlsx.Sheet(name="No data", rows=[[xlsx.Title("Live data")], ["No terminals"]],
                                      looks={0: "title", 1: "muted"})])
    return xlsx.build([_sheet(*card, now) for card in cards])

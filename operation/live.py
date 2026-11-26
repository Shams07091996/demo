"""Live data (the Excel's Dashboard): one card per turned-on terminal of the person's ports, with the vessels
under operation (ATB, no ATD) and the next 7 days: not berthed (no ATB), ETA from today 00:00 Cairo to the end of
the 6th day after today, plus any vessel that has arrived (ATA) and is waiting to berth, marked `arrived`, and any
whose ETA has passed without an ATA, marked `overdue` (it stays until someone types its times)."""

from datetime import datetime, time, timedelta

from django.utils import timezone

from .access import scoped_terminals, scoped_visits
from .figures import live_rate
from .terminals import terminal_to_dict
from .visits import visit_to_dict

DAYS = 7


def response(profile, port, now):
    today = timezone.localdate(now)
    week_start = timezone.make_aware(datetime.combine(today - timedelta(days=6), time.min))
    week_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    next_end = timezone.make_aware(datetime.combine(today + timedelta(days=DAYS), time.min))
    terminals = list(scoped_terminals(profile, port).filter(active=True))
    visits = scoped_visits(profile, port).filter(terminal__in=terminals)
    cards = {t.id: {**terminal_to_dict(t), "calls_7d": 0, "working": [], "upcoming": []} for t in terminals}
    for visit in visits.order_by("atb", "eta", "id"):
        card = cards[visit.terminal_id]
        if week_start <= visit.eta < week_end:
            card["calls_7d"] += 1
        if visit.atb and not visit.atd:
            card["working"].append({**visit_to_dict(visit, profile), "live_rate": live_rate(visit, now)})
        elif not visit.atb and (visit.ata or visit.eta < next_end):
            card["upcoming"].append({**visit_to_dict(visit, profile), "arrived": visit.ata is not None,
                                     "overdue": visit.ata is None and visit.eta < now})
    for card in cards.values():
        card["upcoming"].sort(key=lambda v: (v["eta"], v["id"]))
    return {"terminals": list(cards.values())}

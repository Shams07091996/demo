"""Live data (the Excel's Dashboard): one card per turned-on terminal of the person's ports, with the vessels
under operation (ATB, no ATD) and the ones due in the next 7 days (no ATB yet, ETA from now)."""

from datetime import datetime, time, timedelta

from django.utils import timezone

from .access import scoped_terminals, scoped_visits
from .figures import live_rate
from .terminals import terminal_to_dict
from .visits import visit_to_dict

WINDOW = timedelta(days=7)


def response(profile, port, now):
    today = timezone.localdate(now)
    week_start = timezone.make_aware(datetime.combine(today - timedelta(days=6), time.min))
    week_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    terminals = list(scoped_terminals(profile, port).filter(active=True))
    visits = scoped_visits(profile, port).filter(terminal__in=terminals)
    cards = {t.id: {**terminal_to_dict(t), "calls_7d": 0, "working": [], "upcoming": []} for t in terminals}
    for visit in visits.order_by("atb", "eta", "id"):
        card = cards[visit.terminal_id]
        if week_start <= visit.eta < week_end:
            card["calls_7d"] += 1
        if visit.atb and not visit.atd:
            card["working"].append({**visit_to_dict(visit, profile), "live_rate": live_rate(visit, now)})
        elif not visit.atb and now <= visit.eta < now + WINDOW:
            card["upcoming"].append(visit_to_dict(visit, profile))
    for card in cards.values():
        card["upcoming"].sort(key=lambda v: (v["eta"], v["id"]))
    return {"terminals": list(cards.values())}

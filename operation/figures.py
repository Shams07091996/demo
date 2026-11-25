"""A visit's figures, the workbook's formula columns. Worked out on read, never stored; every page and export uses
these, so they always agree. Hours and moves/hr are rounded to one decimal."""

from django.utils import timezone

MIN_LIVE_HOURS = 0.1  # Live data's moves/hr needs at least this long since ATB


def status(visit):
    if visit.atd:
        return "Completed"
    return "Working" if visit.atb else "Planned"


def hours(start, end):
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600, 1)


def total_moves(visit):
    if visit.discharge is None and visit.loading is None:
        return None
    return (visit.discharge or 0) + (visit.loading or 0)


def figures(visit):
    operation = hours(visit.atb, visit.atd)
    moves = total_moves(visit)
    return {
        "status": status(visit),
        "waiting": hours(visit.ata, visit.atb),
        "operation": operation,
        "port_stay": hours(visit.ata, visit.atd),
        "total_moves": moves,
        "productivity": round(moves / operation, 1) if moves is not None and operation else None,
    }


def live_rate(visit, now):
    """Live data only: moves typed so far ÷ hours since ATB, for a vessel still being worked."""
    moves = total_moves(visit)
    if visit.atb is None or visit.atd is not None or not moves:
        return None
    elapsed = (now - visit.atb).total_seconds() / 3600
    return round(moves / elapsed, 1) if elapsed >= MIN_LIVE_HOURS else None


def report_date(visit):
    """The Cairo date the reports file a visit under: ATA, else ETA."""
    return timezone.localdate(visit.ata or visit.eta)


def average(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None

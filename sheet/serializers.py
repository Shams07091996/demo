"""Turn model instances into the JSON the front end expects."""

from django.utils import timezone

from .constants import PORT_LABELS, TIME_KEYS
from .finance import compute
from .models import ExchangeRate


def local_iso(moment):
    """Cairo local time as 'YYYY-MM-DDTHH:MM' (what <input type=datetime-local> uses), or None."""
    return timezone.localtime(moment).strftime("%Y-%m-%dT%H:%M") if moment else None


def _hours(start, end):
    return round((end - start).total_seconds() / 3600, 2) if start and end else None


def vessel_status(vessel):
    """Where the vessel is in its port call, from the latest milestone filled in."""
    if vessel.sailing_at:
        return "sailed"
    if vessel.ops_end_at:
        return "ops_finished"
    if vessel.ops_start_at:
        return "operating"
    if vessel.berthing_at:
        return "berthed"
    if vessel.arrival_at:
        return "arrived"
    return "scheduled"


def month_rates():
    """{(year, month): USD->EGP rate}."""
    return {(r.month.year, r.month.month): r.rate for r in ExchangeRate.objects.all()}


def service_to_dict(service, month_rate):
    return {
        "id": service.id,
        "type": service.service_type,
        "agent": service.agent,
        "data": service.data,
        "calc": compute(service.service_type, service.data, month_rate),
    }


def vessel_to_dict(vessel, rates):
    rate = rates.get((vessel.date.year, vessel.date.month))
    services = [service_to_dict(s, rate) for s in vessel.services.all()]
    return {
        "id": vessel.id,
        "name": vessel.name,
        "opr": vessel.opr,
        "poc": vessel.poc,
        "arrival_agent": vessel.arrival_agent,
        "sailing_agent": vessel.sailing_agent,
        "port": vessel.port,
        "port_label": PORT_LABELS.get(vessel.port, vessel.port),
        "date": vessel.date.isoformat(),
        "summary": vessel.summary or {},
        **{key: local_iso(getattr(vessel, key)) for key in TIME_KEYS},
        "status": vessel_status(vessel),
        "durations": {
            "ops_hours": _hours(vessel.ops_start_at, vessel.ops_end_at),
            "berth_hours": _hours(vessel.berthing_at, vessel.sailing_at),
            "port_hours": _hours(vessel.arrival_at, vessel.sailing_at),
        },
        "rate": float(rate) if rate else None,
        "services": services,
        "total_cost_egp": round(sum(s["calc"]["cost_egp"] for s in services), 2),
        "total_profit_egp": round(sum(s["calc"]["profit_egp"] for s in services), 2),
    }


def rate_to_dict(rate):
    return {
        "id": rate.id,
        "month": rate.month.strftime("%Y-%m"),
        "label": rate.month.strftime("%m.%Y"),
        "rate": float(rate.rate),
    }


def option_to_dict(option, profile, used=0):
    """`used` = how many vessels (that this user can see) currently carry this value."""
    editable = profile.is_admin or (profile.port is not None and option.port == profile.port)
    return {
        "id": option.id,
        "kind": option.kind,
        "value": option.value,
        "port": option.port,
        "editable": editable,
        "used": used,
    }

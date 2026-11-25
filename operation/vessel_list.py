"""The vessel list (name + fixed LOA, all ports): read by everyone with Vessel Data (the visit dialog fills the LOA
from it), kept by people with "Edit terminals and vessel list", entries deleted by Admins only."""

from django.http import Http404

from .models import ListedVessel
from .validators import clean_listed_vessel

MAX_LISTED = 1000


def listed_to_dict(vessel):
    return {"id": vessel.id, "name": vessel.name, "loa": float(vessel.loa)}


def list_response(params):
    queryset = ListedVessel.objects.all()
    q = (params.get("q") or "").strip()[:100]
    if q:
        queryset = queryset.filter(name__icontains=q)
    return {"vessels": [listed_to_dict(v) for v in queryset[:MAX_LISTED]]}


def get_listed(pk):
    try:
        return ListedVessel.objects.get(pk=pk)
    except ListedVessel.DoesNotExist:
        raise Http404 from None


def save_listed(data, existing=None):
    vessel = existing or ListedVessel()
    for field, value in clean_listed_vessel(data, existing).items():
        setattr(vessel, field, value)
    vessel.save()
    return vessel

"""The Operation API. Every view is wrapped in sheet's json_api (sign-in, two-step, rate limit, one transaction per
write, JSON errors) and reads through operation.access (a User only their ports)."""

from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from sheet import conflicts, ratelimit
from sheet.access import require, require_admin, require_page
from sheet.api import audit, json_api, read_json
from sheet.errors import Forbidden
from sheet.views import _xlsx_response

from . import analysis, live, pictures, terminals, vessel_list, visits
from .access import require_master, require_reader


@json_api
@require_http_methods(["GET", "POST"])
def terminals_list(request):
    profile = request.profile
    require_reader(profile)
    if request.method == "GET":
        return JsonResponse(terminals.list_response(profile, request.GET))
    require_master(profile)
    terminal = terminals.save_terminal(profile, read_json(request))
    audit(request, "terminal.create", id=terminal.id, port=terminal.port)
    return JsonResponse(terminals.terminal_to_dict(terminal), status=201)


@json_api
@require_http_methods(["PUT"])
def terminal_detail(request, pk):
    profile = request.profile
    require_master(profile)
    terminal = terminals.save_terminal(profile, read_json(request), existing=terminals.get_terminal(profile, pk))
    audit(request, "terminal.update", id=terminal.id, port=terminal.port)
    return JsonResponse(terminals.terminal_to_dict(terminal))


@json_api
@require_http_methods(["GET"])
def terminal_picture(request, pk):
    """A terminal's picture from the server's folder (pictures.py), for people who see that terminal."""
    profile = request.profile
    require_reader(profile)
    found = pictures.picture(terminals.get_terminal(profile, pk))
    if found is None:
        raise Http404
    data, kind = found
    response = HttpResponse(data, content_type=kind)
    response["Cache-Control"] = "private, max-age=300"
    return response


@json_api
@require_http_methods(["GET", "POST"])
def listed_vessels(request):
    profile = request.profile
    require_page(profile, "op_vessels")
    if request.method == "GET":
        return JsonResponse(vessel_list.list_response(request.GET))
    require_master(profile)
    vessel = vessel_list.save_listed(read_json(request))
    audit(request, "listed_vessel.create", id=vessel.id)
    return JsonResponse(vessel_list.listed_to_dict(vessel), status=201)


@json_api
@require_http_methods(["PUT", "DELETE"])
def listed_vessel_detail(request, pk):
    profile = request.profile
    require_page(profile, "op_vessels")
    if request.method == "DELETE":
        require_admin(profile)
        vessel_list.get_listed(pk).delete()
        audit(request, "listed_vessel.delete", id=pk)
        return JsonResponse({"ok": True})
    require_master(profile)
    vessel = vessel_list.save_listed(read_json(request), existing=vessel_list.get_listed(pk))
    audit(request, "listed_vessel.update", id=vessel.id)
    return JsonResponse(vessel_list.listed_to_dict(vessel))


@json_api
@require_http_methods(["GET", "POST"])
def visits_list(request):
    profile = request.profile
    require_page(profile, "op_vessels")
    if request.method == "GET":
        return JsonResponse(visits.list_response(profile, request.GET))
    require(profile, "operation.edit")
    visit = visits.save_visit(profile, read_json(request))
    audit(request, "visit.create", id=visit.id, port=visit.terminal.port)
    return JsonResponse(visits.visit_to_dict(visit, profile), status=201)


@json_api
@require_http_methods(["PUT", "DELETE"])
def visit_detail(request, pk):
    profile = request.profile
    require_page(profile, "op_vessels")
    if request.method == "DELETE":
        require(profile, "operation.delete")
        visit = visits.get_visit(profile, pk)
        visit.delete()
        audit(request, "visit.delete", id=pk)
        return JsonResponse({"ok": True})
    require(profile, "operation.edit")
    visit = visits.get_visit(profile, pk)
    payload = read_json(request)
    visit = visits.save_visit(profile, payload, existing=conflicts.locked(visit, payload, request.user))
    audit(request, "visit.update", id=visit.id)
    return JsonResponse(visits.visit_to_dict(visit, profile))


@json_api
@require_http_methods(["GET"])
def live_view(request):
    profile = request.profile
    require_page(profile, "op_live")
    return JsonResponse(live.response(profile, request.GET.get("port") or None, timezone.now()))


@json_api
@require_http_methods(["GET"])
def analysis_view(request):
    """Analysis reports and Report charts share this response."""
    profile = request.profile
    if not (profile.sees("op_analysis") or profile.sees("op_charts")):
        raise Forbidden("You don't have access to this page.")
    return JsonResponse(analysis.response(profile, request.GET))


@json_api
@require_http_methods(["GET"])
def visits_export(request):
    """The Vessel Data page's rows (its own list query, every page of it) as a plain-table .xlsx."""
    profile = request.profile
    require_page(profile, "op_vessels")
    require(profile, "exports")
    ratelimit.check(request, "export")
    content = visits.export_file(profile, request.GET)
    # Which filters were used, not their values (a search can be a name).
    audit(request, "operation.export", filters=",".join(sorted(request.GET))[:200])
    return _xlsx_response(content, f"Vessel Data {timezone.localdate().isoformat()}.xlsx")

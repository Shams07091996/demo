"""The Operation API. Every view is wrapped in sheet's json_api (sign-in, two-step, rate limit, one transaction per
write, JSON errors) and reads through operation.access (a User only their ports)."""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from sheet.access import require_admin
from sheet.api import audit, json_api, read_json

from . import terminals
from .access import require_reader


@json_api
@require_http_methods(["GET", "POST"])
def terminals_list(request):
    profile = request.profile
    require_reader(profile)
    if request.method == "GET":
        return JsonResponse(terminals.list_response(profile, request.GET))
    require_admin(profile)
    terminal = terminals.save_terminal(profile, read_json(request))
    audit(request, "terminal.create", id=terminal.id, port=terminal.port)
    return JsonResponse(terminals.terminal_to_dict(terminal), status=201)


@json_api
@require_http_methods(["PUT"])
def terminal_detail(request, pk):
    profile = request.profile
    require_admin(profile)
    terminal = terminals.save_terminal(profile, read_json(request), existing=terminals.get_terminal(profile, pk))
    audit(request, "terminal.update", id=terminal.id, port=terminal.port)
    return JsonResponse(terminals.terminal_to_dict(terminal))

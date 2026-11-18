"""The pages of the two-step login: enter code, set up Authenticator, setup window over, forget this computer.
`TwoStepMiddleware` only lets a person reach the page of the step they are on (sheet/twostep.py)."""

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import alerts, throttle, twostep
from .access import profile_of
from .netutils import client_ip

security_log = logging.getLogger("sheet.security")


def _locked(request):
    if throttle.is_blocked(client_ip(request), request.user.get_username()):
        security_log.warning("two-step locked user=%s ip=%s", request.user.get_username(), client_ip(request))
        alerts.note("login_lockout")
        return render(request, "sheet/locked.html", status=429)
    return None


@login_required
def code(request):
    device = twostep.confirmed_device(request.user)
    if device is None or twostep.has_passed(request):
        return redirect("index")
    error = ""
    remember = True
    if request.method == "POST":
        locked = _locked(request)
        if locked:
            return locked
        remember = request.POST.get("remember") == "on"
        if twostep.check_code(request, device, request.POST.get("code")):
            twostep.mark_passed(request, "code", device.pk)
            response = redirect("index")
            if remember:
                twostep.remember(request, response)
            return response
        error = "Wrong code. Try the newest code in Authenticator."
    return render(request, "sheet/two_step_code.html", {"error": error, "remember": remember})


@login_required
def setup(request):
    profile = profile_of(request.user)
    if twostep.confirmed_device(request.user) is not None or twostep.has_passed(request):
        return redirect("index")
    if not twostep.setup_open(profile):
        return redirect("two_step_blocked")
    device = twostep.new_device(request.user)
    error = ""
    if request.method == "POST":
        locked = _locked(request)
        if locked:
            return locked
        if twostep.check_code(request, device, request.POST.get("code")):
            device.confirmed = True
            device.save()
            security_log.info("two-step setup done user=%s ip=%s", request.user.get_username(), client_ip(request))
            twostep.mark_passed(request, "code", device.pk)
            return redirect("index")
        error = "Wrong code. Scan the QR code again and type the newest code."
    context = {"error": error, "qr": twostep.qr_data_url(device), "secret": twostep.secret_text(device)}
    return render(request, "sheet/two_step_setup.html", context)


@login_required
def blocked(request):
    return render(request, "sheet/two_step_blocked.html")


@require_POST
@login_required
def forget(request):
    response = redirect("index")
    twostep.forget(request, response)
    return response

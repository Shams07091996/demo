"""Change history (A09, A08): every create / update / delete of a tracked model becomes one ChangeRecord.

Model signals catch every path (API views, the Django admin, cascaded deletes, management commands); bulk_create sends
no signals, so its callers use `record_created`. The current request travels in a context variable set by
`HistoryMiddleware`; without one (management commands, shell) the change is recorded as "system". The record is
written in the same transaction as the change (json_api wraps writes in one), so if it fails the change fails too."""

import json
from contextvars import ContextVar

from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import post_save, pre_delete, pre_save
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import (
    ChangeRecord,
    Customer,
    CustomerContact,
    CustomerRate,
    DisposalPrice,
    ExchangeRate,
    Guest,
    HotelStay,
    Option,
    PortClosure,
    Profile,
    RememberedComputer,
    Service,
    Ship,
    Transfer,
    Vessel,
    VesselDisposal,
)
from .netutils import client_ip

TRACKED = (
    Vessel,
    Service,
    HotelStay,
    Transfer,
    Guest,
    Option,
    ExchangeRate,
    DisposalPrice,
    VesselDisposal,
    PortClosure,
    Ship,
    Customer,
    CustomerContact,
    CustomerRate,
    Profile,
    User,
    TOTPDevice,
    RememberedComputer,
)
# last_login changes on every sign-in (not a change to record); date_joined never changes.
SKIPPED_FIELDS = {"id", "created_at", "last_login", "date_joined"}
# Secrets never go into the history (the Authenticator key, the remembered-computer token hash), nor fields that
# change on every sign-in or wrong code (so a wrong code writes no record).
SECRET_FIELDS = {
    TOTPDevice: {
        "key",
        "drift",
        "last_t",
        "throttling_failure_count",
        "throttling_failure_timestamp",
        "last_used_at",
    },
    RememberedComputer: {"token_hash", "last_used_at"},
}
HIDDEN = "(changed)"  # the password hash is never copied into the history, only the fact that it changed

_request = ContextVar("history_request", default=None)


class HistoryMiddleware:
    """Make the current request (who, from where) available to the history signals."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request.set(request)
        try:
            return self.get_response(request)
        finally:
            _request.reset(token)


def current_request():
    """The request being served, or None (management commands, shell)."""
    return _request.get()


def _values(instance):
    skipped = SKIPPED_FIELDS | SECRET_FIELDS.get(type(instance), set())
    fields = instance._meta.concrete_fields
    values = {f.attname: getattr(instance, f.attname) for f in fields if f.attname not in skipped}
    if isinstance(instance, User):
        values.pop("password")
    return values


def _password_changed(instance, old_hash):
    return isinstance(instance, User) and old_hash is not None and old_hash != instance.password


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _vessel_port(vessel_id):
    if vessel_id is None:
        return ""
    return Vessel._base_manager.filter(pk=vessel_id).values_list("port", flat=True).first() or ""


def port_of(instance):
    if isinstance(instance, (Vessel, Option)):
        return instance.port or ""
    if isinstance(instance, (Service, HotelStay, Transfer)):
        return _vessel_port(instance.vessel_id)
    if isinstance(instance, Guest):
        if instance.stay_id:
            booking_model, booking_id = HotelStay, instance.stay_id
        else:
            booking_model, booking_id = Transfer, instance.transfer_id
        vessel_id = booking_model._base_manager.filter(pk=booking_id).values_list("vessel_id", flat=True).first()
        return _vessel_port(vessel_id)
    if isinstance(instance, Profile):
        return instance.port or ""
    return ""


def _who():
    request = _request.get()
    if request is None:
        return None, "system", ""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user, user.get_username(), client_ip(request)
    return None, "anonymous", client_ip(request)


def record(action, instance, changes):
    user, username, ip = _who()
    ChangeRecord.objects.create(
        user=user,
        username=username,
        ip=ip,
        action=action,
        object_type=instance._meta.model_name,
        object_id=instance.pk,
        port=port_of(instance),
        changes=_json_safe(changes),
    )


def record_created(instances):
    """For bulk_create, which sends no signals."""
    for instance in instances:
        record("create", instance, {k: [None, v] for k, v in _values(instance).items()})


def _before_save(sender, instance, raw=False, **kwargs):
    instance._history_old = None
    if not raw and instance.pk is not None:
        old = sender._base_manager.filter(pk=instance.pk).first()
        instance._history_old = _values(old) if old is not None else None
        instance._history_old_password = old.password if isinstance(old, User) else None


def _after_save(sender, instance, created, raw=False, **kwargs):
    if raw:  # loaddata: the data is being restored, not changed
        return
    new = _values(instance)
    old = getattr(instance, "_history_old", None)
    if created or old is None:
        record("create", instance, {k: [None, v] for k, v in new.items()})
        return
    changes = {k: [old.get(k), v] for k, v in new.items() if old.get(k) != v}
    if _password_changed(instance, getattr(instance, "_history_old_password", None)):
        changes["password"] = [HIDDEN, HIDDEN]
    if changes:
        record("update", instance, changes)


def _before_delete(sender, instance, **kwargs):
    record("delete", instance, {k: [v, None] for k, v in _values(instance).items()})


def connect():
    for model in TRACKED:
        uid = f"history-{model._meta.label}"
        pre_save.connect(_before_save, sender=model, dispatch_uid=f"{uid}-pre-save")
        post_save.connect(_after_save, sender=model, dispatch_uid=f"{uid}-post-save")
        pre_delete.connect(_before_delete, sender=model, dispatch_uid=f"{uid}-pre-delete")

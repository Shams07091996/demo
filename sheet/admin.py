from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import twostep
from .models import (
    EXEMPT_REFUSED,
    ChangeRecord,
    DisposalPrice,
    ExchangeRate,
    Guest,
    HotelStay,
    Option,
    PortClosure,
    Profile,
    RememberedComputer,
    Service,
    Transfer,
    Vessel,
    VesselDisposal,
)

TWO_STEP_FIELDS = ("two_step_exempt", "must_change_password")


class VersionedAdmin(admin.ModelAdmin):
    """A save here that changes something raises the record's edit-conflict version (conflicts.py), so a dialog
    opened before it warns instead of overwriting; a changed service inline raises that service's, a changed guest
    list the booking's (once per save). The version itself can't be edited here."""

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), "version")

    def save_model(self, request, obj, form, change):
        if change and form.has_changed():
            obj.version += 1
            obj._version_bumped = True
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model is Service:
            for inline_form in formset.forms:
                if inline_form.instance.pk and inline_form.has_changed():
                    inline_form.instance.version += 1
        super().save_formset(request, form, formset, change)
        booking = form.instance
        guests_changed = formset.new_objects or formset.changed_objects or formset.deleted_objects
        if formset.model is Guest and change and guests_changed and not getattr(booking, "_version_bumped", False):
            booking.version += 1
            booking._version_bumped = True
            booking.save(update_fields=["version"])


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 0
    readonly_fields = ("version",)


@admin.register(Vessel)
class VesselAdmin(VersionedAdmin):
    list_display = ("name", "opr", "poc", "port", "date")
    list_filter = ("port", "opr")
    search_fields = ("name", "opr", "poc")
    inlines = [ServiceInline]


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False

    def get_readonly_fields(self, request, obj=None):
        """The setup window is opened by a reset only; the two-step settings are for superusers only."""
        if request.user.is_superuser:
            return ("setup_until",)
        return ("setup_until", *TWO_STEP_FIELDS)


class UserForm(UserChangeForm):
    def clean(self):
        data = super().clean()
        exempt = Profile.objects.filter(user=self.instance, two_step_exempt=True).exists()
        if exempt and (data.get("is_staff") or data.get("is_superuser")):
            raise ValidationError(EXEMPT_REFUSED)
        return data


@admin.action(description="Reset two-step login (lost phone)")
def reset_two_step(modeladmin, request, queryset):
    if not request.user.is_superuser:
        return
    for user in queryset:
        twostep.reset(user)
    modeladmin.message_user(request, f"Two-step login reset for {len(queryset)} person(s).", messages.SUCCESS)


class UserWithProfile(UserAdmin):
    form = UserForm
    inlines = [ProfileInline]
    actions = [reset_two_step]

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("reset_two_step", None)
        return actions


admin.site.unregister(TOTPDevice)  # django-otp's own page shows the secret and a QR code


@admin.register(TOTPDevice)
class AuthenticatorAdmin(admin.ModelAdmin):
    """Read-only, and never the secret: an Authenticator is set up by its owner and removed by a reset."""

    list_display = ("user", "name", "confirmed", "created_at", "last_used_at")
    list_filter = ("confirmed",)
    search_fields = ("user__username",)
    fields = ("user", "name", "confirmed", "created_at", "last_used_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    # Removing an Authenticator here is the same as the Reset action: remembered computers go too, a new window opens.
    def delete_model(self, request, obj):
        twostep.reset(obj.user)

    def delete_queryset(self, request, queryset):
        for user in {device.user for device in queryset}:
            twostep.reset(user)


@admin.register(RememberedComputer)
class RememberedComputerAdmin(admin.ModelAdmin):
    """Remembered computers can be looked at and removed (a stolen laptop), never added or changed."""

    list_display = ("user", "agent", "ip", "created_at", "expires_at", "last_used_at")
    search_fields = ("user__username",)
    fields = ("user", "agent", "ip", "created_at", "expires_at", "last_used_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


admin.site.unregister(User)
admin.site.register(User, UserWithProfile)
admin.site.register(ExchangeRate)
admin.site.register(DisposalPrice)
admin.site.register(VesselDisposal)
admin.site.register(Option)


class StayGuestInline(admin.TabularInline):
    model = Guest
    fk_name = "stay"
    exclude = ("transfer",)
    extra = 0


class TransferGuestInline(admin.TabularInline):
    model = Guest
    fk_name = "transfer"
    exclude = ("stay",)
    extra = 0


@admin.register(HotelStay)
class HotelStayAdmin(VersionedAdmin):
    list_display = ("hotel", "check_in", "nights", "vessel")
    inlines = [StayGuestInline]


@admin.register(Transfer)
class TransferAdmin(VersionedAdmin):
    list_display = ("at", "from_place", "to_place", "hotel", "vessel")
    inlines = [TransferGuestInline]


@admin.register(PortClosure)
class PortClosureAdmin(VersionedAdmin):
    list_display = ("port", "start_at", "end_at", "reason")
    list_filter = ("port",)


@admin.register(ChangeRecord)
class ChangeRecordAdmin(admin.ModelAdmin):
    """Read-only: the history can be looked at, never added to, changed or deleted by hand."""

    list_display = ("at", "username", "action", "object_type", "object_id", "port", "ip")
    list_filter = ("action", "object_type", "port")
    search_fields = ("username", "object_type")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

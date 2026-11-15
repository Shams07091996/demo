from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import ExchangeRate, Guest, HotelStay, Option, Profile, Service, Transfer, Vessel


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 0


@admin.register(Vessel)
class VesselAdmin(admin.ModelAdmin):
    list_display = ("name", "opr", "poc", "port", "date")
    list_filter = ("port", "opr")
    search_fields = ("name", "opr", "poc")
    inlines = [ServiceInline]


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class UserWithProfile(UserAdmin):
    inlines = [ProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserWithProfile)
admin.site.register(ExchangeRate)
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
class HotelStayAdmin(admin.ModelAdmin):
    list_display = ("hotel", "check_in", "nights", "vessel")
    inlines = [StayGuestInline]


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ("at", "from_place", "to_place", "hotel", "vessel")
    inlines = [TransferGuestInline]

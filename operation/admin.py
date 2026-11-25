"""Read-only views in the Django admin; terminals and visits are changed only through the app's pages."""

from django.contrib import admin

from .models import Terminal, Visit


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Terminal)
class TerminalAdmin(ReadOnlyAdmin):
    list_display = ("name", "code", "port", "quay_length", "cranes", "active")


@admin.register(Visit)
class VisitAdmin(ReadOnlyAdmin):
    list_display = ("id", "vessel_name", "shipping_line", "terminal", "eta", "atb", "atd")

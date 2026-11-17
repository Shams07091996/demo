from django.conf import settings
from django.contrib import admin
from django.urls import include, path

handler400 = "sheet.views.bad_request"
handler403 = "sheet.views.forbidden"
handler404 = "sheet.views.not_found"
handler500 = "sheet.views.server_error"

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("", include("sheet.urls")),
]

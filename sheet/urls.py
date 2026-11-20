from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views, views_twostep

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="sheet/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("login/code/", views_twostep.code, name="two_step_code"),
    path("login/setup/", views_twostep.setup, name="two_step_setup"),
    path("login/blocked/", views_twostep.blocked, name="two_step_blocked"),
    path("login/forget/", views_twostep.forget, name="two_step_forget"),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(
            form_class=views_twostep.NewPasswordForm,
            template_name="sheet/password_change.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "password/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="sheet/password_change_done.html"),
        name="password_change_done",
    ),
    path("", views.index, name="index"),
    path("export.csv", views.export_csv, name="export_csv"),
    path("api/vessels/", views.vessels, name="api_vessels"),
    path("api/vessels/alerts/", views.vessel_alerts, name="api_vessel_alerts"),
    path("api/dashboard/", views.dashboard, name="api_dashboard"),
    path("api/dashboard/jobs/", views.dashboard_jobs, name="api_dashboard_jobs"),
    path("api/vessels/<int:pk>/", views.vessel_detail, name="api_vessel"),
    path("api/vessels/<int:pk>/services/", views.service_create, name="api_service_create"),
    path("api/vessels/<int:pk>/crew/", views.vessel_crew, name="api_vessel_crew"),
    path("api/services/<int:pk>/", views.service_detail, name="api_service"),
    path("api/services/<int:pk>/log/<str:uid>/", views.service_log, name="api_service_log"),
    path("api/options/", views.options, name="api_options"),
    path("api/options/<int:pk>/", views.option_detail, name="api_option"),
    path("api/rates/", views.rates, name="api_rates"),
    path("api/rates/<int:pk>/", views.rate_delete, name="api_rate_delete"),
    path("api/disposal-prices/", views.disposal_prices_list, name="api_disposal_prices"),
    path("api/disposal-prices/<int:pk>/", views.disposal_price_delete, name="api_disposal_price_delete"),
    path("api/disposal/", views.disposal_list, name="api_disposal"),
    path("api/disposal/<int:vessel_id>/", views.disposal_update, name="api_disposal_update"),
    path("api/calculations/", views.calculations_list, name="api_calculations"),
    path("api/history/", views.history_list, name="api_history"),
    path("api/closures/", views.closures_list, name="api_closures"),
    path("api/closures/<int:pk>/", views.closure_detail, name="api_closure"),
    path("api/hotels/", views.bookings, {"kind": "hotels"}, name="api_hotels"),
    path("api/hotels/<int:pk>/", views.booking_detail, {"kind": "hotels"}, name="api_hotel"),
    path("api/transfers/", views.bookings, {"kind": "transfers"}, name="api_transfers"),
    path("api/transfers/<int:pk>/", views.booking_detail, {"kind": "transfers"}, name="api_transfer"),
]

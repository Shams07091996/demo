from django.urls import path

from . import views

urlpatterns = [
    path("api/operation/terminals/", views.terminals_list, name="api_op_terminals"),
    path("api/operation/terminals/<int:pk>/", views.terminal_detail, name="api_op_terminal"),
    path("api/operation/vessels/", views.listed_vessels, name="api_op_listed"),
    path("api/operation/vessels/<int:pk>/", views.listed_vessel_detail, name="api_op_listed_one"),
    path("api/operation/visits/", views.visits_list, name="api_op_visits"),
    path("api/operation/visits/export/", views.visits_export, name="api_op_visits_export"),
    path("api/operation/visits/<int:pk>/", views.visit_detail, name="api_op_visit"),
    path("api/operation/live/", views.live_view, name="api_op_live"),
    path("api/operation/analysis/", views.analysis_view, name="api_op_analysis"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("api/operation/terminals/", views.terminals_list, name="api_op_terminals"),
    path("api/operation/terminals/<int:pk>/", views.terminal_detail, name="api_op_terminal"),
    path("api/operation/visits/", views.visits_list, name="api_op_visits"),
    path("api/operation/visits/<int:pk>/", views.visit_detail, name="api_op_visit"),
]

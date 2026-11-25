from django.urls import path

from . import views

urlpatterns = [
    path("api/operation/terminals/", views.terminals_list, name="api_op_terminals"),
    path("api/operation/terminals/<int:pk>/", views.terminal_detail, name="api_op_terminal"),
]

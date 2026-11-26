from django.apps import AppConfig


class OperationConfig(AppConfig):
    """Port berthing: every vessel calling at every terminal (separate from the Vessels page's own vessels)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "operation"

    def ready(self):
        from sheet import history

        from .models import BerthingWindow, ListedVessel, Terminal, Visit

        history.track(Terminal, Visit, ListedVessel, BerthingWindow)

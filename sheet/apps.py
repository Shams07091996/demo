from django.apps import AppConfig


class SheetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sheet"

    def ready(self):
        from . import history, signals  # noqa: F401  (signals registers the login signal handlers)

        history.connect()

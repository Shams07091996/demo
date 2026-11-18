from django.apps import AppConfig


class SheetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sheet"

    def ready(self):
        from . import checks, history, signals, twostep  # noqa: F401  (checks / signals register themselves on import)

        history.connect()

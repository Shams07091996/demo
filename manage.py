#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

DEV_ONLY_COMMANDS = ("runserver", "test")


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Debug mode is off unless DJANGO_DEBUG=1 is set. The development server and the test runner are never
    # production, so they default it on; every other command (migrate, seed_demo...) and the WSGI/ASGI server
    # need it set explicitly.
    if len(sys.argv) > 1 and sys.argv[1] in DEV_ONLY_COMMANDS:
        os.environ.setdefault("DJANGO_DEBUG", "1")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

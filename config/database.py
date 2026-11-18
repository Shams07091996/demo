
"""Database settings, built from environment variables.

PostgreSQL is used in production.
SQLite is only for development and quick tests.
"""

from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def build_database_settings(environ, *, debug, base_dir):
    database_url = environ.get("DATABASE_URL", "").strip()

    if database_url:
        parsed = urlparse(database_url)

        if parsed.scheme not in ("postgres", "postgresql"):
            raise ImproperlyConfigured(
                "DATABASE_URL must be a PostgreSQL connection URL."
            )

        if not parsed.hostname or not parsed.path.strip("/"):
            raise ImproperlyConfigured(
                "DATABASE_URL is missing its database host or name."
            )

        options = {
            "sslmode": environ.get("DJANGO_DB_SSLMODE", "require")
        }

        if environ.get("DJANGO_DB_SSLROOTCERT"):
            options["sslrootcert"] = environ["DJANGO_DB_SSLROOTCERT"]

        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname,
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": options,
        }

    name = environ.get("DJANGO_DB_NAME", "").strip()

    if not name:
        if not debug and environ.get("DJANGO_ALLOW_SQLITE", "0") != "1":
            raise ImproperlyConfigured(
                "Production needs PostgreSQL: set DATABASE_URL or "
                "DJANGO_DB_NAME (and DJANGO_DB_USER / "
                "DJANGO_DB_PASSWORD / DJANGO_DB_HOST)."
            )

        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": environ.get(
                "DJANGO_DB_PATH",
                base_dir / "db.sqlite3"
            ),
        }

    options = {
        "sslmode": environ.get("DJANGO_DB_SSLMODE", "require")
    }

    if environ.get("DJANGO_DB_SSLROOTCERT"):
        options["sslrootcert"] = environ["DJANGO_DB_SSLROOTCERT"]

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": environ.get("DJANGO_DB_USER", ""),
        "PASSWORD": environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": environ.get("DJANGO_DB_HOST", "localhost"),
        "PORT": environ.get("DJANGO_DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }

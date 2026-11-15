"""Database settings, built from environment variables.

PostgreSQL is used when DJANGO_DB_NAME is set. SQLite is only for development and quick tests.
"""

from django.core.exceptions import ImproperlyConfigured


def build_database_settings(environ, *, debug, base_dir):
    name = environ.get("DJANGO_DB_NAME", "").strip()
    if not name:
        if not debug and environ.get("DJANGO_ALLOW_SQLITE", "0") != "1":
            raise ImproperlyConfigured(
                "Production needs PostgreSQL: set DJANGO_DB_NAME (and DJANGO_DB_USER / DJANGO_DB_PASSWORD / "
                "DJANGO_DB_HOST). SQLite is for development only."
            )
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": environ.get("DJANGO_DB_PATH", base_dir / "db.sqlite3")}

    # Encrypt the connection to the database. "require" encrypts; "verify-full" also checks the server's identity.
    options = {"sslmode": environ.get("DJANGO_DB_SSLMODE", "require")}
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

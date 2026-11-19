"""Django settings. Everything environment-specific comes from environment variables.

Debug mode is OFF unless DJANGO_DEBUG=1 is set, so a server whose environment was forgotten fails closed
(it refuses to start without a secret key and PostgreSQL) instead of running in debug mode.
`manage.py runserver` and `manage.py test` switch it on by themselves (see manage.py).
Production:  set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS and the database variables (see README.md).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .database import build_database_settings

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.")
    SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"  # noqa: S105  debug only; production refuses to start without DJANGO_SECRET_KEY

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django_otp",  # two-step login: the Authenticator device and the code check (sheet/twostep.py)
    "django_otp.plugins.otp_totp",
    "sheet",  # before staticfiles, so sheet's runserver (no-cache static files) is the one used
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "sheet.middleware.LoginThrottleMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "sheet.history.HistoryMiddleware",
    "sheet.middleware.TwoStepMiddleware",  # after authentication: nothing past the password alone
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "sheet.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "sheet.context_processors.theme",
            ],
        },
    },
]

DATABASES = {"default": build_database_settings(os.environ, debug=DEBUG, base_dir=BASE_DIR)}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "admin/")  # move it with DJANGO_ADMIN_URL=private-path/

LOGIN_URL = "/login/"
OTP_TOTP_ISSUER = "Marine Service Sheet"  # the name shown in Microsoft Authenticator
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# ---- security -------------------------------------------------------------------------------
# Idle timeout: the session lives N minutes after the LAST request (it is refreshed on every request).
SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_IDLE_MINUTES", 60)) * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_NAME = "sessionid"  # "__Host-" prefixed in production, below
CSRF_COOKIE_NAME = "csrftoken"
REMEMBER_COOKIE_NAME = "remember"  # "Remember this computer" (sheet/twostep.py); "__Host-" prefixed in production
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True  # the page reads the token from a <meta> tag instead
CSRF_COOKIE_SAMESITE = "Lax"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024  # the API only receives small JSON bodies
X_FRAME_OPTIONS = "DENY"
CSRF_FAILURE_VIEW = "sheet.views.csrf_failure"  # JSON under /api/, Django's page elsewhere
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

BEHIND_PROXY = env_bool("DJANGO_BEHIND_PROXY", False)  # only if your reverse proxy sets the headers itself

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # "__Host-": the browser only accepts these cookies over HTTPS, for this exact host and path "/" — no subdomain
    # or other path can set or overwrite them. The app must be served from the root of its own host.
    SESSION_COOKIE_NAME = "__Host-sessionid"
    CSRF_COOKIE_NAME = "__Host-csrftoken"
    REMEMBER_COOKIE_NAME = "__Host-remember"
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Preloading commits the whole domain to HTTPS in every browser for months; the domain owner decides.
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
    if not SECURE_HSTS_PRELOAD:
        SILENCED_SYSTEM_CHECKS = ["security.W021"]
    if BEHIND_PROXY:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Behind a reverse proxy every request seems to come from the proxy. Name the header your proxy sets
# (e.g. "X-Forwarded-For") so login throttling and logs see the real client. Leave empty if not behind a proxy.
# The LAST address in that header is used, because that is the one your own proxy appended.
_ip_header = os.environ.get("DJANGO_CLIENT_IP_HEADER", "").strip()
CLIENT_IP_META_KEY = "HTTP_" + _ip_header.upper().replace("-", "_") if _ip_header else ""

# API rate limits (sheet/ratelimit.py), per window: writes per user and per address, CSV exports per user.
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("DJANGO_RATE_LIMIT_WINDOW_SECONDS", 600))
RATE_LIMIT_WRITES_PER_USER = int(os.environ.get("DJANGO_RATE_LIMIT_WRITES_PER_USER", 120))
RATE_LIMIT_WRITES_PER_IP = int(os.environ.get("DJANGO_RATE_LIMIT_WRITES_PER_IP", 600))
RATE_LIMIT_EXPORTS_PER_USER = int(os.environ.get("DJANGO_RATE_LIMIT_EXPORTS_PER_USER", 20))

# The LOG letter's pictures (logo.jpg, stamp.jpg, footer.jpg): a folder outside the project and outside static files,
# never in git (the stamp is signed). Empty / missing -> the letter is made without them (demo, tests).
LETTERHEAD_DIR = os.environ.get("DJANGO_LETTERHEAD_DIR", "")

# Alerting (sheet/alerts.py): ALERT_THRESHOLD lock-outs, denied requests or server errors within the window write one
# `sheet.alert` ERROR record, and e-mail DJANGO_ALERT_EMAILS (comma-separated) if set (needs Django's EMAIL_* settings).
ALERT_THRESHOLD = int(os.environ.get("DJANGO_ALERT_THRESHOLD", 10))
ALERT_WINDOW_SECONDS = int(os.environ.get("DJANGO_ALERT_WINDOW_SECONDS", 600))
ADMINS = [(address, address) for address in env_list("DJANGO_ALERT_EMAILS")]
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", 25))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_TLS", True)
EMAIL_TIMEOUT = int(os.environ.get("DJANGO_EMAIL_TIMEOUT", 10))  # seconds: a dead mail server never hangs a request
SERVER_EMAIL = os.environ.get("DJANGO_EMAIL_FROM", "marine-sheet@localhost")

# Logs go to the console, and also to a rotating file when DJANGO_LOG_FILE is set (10 MB x 10 files).
_log_handlers = ["console"]
_handlers = {"console": {"class": "logging.StreamHandler", "formatter": "plain"}}
if os.environ.get("DJANGO_LOG_FILE"):
    _handlers["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": os.environ["DJANGO_LOG_FILE"],
        "maxBytes": 10 * 1024 * 1024,
        "backupCount": 10,
        "encoding": "utf-8",
        "formatter": "plain",
    }
    _log_handlers.append("file")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": _handlers,
    "loggers": {
        "sheet.audit": {"handlers": _log_handlers, "level": "INFO", "propagate": False},
        "sheet.security": {"handlers": _log_handlers, "level": "INFO", "propagate": False},
        "sheet.alert": {"handlers": _log_handlers, "level": "INFO", "propagate": False},
        "django.security": {"handlers": _log_handlers, "level": "WARNING", "propagate": False},
        # Not Django's default (which e-mails every error to ADMINS): alerts are e-mailed by sheet/alerts.py only.
        "django.request": {"handlers": _log_handlers, "level": "ERROR", "propagate": False},
    },
}

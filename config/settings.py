from pathlib import Path

import dj_database_url
import sentry_sdk
from decouple import Csv, config
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

BASE_DIR = Path(__file__).resolve().parent.parent


import os

GDAL_LIBRARY_PATH = config("GDAL_LIBRARY_PATH", default=None)
GEOS_LIBRARY_PATH = config("GEOS_LIBRARY_PATH", default=None)

# --------------------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY", default="django-insecure-change-me-before-production")
DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,.railway.app",
    cast=Csv(),
)
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://*.railway.app",
    cast=Csv(),
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "django_celery_beat",
    "axes",
    "accounts",
    "services",
    "marketplace",
    "job_requests",
    "bookings",
    "payments",
    "whatsappbot",
    "webchat",
    "pages",
    "ratings",
    "support_app",
    "verification",
    "disputes",
    "notifications",
    "core",
]

# The interactive test console is NOT part of the V2 manual and must never be reachable
# in production. It is off unless you explicitly turn it on.
ENABLE_DEV_CONSOLE = config("ENABLE_DEV_CONSOLE", default=False, cast=bool)
if ENABLE_DEV_CONSOLE:
    INSTALLED_APPS.append("devconsole")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Part 18.4 — django-axes must be the LAST middleware in the list.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --------------------------------------------------------------------------------------
# Part 4 Step 2 — DATABASES (PostGIS engine on the existing Supabase connection)
# --------------------------------------------------------------------------------------
DATABASES = {
    "default": dj_database_url.parse(
        config("DATABASE_URL"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = config("TIME_ZONE", default="Africa/Lagos")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# --------------------------------------------------------------------------------------
# V1 integration settings (WhatsApp Cloud API + Paystack)
# --------------------------------------------------------------------------------------
WHATSAPP_TOKEN = config("WHATSAPP_TOKEN", default="")
WHATSAPP_PHONE_NUMBER_ID = config("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_VERIFY_TOKEN = config("WHATSAPP_VERIFY_TOKEN", default="")
WHATSAPP_API_VERSION = config("WHATSAPP_API_VERSION", default="v19.0")

PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")

# --------------------------------------------------------------------------------------
# Web chat — the primary customer/artisan channel. Replaces WhatsApp as the required
# transport: every WHATSAPP_* setting above is now optional. If it's blank,
# `notifications.services.send_notification` simply can't fall back to WhatsApp for a
# user who has never used the web channel either — it still tries, logs the failure,
# and falls through to email. Nothing in the request path requires WhatsApp to be
# configured; only `whatsappbot`'s own webhook (a channel you can choose to also run,
# not one the product depends on) does.
# --------------------------------------------------------------------------------------
SITE_NAME = config("SITE_NAME", default="Nigeria Artisan Marketplace")
WEBCHAT_OTP_TTL_SECONDS = config("WEBCHAT_OTP_TTL_SECONDS", default=300, cast=int)
WEBCHAT_OTP_RESEND_COOLDOWN_SECONDS = config(
    "WEBCHAT_OTP_RESEND_COOLDOWN_SECONDS", default=45, cast=int
)
# How long a browser session keeps "owning" delivery for its bound phone number
# after it was last active, before notifications.services falls back to
# WhatsApp/email again. Keeps an abandoned tab from permanently stealing delivery.
WEBCHAT_ACTIVE_WINDOW_HOURS = config("WEBCHAT_ACTIVE_WINDOW_HOURS", default=24, cast=int)
# Suggested poll interval for the widget's JS, in milliseconds. Templated into the
# page so it can be tuned per-environment (e.g. slower under heavy load) without a
# frontend code change.
WEBCHAT_POLL_INTERVAL_MS = config("WEBCHAT_POLL_INTERVAL_MS", default=2500, cast=int)

# Optional real SMS/OTP delivery for the web channel (Nigeria-first: Termii). Leave
# TERMII_API_KEY blank to run with the console/log fallback (see webchat/sms_backends.py)
# — safe for dev and CI, structurally inert in production because it only ever
# surfaces the code back over the API when DEBUG=True.
TERMII_API_KEY = config("TERMII_API_KEY", default="")
TERMII_SENDER_ID = config("TERMII_SENDER_ID", default="ArtisanNG")
TERMII_BASE_URL = config("TERMII_BASE_URL", default="https://api.ng.termii.com/api")

# --- V2 additions below ---
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")
# Part 4 Step 4 — this is NOT the same value as WHATSAPP_TOKEN. Meta App Settings -> Basic -> App Secret.
WHATSAPP_APP_SECRET = config("WHATSAPP_APP_SECRET", default="")
PAYSTACK_ENVIRONMENT = config("PAYSTACK_ENVIRONMENT", default="test")

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=False, cast=bool)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# django-axes (admin login brute-force lockout — Part 18.4)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
# Lock on the (username, ip) pair: locking on username alone lets an attacker lock out
# a real staff account on purpose; locking on IP alone is bypassed by rotating IPs.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Part 18.3 — cache backend django-ratelimit counts against.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
if config("USE_LOCMEM_CACHE", default=False, cast=bool):
    # Escape hatch for CI / test runs with no Redis available.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ratelimit",
        }
    }

# Part 12 Step 3 — SMTP for the notification email fallback.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="no-reply@artisanmarketplace.ng"
)

# Part 18.2 — private, S3-compatible object storage (Supabase Storage / Backblaze B2).
STORAGE_ENDPOINT_URL = config("STORAGE_ENDPOINT_URL", default="")
STORAGE_BUCKET = config("STORAGE_BUCKET", default="artisan-verification-private")
STORAGE_ACCESS_KEY = config("STORAGE_ACCESS_KEY", default="")
STORAGE_SECRET_KEY = config("STORAGE_SECRET_KEY", default="")
STORAGE_REGION = config("STORAGE_REGION", default="auto")

# Security hardening — active when DEBUG is False (production). Part 18.6.
if not DEBUG:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

# Part 23 Step 8 — Sentry error monitoring (web + Celery).
SENTRY_DSN = config("SENTRY_DSN", default="")
if not DEBUG and SENTRY_DSN and not SENTRY_DSN.startswith("leave-this-blank"):
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment=config("SENTRY_ENVIRONMENT", default=PAYSTACK_ENVIRONMENT),
    )

# --------------------------------------------------------------------------------------
# Logging — structured enough to debug a webhook at 2am, quiet enough to read.
# --------------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "payments": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "whatsappbot": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "webchat": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "marketplace": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "notifications": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}

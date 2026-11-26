"""
Django settings for the Vessel Arrival Intelligence backend (Phase 1).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = os.getenv("DEBUG", "False") == "True"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    # domain apps
    "apps.common",
    "apps.ports",
    "apps.vessels",
    "apps.companies",
    "apps.relationships",
    "apps.observations",
    "apps.opportunities",
    "apps.enrichment",
    "apps.outreach",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.web.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context_processors.web_user_role",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Use PostgreSQL when DB_NAME is configured; fall back to sqlite for quick local
# spin-up / running the test suite without a Postgres instance available.
if os.getenv("DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Production hashed static files switch
STATIC_HASHING = os.getenv("STATIC_HASHING", "False").lower() in ("true", "1", "yes")

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "apps.web.storage.AggregatedManifestStaticFilesStorage"
            if STATIC_HASHING
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

# --- Security settings (environment-driven with safe development defaults) ---
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False").lower() in ("true", "1", "yes")
_hsts_sec = os.getenv("SECURE_HSTS_SECONDS")
SECURE_HSTS_SECONDS = int(_hsts_sec) if _hsts_sec else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "False").lower() in ("true", "1", "yes")

# Cookie names are specific to this project. Browsers share cookies between
# ports on the same host (127.0.0.1:8000 and 127.0.0.1:8001 are the same cookie
# jar), so two Django apps using the default names log each other out.
SESSION_COOKIE_NAME = "vi_sessionid"
CSRF_COOKIE_NAME = "vi_csrftoken"  # api.js reads this exact name

# Unconditional security settings & headers
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

WEB_CSP_MODE = os.getenv("WEB_CSP_MODE", "enforce")

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
}

from datetime import timedelta  # noqa: E402  (placed here to keep settings self-contained)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- Role group names (single source of truth) ---
ROLE_ADMIN = "Admin"
ROLE_BD_MANAGER = "BD Manager"

# Vessel type substrings excluded from discovery (case-insensitive, blocklist —
# new/unseen commercial types are included by default).
VESSEL_TYPE_EXCLUSIONS = [
    "Tug",
    "Landing Craft",
    "Supply Ship",
    "Hand Mark",
    "Buoy",
    "Pilot",
    "Dredger",
    "Patrol",
]

# Vessel name keywords checked as fallback when vessel_type is empty or "Unknown"
VESSEL_NAME_EXCLUSION_KEYWORDS = ["PILOT", "SAR AIRCRAFT", "PATROL"]

# Maximum plausible speed for a commercial vessel (knots)
MAX_PLAUSIBLE_VESSEL_SPEED_KNOTS = 60

# --- Kpler & MarineTraffic integration settings ---
MARINETRAFFIC_API_KEY = os.getenv("MARINETRAFFIC_API_KEY", "")
MARINETRAFFIC_BASE_URL = os.getenv(
    "MARINETRAFFIC_BASE_URL", "https://services.marinetraffic.com/api"
)
KPLER_API_KEY = os.getenv("KPLER_API_KEY", "")
KPLER_GRAPHQL_URL = os.getenv(
    "KPLER_GRAPHQL_URL", "https://api.kpler.com/v2/maritime/vessels/graphql"
)
_DEFAULT_KPLER_AIS_URL = "https://api.kpler.com/v2/maritime/ais-latest"
_ais_url = (os.getenv("KPLER_AIS_URL") or "").strip()
# A blank value or a stray comment in .env must never become the URL.
KPLER_AIS_URL = _ais_url if _ais_url.lower().startswith(("https://", "http://")) else _DEFAULT_KPLER_AIS_URL
# AIS Latest may use its own key; when KPLER_AIS_API_KEY is empty the KPLER_API_KEY is used.
KPLER_AIS_API_KEY = os.getenv("KPLER_AIS_API_KEY", "")
# Positions older than this are ignored (the API returns the latest position of the past 7 days).
AIS_MAX_POSITION_AGE_HOURS = int(os.getenv("AIS_MAX_POSITION_AGE_HOURS", "24"))
# A vessel in the port area at or below this speed (knots) counts as anchored.
AIS_ANCHORAGE_MAX_SOG = float(os.getenv("AIS_ANCHORAGE_MAX_SOG", "1.0"))
AIS_LATEST_LIMIT = int(os.getenv("AIS_LATEST_LIMIT", "5000"))
# Run AIS Latest after Expected Arrivals when the live refresh button is used.
INGEST_REFRESH_AIS_ENABLED = os.getenv("INGEST_REFRESH_AIS_ENABLED", "True").lower() in ("true", "1", "yes")
KPLER_HTTP_TIMEOUT_SECONDS = int(os.getenv("KPLER_HTTP_TIMEOUT_SECONDS", "30"))
_raw_dir = os.getenv("KPLER_RAW_DIR")
KPLER_RAW_DIR = Path(_raw_dir) if _raw_dir else (BASE_DIR / "data" / "kpler")
KPLER_GRAPHQL_PAGE_SIZE = int(os.getenv("KPLER_GRAPHQL_PAGE_SIZE", "100"))
KPLER_OWNERSHIP_ENABLED = os.getenv("KPLER_OWNERSHIP_ENABLED", "False").lower() in ("true", "1", "yes")
# Kpler allows 500 vessel lookups a month; keep a small safety margin.
KPLER_OWNERSHIP_MONTHLY_IMO_CAP = int(os.getenv("KPLER_OWNERSHIP_MONTHLY_IMO_CAP", "480"))
# Day of the month on which the Kpler allowance starts again (1 = the 1st).
KPLER_QUOTA_RESET_DAY = int(os.getenv("KPLER_QUOTA_RESET_DAY", "1"))
# A vessel is looked up again only after this many days.
OWNERSHIP_RECHECK_DAYS = int(os.getenv("OWNERSHIP_RECHECK_DAYS", "180"))
# Lookups kept every day for the "Look up owner" button (the rest go to the daily sync).
OWNERSHIP_MANUAL_DAILY_RESERVE = int(os.getenv("OWNERSHIP_MANUAL_DAILY_RESERVE", "4"))
OWNERSHIP_DAILY_MAX_IMOS = int(os.getenv("OWNERSHIP_DAILY_MAX_IMOS", "32"))
# MarineTraffic extended arrivals: one call per port per day. The app waits at least this
# many hours before asking for the same port again (23 so a daily run is never blocked).
MT_ARRIVALS_MIN_GAP_HOURS = int(os.getenv("MT_ARRIVALS_MIN_GAP_HOURS", "23"))

EXPECTED_ARRIVALS_TIMESPAN_DAYS = int(os.getenv("EXPECTED_ARRIVALS_TIMESPAN_DAYS", "14"))
EXPECTED_ARRIVALS_DAYS_LAST_SIGNAL = int(os.getenv("EXPECTED_ARRIVALS_DAYS_LAST_SIGNAL", "1"))
EXPECTED_ARRIVALS_GT_MIN = int(os.getenv("EXPECTED_ARRIVALS_GT_MIN", "3000"))
EXPECTED_ARRIVALS_GT_MAX = int(os.getenv("EXPECTED_ARRIVALS_GT_MAX", "500000"))

# --- Lead scoring engine ---
SCORING_RELEVANT_VESSEL_SEGMENTS = {
    # exact type strings -> +20; keyword substring matches -> +10
    "exact": ["Container Ship", "Chemical/Oil Products Tanker", "Bulk Carrier"],
    "keyword": [
        "Tanker",
        "Container",
        "Bulk",
        "Bulk Carrier",
        "LNG",
        "LPG",
        "Heavy Load",
        "Ro-Ro",
        "RoRo",
        "General Cargo",
    ],
}
SCORING_LARGE_FLEET_DWT_THRESHOLD = 50000  # DWT above this -> +10
SCORING_RECENT_NEGATIVE_WINDOW_DAYS = 90   # "lost" within this many days -> -20

SCORE_BANDS = [
    (80, "HOT"),
    (60, "HIGH"),
    (40, "MEDIUM"),
    (0, "LOW"),
]  # ordered highest-threshold first; first threshold <= score wins

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "application.log",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {
        "vessel_intel": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
    },
}

# --- Live refresh button (Lead board "Refresh data (live)") ---
INGEST_REFRESH_ENABLED = os.getenv("INGEST_REFRESH_ENABLED", "True").lower() in ("true", "1", "yes")
INGEST_REFRESH_OWNERSHIP_ENABLED = os.getenv("INGEST_REFRESH_OWNERSHIP_ENABLED", "True").lower() in ("true", "1", "yes")
INGEST_REFRESH_OWNERSHIP_MAX_IMOS = int(os.getenv("INGEST_REFRESH_OWNERSHIP_MAX_IMOS", "20"))
INGEST_REFRESH_COOLDOWN_SECONDS = int(os.getenv("INGEST_REFRESH_COOLDOWN_SECONDS", "120"))
INGEST_REFRESH_PORTS = ["SGSIN", "AEFJR"]
INGEST_REFRESH_STALE_MINUTES = int(os.getenv("INGEST_REFRESH_STALE_MINUTES", "10"))
# When True the refresh runs inline instead of in a background thread (tests).
INGEST_REFRESH_SYNC = os.getenv("INGEST_REFRESH_SYNC", "False").lower() in ("true", "1", "yes")

# --- Email from the "Send mail" button ---
# With no EMAIL_HOST the mail is only printed in the server window (test mode) and nothing is delivered.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
# Port 587 uses STARTTLS (EMAIL_USE_TLS). Port 465 uses SSL from the start: set EMAIL_USE_SSL=True and EMAIL_USE_TLS=False.
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("true", "1", "yes") and not EMAIL_USE_SSL
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))   # seconds; a slow mail server must not freeze the page
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST else "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@localhost")
OUTREACH_ENABLED = os.getenv("OUTREACH_ENABLED", "True").lower() in ("true", "1", "yes")
# Optional: a shared mailbox that gets a hidden copy of every mail (comma separated).
OUTREACH_BCC = os.getenv("OUTREACH_BCC", "")
# Ask for confirmation when the same company was already mailed about the same vessel this recently.
OUTREACH_RESEND_BLOCK_DAYS = int(os.getenv("OUTREACH_RESEND_BLOCK_DAYS", "3"))
# While testing: set this to your own address and EVERY mail is delivered there instead of to the company, so no
# real owner or manager is contacted. Leave it empty in production.
OUTREACH_TEST_RECIPIENT = os.getenv("OUTREACH_TEST_RECIPIENT", "")
OUTREACH_DAILY_LIMIT_PER_USER = int(os.getenv("OUTREACH_DAILY_LIMIT_PER_USER", "50"))

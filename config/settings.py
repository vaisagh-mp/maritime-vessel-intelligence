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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

# --- DataDocked (AIS / vessel intelligence provider) ---
DATADOCKED_API_KEY = os.getenv("DATADOCKED_API_KEY", "")
DATADOCKED_BASE_URL = os.getenv(
    "DATADOCKED_BASE_URL", "https://datadocked.com/api/vessels_operations"
)

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

# Expected-arrivals discovery: max pages fetched per port per run (50 credits/page).
# If a port returns more pages, only the first N are processed and a warning is logged.
EXPECTED_ARRIVALS_MAX_PAGES_PER_PORT = 3

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

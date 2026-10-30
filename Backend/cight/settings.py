"""Django settings for CIGHT-BROWSER.

Requirements implemented:
- CON-04: Django/PostgreSQL is authoritative source of truth.
- NFR-SEC-02 / NFR-OPS-01: All configuration loaded from environment via django-environ.
- NFR-SEC-05: CSRF middleware kept enabled.
- NFR-SEC-07: Disable third-party telemetry (PostHog, CloudSync) at startup.
- NFR-OPS-02: Operational thresholds configured via environment variables.
- NFR-OPS-03: Structured JSON logging with structlog.
- FR-53: Server-side browser profile root configuration.
"""
import os
from pathlib import Path

import environ
import structlog

# NFR-SEC-07: Explicitly prevent browser-use third-party telemetry & cloud sync
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "django-insecure-default-development-key-replace-in-prod"),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DATABASE_URL=(str, ""),
    REDIS_URL=(str, "redis://127.0.0.1:6379/0"),
    GEMINI_API_KEY=(str, ""),
    GEMINI_MODEL=(str, "gemini-2.5-flash"),
    LOOP_REPEAT_LIMIT=(int, 3),
    CONSECUTIVE_FAILURE_LIMIT=(int, 3),
    ACTION_TIMEOUT_SECONDS=(int, 30),
    LLM_TIMEOUT_SECONDS=(int, 30),
    CONFIRMATION_EXPIRY_SECONDS=(int, 120),
    TASK_MAX_STEPS=(int, 50),
    BROWSER_HEADLESS=(bool, False),
    BROWSER_PROFILE_ROOT=(str, str(BASE_DIR / "browser_profiles")),
)

# Read .env file if it exists
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",  # NFR-SEC-05: CSRF kept enabled
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cight.urls"

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

WSGI_APPLICATION = "cight.wsgi.application"
ASGI_APPLICATION = "cight.asgi.application"

# Database (CON-04)
# Falls back to SQLite if DATABASE_URL is unset (e.g. lightweight unit testing in CI)
DATABASE_URL = env("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": env.db("DATABASE_URL"),
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Password validation
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

# Redis & Channels Layer
REDIS_URL = env("REDIS_URL")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}

# Celery Configuration (CON-01)
CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# AI Configuration (SRS §2.5, TBD-02)
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL")

# Operational Thresholds (NFR-OPS-02)
LOOP_REPEAT_LIMIT = env("LOOP_REPEAT_LIMIT")
CONSECUTIVE_FAILURE_LIMIT = env("CONSECUTIVE_FAILURE_LIMIT")
ACTION_TIMEOUT_SECONDS = env("ACTION_TIMEOUT_SECONDS")
LLM_TIMEOUT_SECONDS = env("LLM_TIMEOUT_SECONDS")
CONFIRMATION_EXPIRY_SECONDS = env("CONFIRMATION_EXPIRY_SECONDS")
TASK_MAX_STEPS = env("TASK_MAX_STEPS")
BROWSER_HEADLESS = env("BROWSER_HEADLESS")

# Browser Profiles Root (FR-52..54)
BROWSER_PROFILE_ROOT = Path(env("BROWSER_PROFILE_ROOT"))
BROWSER_PROFILE_ROOT.mkdir(parents=True, exist_ok=True)

# Structured JSON Logging (NFR-OPS-03)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json_formatter": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json_formatter",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "core": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


"""
Django settings for the AI-Powered E-Complaint Analysis System.

Backend: Django (apps: accounts, complaints). Frontend: HTML5/CSS3/JS served from
the top-level ``frontend/`` directory (templates + static files).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY: override these through environment variables in any real deployment.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-change-me-in-production",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "complaints",
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
        "DIRS": [BASE_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite for development. The SRS targets PostgreSQL 14+/MySQL 8+; switch the
# ENGINE/NAME/... below when deploying (no application code depends on SQLite).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.LetterAndDigitValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication / sessions (REQ-AUTH-008, REQ-SEC-006) ---
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"
SESSION_COOKIE_AGE = 30 * 60          # 30 minutes of inactivity
SESSION_SAVE_EVERY_REQUEST = True     # sliding window -> inactivity timeout
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

# --- Lockout policy (REQ-AUTH-006) ---
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_FAILURE_WINDOW_MINUTES = 10
LOGIN_LOCKOUT_MINUTES = 15

# --- Self-registration guards for privileged roles ---
# Citizens may register freely. Officer / System Administrator sign-ups require
# a registration code so that anyone on the internet cannot mint a privileged
# account. Override via environment variables; these are DEV defaults.
OFFICER_REGISTRATION_CODE = os.environ.get("OFFICER_REGISTRATION_CODE", "OFFICER-DEV-2026")
ADMIN_REGISTRATION_CODE = os.environ.get("ADMIN_REGISTRATION_CODE", "SYSADMIN-DEV-2026")

# --- Complaint attachments (REQ-CMP-002/003) ---
MAX_ATTACHMENTS_PER_COMPLAINT = 3
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

# --- Email (REQ-NOT-*): console backend in development ---
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = "ecomplaint@localhost"

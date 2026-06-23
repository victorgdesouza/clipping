import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def env_int(name, default=0):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


DATABASE_URL = os.getenv("DATABASE_URL")
DEBUG = env_bool("DEBUG", default=not bool(DATABASE_URL))
SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    if DEBUG or not DATABASE_URL:
        SECRET_KEY = "django-insecure-local-development-only"
    else:
        raise ImproperlyConfigured("Defina SECRET_KEY no ambiente.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")
ALLOWED_HOSTS += [".onrender.com"]
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

IS_PRODUCTION = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=IS_PRODUCTION)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=IS_PRODUCTION)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=IS_PRODUCTION)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000 if IS_PRODUCTION else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=IS_PRODUCTION)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)
X_FRAME_OPTIONS = "DENY"

NEWSAPI_API_KEY = os.getenv("NEWSAPI_API_KEY", "")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
BRAVE_SEARCH_MAX_QUERIES = env_int("BRAVE_SEARCH_MAX_QUERIES", 12)
BRAVE_SEARCH_RESULTS_PER_QUERY = env_int("BRAVE_SEARCH_RESULTS_PER_QUERY", 20)
BRAVE_SEARCH_TIMEOUT_SECONDS = env_int("BRAVE_SEARCH_TIMEOUT_SECONDS", 10)
BRAVE_SEARCH_WORKERS = env_int("BRAVE_SEARCH_WORKERS", 4)
BRAVE_SEARCH_FRESHNESS = os.getenv("BRAVE_SEARCH_FRESHNESS", "pm")
DISCOVERY_MIN_RELEVANCE_SCORE = env_int("DISCOVERY_MIN_RELEVANCE_SCORE", 35)
DISCOVERY_PROFILE_NEW_SOURCES = env_int("DISCOVERY_PROFILE_NEW_SOURCES", 5)
DISCOVERY_MIN_INTERVAL_HOURS = env_int("DISCOVERY_MIN_INTERVAL_HOURS", 24)
SITEMAP_MAX_CHILDREN = env_int("SITEMAP_MAX_CHILDREN", 3)
SITEMAP_MAX_ARTICLES = env_int("SITEMAP_MAX_ARTICLES", 30)
USE_LLM_SEARCH = env_bool("USE_LLM_SEARCH", default=False)
GPTNEO_MODEL = os.getenv("GPTNEO_MODEL", "EleutherAI/gpt-neo-2.7B")


INSTALLED_APPS = [
    "newsclip.apps.NewsclipConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "django_q",
    "reports_app.apps.ReportsAppConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"
SITE_ID = 1

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

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

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=env_bool("DATABASE_SSL_REQUIRE", default=True),
        )
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

LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "pt-br")
TIME_ZONE = os.getenv("TIME_ZONE", "America/Sao_Paulo")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

Q_CLUSTER = {
    "name": "newsclip_cluster",
    # Um worker compartilha a instancia gratuita com o Gunicorn sem multiplicar
    # o consumo de memoria. A fila ORM preserva as tarefas no PostgreSQL.
    "workers": int(os.getenv("Q_CLUSTER_WORKERS", "1")),
    "recycle": 500,
    "timeout": int(os.getenv("Q_CLUSTER_TIMEOUT", "1800")),
    "retry": int(os.getenv("Q_CLUSTER_RETRY", "1860")),
    "compress": True,
    "save_limit": 250,
    "queue_limit": 500,
    "cpu_affinity": 1,
    "label": "Django Q",
    "orm": "default",
}

LOG_HANDLERS = ["console"]
if DEBUG:
    LOG_HANDLERS.append("file")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "debug.log",
            "formatter": "verbose",
        },
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "newsclip": {
            "handlers": LOG_HANDLERS,
            "level": "INFO",
            "propagate": True,
        },
        "django_q": {
            "handlers": LOG_HANDLERS,
            "level": "INFO",
            "propagate": True,
        },
    },
}

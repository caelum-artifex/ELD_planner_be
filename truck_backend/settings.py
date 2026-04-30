import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-key-change-in-production")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

# ── Apps ──────────────────────────────────────────────────────────────────────
# Only the minimum apps required — no admin, auth, sessions, or contenttypes
# because this API is fully stateless and uses no database.
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    "corsheaders",
    "rest_framework",
    "planner",
]

# ── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "truck_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "truck_backend.wsgi.application"

# ── No database needed ────────────────────────────────────────────────────────
# Trip planning is fully stateless — all computation happens in-memory.
# No models, no migrations, no DB connection required.

# ── Static files (served by WhiteNoise in production) ────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow all origins in dev. Set CORS_ALLOWED_ORIGINS env var in production
# to restrict to your Vercel frontend URL.
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _cors_origins:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",")]
else:
    CORS_ALLOW_ALL_ORIGINS = True

# ── Misc ──────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

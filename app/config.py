import os
import secrets
from urllib.parse import quote_plus, urlsplit
from sqlalchemy.engine import make_url

from dotenv import load_dotenv

load_dotenv()

_PLACEHOLDER_SECRETS = {
    "change-this-secret-key",
    "change-this-jwt-secret",
    "your-secret-key",
    "your-jwt-secret",
}


def _configured_secret(name, app_env):
    value = os.environ.get(name)
    if app_env != "production" and (
        not value or value.strip().lower() in _PLACEHOLDER_SECRETS
    ):
        return secrets.token_urlsafe(48)
    return value


def validate_security_config(config):
    """Fail closed when production security settings are incomplete."""
    app_env = str(config.get("APP_ENV", "development")).strip().lower()
    if app_env not in {"development", "testing", "production"}:
        raise RuntimeError("APP_ENV must be development, testing, or production")
    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("Set DATABASE_URL or explicit PostgreSQL connection variables")

    if app_env != "production":
        return

    rate_limit_storage = urlsplit(str(config.get("RATELIMIT_STORAGE_URI", "memory://")))
    if rate_limit_storage.scheme not in {"redis", "rediss"} or not rate_limit_storage.netloc:
        raise RuntimeError("Production requires a shared Redis RATELIMIT_STORAGE_URI")

    for name in ("SECRET_KEY", "JWT_SECRET"):
        value = config.get(name)
        if (
            not isinstance(value, str)
            or len(value.encode("utf-8")) < 32
            or value.strip().lower() in _PLACEHOLDER_SECRETS
        ):
            raise RuntimeError(f"Production requires a unique, non-placeholder {name} of at least 32 bytes")

    if config.get("DEBUG"):
        raise RuntimeError("DEBUG must be disabled in production")
    if not config.get("SESSION_COOKIE_SECURE"):
        raise RuntimeError("SESSION_COOKIE_SECURE must be enabled in production")
    if not str(config.get("APP_BASE_URL", "")).lower().startswith("https://"):
        raise RuntimeError("APP_BASE_URL must use HTTPS in production")

    database_url = make_url(config["SQLALCHEMY_DATABASE_URI"])
    if database_url.get_backend_name() != "postgresql":
        raise RuntimeError("Production must use PostgreSQL")
    if (database_url.username or "").lower() == "postgres":
        raise RuntimeError("Production must use a least-privilege PostgreSQL role, not postgres")


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        postgres_user = os.environ.get("POSTGRES_USER")
        postgres_password = os.environ.get("POSTGRES_PASSWORD")
        postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
        postgres_port = os.environ.get("POSTGRES_PORT", "5432")
        postgres_database = os.environ.get("POSTGRES_DB")
        if postgres_user and postgres_password and postgres_database:
            credentials = f"{postgres_user}:{quote_plus(postgres_password)}"
            DATABASE_URL = (
                f"postgresql+psycopg2://{credentials}@"
                f"{postgres_host}:{postgres_port}/{postgres_database}"
            )

    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SLOW_QUERY_THRESHOLD_MS = float(os.environ.get("SLOW_QUERY_THRESHOLD_MS", "500"))
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    # Apply a baseline ceiling to every route; authentication routes also have
    # stricter per-view limits in app.routes.auth.
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "600 per hour")
    RATELIMIT_HEADERS_ENABLED = True

    SECRET_KEY = _configured_secret("SECRET_KEY", APP_ENV)
    JWT_SECRET = _configured_secret("JWT_SECRET", APP_ENV)
    DEBUG = APP_ENV == "development"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CROP_DISTANCE_METERS = int(os.environ.get("MAX_CROP_DISTANCE_METERS", "15000"))
    MAX_CROP_DISTANCE_KM = MAX_CROP_DISTANCE_METERS / 1000
    MAX_CROP_PHOTO_SIZE_BYTES = 5 * 1024 * 1024
    MAX_PROFILE_PHOTO_SIZE_BYTES = 5 * 1024 * 1024
    MAX_CHAT_ATTACHMENT_SIZE_BYTES = 50 * 1024 * 1024
    MAX_KNOWLEDGE_MEDIA_SIZE_BYTES = 50 * 1024 * 1024
    MAX_CONTENT_LENGTH = 60 * 1024 * 1024

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("MAIL_USERNAME", "noreply@agridirect.local")
    INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "")
    INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}
    # SMTP debug output can include AUTH payloads. Never enable it, even in development.
    MAIL_DEBUG = False

    _mail_suppress_override = os.environ.get("MAIL_SUPPRESS_SEND")
    if _mail_suppress_override is None:
        smtp_configured = bool(MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD and MAIL_SERVER != "localhost")
        MAIL_SUPPRESS_SEND = not smtp_configured
    else:
        MAIL_SUPPRESS_SEND = _mail_suppress_override.lower() in {"1", "true", "yes", "on"}

    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

    @staticmethod
    def validate(config):
        validate_security_config(config)

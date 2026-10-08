"""Agri Directs Flask application package.

This module creates the Flask application and keeps a compatibility layer for
older imports without forcing a circular dependency during package import.
"""

from pathlib import Path
from datetime import datetime
import time

from flask import Flask, g, request, session
from sqlalchemy.exc import SQLAlchemyError

from .config import Config
from .extensions import bcrypt, db, login_manager, mail, migrate
from .models.database import update_analytics
from .services.audit_service import record_request_event, should_audit_request

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database.db"


def create_app(config_overrides=None):
    """Create and configure the Flask app instance."""
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "app" / "templates"),
        static_folder=str(BASE_DIR / "app" / "static"),
    )
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.config.setdefault("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
    app.secret_key = app.config.get("SECRET_KEY", "agridirect_secret")

    @app.template_filter("datetime_format")
    def datetime_format(value, format_string="%Y-%m-%d %H:%M"):
        """Format database datetimes consistently across SQLite and PostgreSQL."""
        if not value:
            return ""
        if isinstance(value, datetime):
            return value.strftime(format_string)
        return str(value)[:10] if format_string == "%Y-%m-%d" else str(value)[:16]

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    mail.init_app(app)
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            from .models.auth.models import User
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    from . import routes
    routes.register_routes(app)

    @app.before_request
    def start_request_timer():
        g.request_started_at = time.perf_counter()
        g.audit_actor = session.get("user")
        g.audit_role = session.get("role")

    @app.after_request
    def write_audit_event(response):
        if should_audit_request(request.endpoint, request.method, request.path):
            started_at = getattr(g, "request_started_at", time.perf_counter())
            try:
                record_request_event(
                    response.status_code,
                    (time.perf_counter() - started_at) * 1000,
                    session.get("user") or getattr(g, "audit_actor", None),
                    session.get("role") or getattr(g, "audit_role", None),
                )
            except SQLAlchemyError:
                app.logger.exception("Unable to persist request audit event")
        return response

    return app


app = create_app()


def get_db():
    from .legacy import get_db as _legacy_get_db
    return _legacy_get_db()


def init_db():
    from .legacy import init_db as _legacy_init_db
    with app.app_context():
        return _legacy_init_db()


__all__ = [
    "app",
    "create_app",
    "get_db",
    "init_db",
    "update_analytics",
    "db",
    "migrate",
    "bcrypt",
    "login_manager",
    "DB_PATH",
]

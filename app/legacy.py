from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import csv
import os
import logging
import calendar
import re
from datetime import datetime, timedelta
from collections import defaultdict
import jwt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from functools import wraps

from .config import Config
from .extensions import db, migrate

# Bootstrap and compatibility symbols remain here so existing imports continue
# to work while domain implementations live in dedicated packages.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database.db")  # legacy import compatibility
DEFAULT_DB_PATH = DB_PATH

try:
    from . import app as _package_app
except ImportError:  # pragma: no cover - used only during direct legacy import fallback
    _package_app = None

if _package_app is not None:
    app = _package_app
else:
    app = Flask("app", template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    app.secret_key = os.environ.get("SECRET_KEY", "agridirect_secret")
    db.init_app(app)
    migrate.init_app(app, db)


def create_app():
    # ``app.legacy`` is still importable directly; defer route imports until
    # requested so the compatibility module does not create import cycles.
    from .routes import register_routes
    register_routes(app)
    return app

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

API_KEY = os.environ.get("API_KEY", "mysecurekey123")
JWT_SECRET = os.environ.get("JWT_SECRET", "jwt_secret_key_agridirect")

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from .algorithms.market_analysis import _parse_inventory_datetime, _linear_forecast, build_market_analysis
from .services.geo_service import geocode_location
from .services.auth_service import generate_jwt_token, verify_jwt_token, token_required
from .models.database import (
    get_db, PostgreSQLCursor, CompatRow, _compat_row, SQLAlchemyConnection,
    _save_upload_file, _seed_default_crops, _migrate_harvest_to_inventory,
    init_db, update_analytics,
)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

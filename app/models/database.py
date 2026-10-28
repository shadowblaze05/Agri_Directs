"""Flask-SQLAlchemy database compatibility and schema helpers.

The application historically exposed a DB-API-like ``get_db`` function. This
module preserves that interface while keeping PostgreSQL translation and schema
management out of HTTP route modules.
"""

import importlib
import logging
import os
import re
import uuid
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime

from flask import current_app, has_app_context
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from ..extensions import db
from ..password_policy import password_policy_error
from ..algorithms.market_analysis import build_market_analysis

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logger = logging.getLogger(__name__)

def _with_app_context():
    if has_app_context():
        return nullcontext()
    try:
        package_app = importlib.import_module("app")
    except ImportError:  # pragma: no cover - fallback import path
        return nullcontext()
    app = getattr(package_app, "app", None)
    if app is None:
        return nullcontext()
    return app.app_context()


def get_db():
    return SQLAlchemyConnection()


class PostgreSQLCursor:
    """Compatibility cursor backed entirely by Flask-SQLAlchemy."""

    _sqlite_ddl = re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE)
    _pragma_table_info = re.compile(r"^\s*PRAGMA\s+table_info\((\w+)\)\s*$", re.IGNORECASE)

    def __init__(self):
        self._result = None

    @staticmethod
    def _translate_sql(sql):
        pragma_match = PostgreSQLCursor._pragma_table_info.match(sql)
        if pragma_match:
            table_name = pragma_match.group(1)
            return (
                "SELECT ordinal_position - 1 AS cid, column_name AS name, "
                "data_type AS type, (is_nullable = 'NO') AS notnull, "
                "column_default AS dflt_value, 0 AS pk "
                "FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :table_name "
                "ORDER BY ordinal_position",
                {"table_name": table_name},
            )

        sql = PostgreSQLCursor._sqlite_ddl.sub("SERIAL PRIMARY KEY", sql)
        sql = re.sub(r"\bDATETIME\b", "TIMESTAMP", sql, flags=re.IGNORECASE)

        had_ignore = bool(re.match(r"^\s*INSERT\s+OR\s+IGNORE\b", sql, flags=re.IGNORECASE))
        sql = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\b", "INSERT", sql, flags=re.IGNORECASE)
        if had_ignore and "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        sql = sql.replace("strftime('%Y-%m', date_received)", "SUBSTRING(date_received FROM 1 FOR 7)")
        sql = sql.replace("strftime('%Y', date_received)", "SUBSTRING(date_received FROM 1 FOR 4)")
        sql = sql.replace("strftime(\"%Y-%m\", date_received)", "SUBSTRING(date_received FROM 1 FOR 7)")
        sql = sql.replace("strftime(\"%Y\", date_received)", "SUBSTRING(date_received FROM 1 FOR 4)")
        return sql, None

    @staticmethod
    def _named_parameters(sql, params):
        if not params:
            return sql, {}
        if isinstance(params, dict):
            return sql, params
        named_sql = []
        named_params = {}
        index = 0
        for character in sql:
            if character == "?":
                name = f"p{index}"
                named_sql.append(f":{name}")
                named_params[name] = params[index]
                index += 1
            else:
                named_sql.append(character)
        if index != len(params):
            raise ValueError("SQL parameter count does not match placeholders")
        return "".join(named_sql), named_params

    def execute(self, sql, params=None):
        legacy_insert = re.match(
            r"^\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+inventory\s*\(\s*crop_name\s*,\s*(.*?)\)\s*VALUES\s*\(\s*(.*?)\s*\)\s*;?\s*$",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if legacy_insert and params is not None:
            remaining_columns = legacy_insert.group(1).strip()
            if remaining_columns:
                legacy_params = tuple(params)
                if legacy_params:
                    sql = (
                        "INSERT INTO inventory(crop_id, crop_name, " + remaining_columns + ") "
                        "VALUES ((SELECT id FROM crops WHERE crops_name = ?), ?, "
                        + ", ".join("?" for _ in range(len(legacy_params) - 1)) + ")"
                    )
                    params = (legacy_params[0],) + legacy_params

        if db.engine.dialect.name == "postgresql":
            translated_sql, pragma_params = self._translate_sql(sql)
        else:
            translated_sql = re.sub(
                r"SUBSTRING\(([\w.]+)\s+FROM\s+(\d+)\s+FOR\s+(\d+)\)",
                r"SUBSTR(\1, \2, \3)",
                sql,
                flags=re.IGNORECASE,
            )
            pragma_params = None
        effective_params = pragma_params if pragma_params is not None else params
        translated_sql, named_params = self._named_parameters(translated_sql, effective_params)
        with _with_app_context():
            self._result = db.session.execute(text(translated_sql), named_params)
            db.session.flush()
        return self

    def executemany(self, sql, params):
        for parameter_set in params:
            self.execute(sql, parameter_set)
        return self

    def fetchone(self):
        return _compat_row(self._result.fetchone())

    def fetchall(self):
        return [_compat_row(row) for row in self._result.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    def __getattr__(self, name):
        return getattr(self._result, name)


class CompatRow(dict):
    """Allow existing handlers to use both row['column'] and row[index]."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def __eq__(self, other):
        if isinstance(other, (tuple, list)):
            return tuple(self.values()) == tuple(other)
        return super().__eq__(other)


def _compat_row(row):
    if row is None:
        return None
    return CompatRow(row._mapping)


class SQLAlchemyConnection:
    """Connection-shaped facade backed by Flask-SQLAlchemy's scoped session."""

    def __init__(self):
        self._context = None
        if not has_app_context():
            try:
                package_app = importlib.import_module("app")
            except ImportError:  # pragma: no cover - fallback import path
                package_app = None
            app = getattr(package_app, "app", None)
            if app is not None:
                self._context = app.app_context()
                self._context.__enter__()

    def cursor(self):
        return PostgreSQLCursor()

    def commit(self):
        with _with_app_context():
            if inspect(db.engine).has_table("inventory") and inspect(db.engine).has_table("crops"):
                db.session.execute(
                    text(
                        "UPDATE inventory "
                        "SET crop_name = (SELECT crops.crops_name FROM crops WHERE crops.id = inventory.crop_id) "
                        "WHERE crop_name IS NULL AND crop_id IS NOT NULL"
                    )
                )
            db.session.flush()
            db.session.commit()

    def close(self):
        with _with_app_context():
            db.session.remove()
        if self._context is not None:
            self._context.__exit__(None, None, None)
            self._context = None


def _save_upload_file(uploaded_file, subfolder):
    from ..services.upload_service import save_sanitized_public_image, save_video_upload

    if not uploaded_file or uploaded_file.filename == "":
        return None

    filename = secure_filename(uploaded_file.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    image_formats = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}
    video_extensions = {"mp4", "m4v", "mov", "webm"}
    if subfolder == "images" and extension not in image_formats:
        raise ValueError("Knowledge Hub images must be PNG, JPG, JPEG, GIF, or WEBP.")
    if subfolder == "videos" and extension not in video_extensions:
        raise ValueError("Knowledge Hub videos must be MP4, M4V, MOV, or WEBM.")
    if subfolder not in {"images", "videos"}:
        raise ValueError("Unsupported Knowledge Hub upload category.")

    upload_dir = os.path.join(current_app.static_folder, "uploads", "knowledge", subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    if not filename:
        raise ValueError("The uploaded filename is invalid.")

    stored_filename = f"{uuid.uuid4().hex}.{extension}"
    file_path = os.path.join(upload_dir, stored_filename)
    maximum_size = current_app.config["MAX_KNOWLEDGE_MEDIA_SIZE_BYTES"]
    if subfolder == "images":
        save_sanitized_public_image(uploaded_file, file_path, image_formats[extension], maximum_size)
    else:
        save_video_upload(uploaded_file, file_path, extension, maximum_size)
    return f"/static/uploads/knowledge/{subfolder}/{stored_filename}"


def _seed_default_crops(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crops(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        crops_name TEXT UNIQUE
    )
    """)

    cur.execute("SELECT COUNT(*) AS count FROM crops")
    if cur.fetchone()["count"] == 0:
        default_crops = ["Rice", "Maize", "Tomato", "Cabbage", "Banana", "Corn", "Cassava"]
        for crop_name in default_crops:
            cur.execute("INSERT OR IGNORE INTO crops(crops_name) VALUES (?)", (crop_name,))


def _migrate_harvest_to_inventory(cur):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS harvest(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        crop_id INTEGER,
        quantity INTEGER,
        farmer TEXT,
        date_received TEXT,
        location TEXT
    )
    """)

    cur.execute("SELECT COUNT(*) AS count FROM inventory")
    inventory_exists = cur.fetchone()["count"] > 0

    cur.execute("SELECT id, crop_id, quantity, farmer, date_received, location FROM harvest ORDER BY id")
    harvest_rows = cur.fetchall()

    for row in harvest_rows:
        if row["crop_id"] is None:
            continue

        existing = cur.execute(
            "SELECT id FROM inventory WHERE crop_id=? AND quantity=? AND farmer=? AND date_received=? AND COALESCE(location, '')=COALESCE(?, '')",
            (row["crop_id"], row["quantity"], row["farmer"], row["date_received"], row["location"])
        ).fetchone()
        if existing:
            continue

        cur.execute(
            "INSERT INTO inventory(crop_id, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)",
            (row["crop_id"], row["quantity"], row["farmer"], row["date_received"], row["location"])
        )

    if harvest_rows and not inventory_exists:
        logger.info("Backfilled dashboard inventory from legacy harvest records")


def init_db():
    if not has_app_context():
        with _with_app_context():
            return init_db()

    conn = get_db()
    cur = conn.cursor()

    database_uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if current_app.config.get("APP_ENV") == "testing" and database_uri.startswith("sqlite:"):
        for table_name in (
            "knowledge_replies",
            "knowledge_comments",
            "knowledge_likes",
            "knowledge_posts",
            "notifications",
            "messages",
            "inventory",
            "analytics",
            "users",
        ):
            try:
                cur.execute(f"DELETE FROM {table_name}")
            except Exception:
                logger.debug("Skipping reset for missing table %s", table_name)
        conn.commit()

    # Create referenced domain tables before PostgreSQL validates foreign keys.
    _seed_default_crops(cur)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'user',
        location TEXT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        reliability_score REAL DEFAULT NULL,
        reliability_status TEXT DEFAULT 'Not Yet Rated',
        completed_transactions INTEGER DEFAULT 0,
        cancelled_transactions INTEGER DEFAULT 0,
        total_transactions INTEGER DEFAULT 0
    )
    """)
    # Keep older SQLite databases compatible with the account-management UI.
    cur.execute("PRAGMA table_info(users)")
    user_columns = [row[1] for row in cur.fetchall()]
    for column, definition in (
        ("first_name", "TEXT"),
        ("last_name", "TEXT"),
        ("email", "TEXT"),
    ):
        if column not in user_columns:
            cur.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS crop_categories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crop_pricing(
        crop_id INTEGER PRIMARY KEY,
        pricing_mode TEXT NOT NULL CHECK (pricing_mode IN ('range', 'bounds')),
        price_unit TEXT NOT NULL DEFAULT 'kg'
            CHECK (price_unit = 'kg'),
        reference_price NUMERIC(10, 2),
        price_range NUMERIC(10, 2),
        minimum_price NUMERIC(10, 2),
        maximum_price NUMERIC(10, 2),
        CHECK (
            (pricing_mode = 'range' AND reference_price > 0
             AND price_range >= 0 AND reference_price > price_range
             AND minimum_price IS NULL
             AND maximum_price IS NULL) OR
            (pricing_mode = 'bounds' AND minimum_price > 0
             AND maximum_price >= minimum_price AND price_range IS NULL
             AND (reference_price IS NULL OR reference_price BETWEEN
                  minimum_price AND maximum_price))
        ),
        FOREIGN KEY (crop_id) REFERENCES crops(id) ON DELETE CASCADE
    )
    """)
    cur.execute("PRAGMA table_info(crops)")
    crop_columns = [row[1] for row in cur.fetchall()]
    if "category_id" not in crop_columns:
        cur.execute("ALTER TABLE crops ADD COLUMN category_id INTEGER")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        crop_id INTEGER,
        crop_name TEXT,
        quantity INTEGER,
        farmer TEXT,
        date_received TEXT,
        location TEXT,
        FOREIGN KEY (crop_id) REFERENCES crops(id)
    )
    """)

    cur.execute("PRAGMA table_info(inventory)")
    inventory_columns = [row[1] for row in cur.fetchall()]
    if 'crop_name' not in inventory_columns:
        cur.execute("ALTER TABLE inventory ADD COLUMN crop_name TEXT")
    if 'crop_id' not in inventory_columns:
        cur.execute("ALTER TABLE inventory ADD COLUMN crop_id INTEGER")
    inventory_geotag_columns = {
        "photo_path": "TEXT",
        "latitude": "REAL",
        "longitude": "REAL",
        "capture_time": "DATETIME",
        "distance_from_user": "REAL",
        "verification_status": "TEXT NOT NULL DEFAULT 'pending'",
        "verification_notes": "TEXT",
        "reviewed_by": "TEXT",
        "reviewed_at": "DATETIME",
    }
    for column, definition in inventory_geotag_columns.items():
        if column not in inventory_columns:
            cur.execute(f"ALTER TABLE inventory ADD COLUMN {column} {definition}")

    cur.execute("""
        UPDATE inventory
        SET crop_name = (
            SELECT crops.crops_name
            FROM crops
            WHERE crops.id = inventory.crop_id
        )
        WHERE crop_name IS NULL AND crop_id IS NOT NULL
    """)
    cur.execute("""
        UPDATE inventory
        SET crop_id = (
            SELECT crops.id
            FROM crops
            WHERE crops.crops_name = inventory.crop_name
        )
        WHERE crop_id IS NULL AND crop_name IS NOT NULL
    """)
    unmatched = cur.execute("SELECT COUNT(*) AS count FROM inventory WHERE crop_id IS NULL").fetchone()["count"]
    if unmatched:
        raise RuntimeError(f"{unmatched} inventory record(s) could not be matched to crops")

    #NEW MARKETPLACE
    cur.execute("""
    CREATE TABLE IF NOT EXISTS marketplace(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        buyer_username TEXT,
        crop_id INTEGER,
        crop_name TEXT,
        amount INTEGER,
        price REAL,
        unit TEXT DEFAULT 'kg',
        status TEXT DEFAULT 'available',
        order_status TEXT DEFAULT 'available',
        listing_date TEXT,
        order_date TEXT,
        delivery_date TEXT,
        delivery_province TEXT,
        delivery_city TEXT,
        delivery_barangay TEXT,
        delivery_street TEXT,
        delivery_landmark TEXT,
        expiry_date TEXT,
        description TEXT,
        location TEXT,
        delivery_confirmed INTEGER DEFAULT 0,
        buyer_confirmed INTEGER DEFAULT 0,
        buyer_confirm_date TEXT,
        buyer_rating INTEGER DEFAULT NULL,
        buyer_rating_date TEXT,
        main_image TEXT,
        listing_type TEXT DEFAULT 'standard',
        available_date TEXT,
        preorder_status TEXT,
        preorder_quantity INTEGER,
        cancel_requested_by TEXT,
        cancel_reason TEXT,
        cancel_requested_date TEXT,
        FOREIGN KEY (crop_id) REFERENCES crops(id) ON DELETE RESTRICT
    )
    """)
    
    cur.execute("PRAGMA table_info(marketplace)")
    marketplace_columns = [row[1] for row in cur.fetchall()]
    if 'buyer_username' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_username TEXT")
    if 'order_status' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN order_status TEXT DEFAULT 'available'")
    if 'order_date' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN order_date TEXT")
    if 'delivery_date' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN delivery_date TEXT")
    if 'delivery_confirmed' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN delivery_confirmed INTEGER DEFAULT 0")
    # New column: buyer must confirm receipt before rating is allowed
    if 'buyer_confirmed' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_confirmed INTEGER DEFAULT 0")
    if 'buyer_confirm_date' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_confirm_date TEXT")
    if 'buyer_rating' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_rating INTEGER DEFAULT NULL")
    if 'buyer_rating_date' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_rating_date TEXT")
    marketplace_compatibility_columns = {
        'main_image': 'TEXT',
        'thumbnail_verified': 'INTEGER NOT NULL DEFAULT 0',
        'thumbnail_latitude': 'REAL',
        'thumbnail_longitude': 'REAL',
        'thumbnail_distance_meters': 'REAL',
        'thumbnail_captured_at': 'TEXT',
        'delivery_province': 'TEXT',
        'delivery_city': 'TEXT',
        'delivery_barangay': 'TEXT',
        'delivery_street': 'TEXT',
        'delivery_landmark': 'TEXT',
        'listing_type': "TEXT DEFAULT 'standard'",
        'available_date': 'TEXT',
        'preorder_status': 'TEXT',
        'preorder_quantity': 'INTEGER',
        'cancel_requested_by': 'TEXT',
        'cancel_reason': 'TEXT',
        'cancel_requested_date': 'TEXT',
    }
    for column, definition in marketplace_compatibility_columns.items():
        if column not in marketplace_columns:
            cur.execute(f"ALTER TABLE marketplace ADD COLUMN {column} {definition}")
    cur.execute("UPDATE marketplace SET main_image=NULL WHERE thumbnail_verified=0")

    cur.execute("PRAGMA table_info(users)")
    users_columns = [row[1] for row in cur.fetchall()]
    # Keep databases created before the expanded account model compatible with
    # the profile-management pages.
    profile_columns = {
        'email': 'TEXT',
        'first_name': 'TEXT',
        'last_name': 'TEXT',
        'is_active': 'BOOLEAN NOT NULL DEFAULT TRUE',
        'phone_number': 'TEXT',
        'profile_picture': 'TEXT',
        'bio': 'TEXT',
        'is_verified': 'INTEGER DEFAULT 0',
        'location_latitude': 'REAL',
        'location_longitude': 'REAL',
        'location_verified': 'INTEGER NOT NULL DEFAULT 0',
        'location_verified_at': 'DATETIME',
        'profile_photo_captured_at': 'DATETIME',
        'psgc_location': 'TEXT',
        'geotag_location': 'TEXT',
        'created_at': 'TEXT',
        'updated_at': 'TEXT',
    }
    for column, definition in profile_columns.items():
        if column not in users_columns:
            cur.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    if 'reliability_score' not in users_columns:
        cur.execute("ALTER TABLE users ADD COLUMN reliability_score REAL DEFAULT NULL")
    if 'reliability_status' not in users_columns:
        cur.execute("ALTER TABLE users ADD COLUMN reliability_status TEXT DEFAULT 'Not Yet Rated'")
    if 'completed_transactions' not in users_columns:
        cur.execute("ALTER TABLE users ADD COLUMN completed_transactions INTEGER DEFAULT 0")
    if 'cancelled_transactions' not in users_columns:
        cur.execute("ALTER TABLE users ADD COLUMN cancelled_transactions INTEGER DEFAULT 0")
    if 'total_transactions' not in users_columns:
        cur.execute("ALTER TABLE users ADD COLUMN total_transactions INTEGER DEFAULT 0")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS analytics(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_type TEXT,
        period_value TEXT,
        total_harvest INTEGER,
        top_crop TEXT,
        top_crop_volume INTEGER,
        top_crop_id INTEGER,
        top_location TEXT,
        top_location_volume INTEGER
    )
    """)

    cur.execute("PRAGMA table_info(analytics)")
    analytics_columns = [row[1] for row in cur.fetchall()]
    if 'top_crop' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_crop TEXT")
    if 'top_crop_volume' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_crop_volume INTEGER")
    if 'top_crop_id' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_crop_id INTEGER")

    _migrate_harvest_to_inventory(cur)

    # Create messages table with recipient column
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        recipient TEXT,
        message TEXT,
        timestamp TEXT,
        attachment_url TEXT,
        attachment_type TEXT
    )
    """)
    cur.execute("PRAGMA table_info(messages)")
    message_columns = [row[1] for row in cur.fetchall()]
    if "attachment_url" not in message_columns:
        cur.execute("ALTER TABLE messages ADD COLUMN attachment_url TEXT")
    if "attachment_type" not in message_columns:
        cur.execute("ALTER TABLE messages ADD COLUMN attachment_type TEXT")
    
    # Create notifications table (used by the notifications endpoint)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        title TEXT,
        message TEXT,
        type TEXT,
        created_at TEXT,
        is_read INTEGER DEFAULT 0,
        link TEXT
    )
    """)
    cur.execute("PRAGMA table_info(notifications)")
    notification_columns = [row[1] for row in cur.fetchall()]
    if "link" not in notification_columns:
        cur.execute("ALTER TABLE notifications ADD COLUMN link TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        token TEXT UNIQUE,
        expires_at TEXT,
        created_at TEXT,
        used_at TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        purpose TEXT NOT NULL DEFAULT 'password_reset',
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS slow_query_stats(
        fingerprint TEXT PRIMARY KEY,
        statement TEXT NOT NULL,
        call_count INTEGER NOT NULL DEFAULT 0,
        total_time_ms FLOAT NOT NULL DEFAULT 0,
        max_time_ms FLOAT NOT NULL DEFAULT 0,
        last_seen_at DATETIME NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS profile_reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_username TEXT NOT NULL,
        reported_username TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_by TEXT,
        reviewed_at DATETIME
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS listing_photo_location_alerts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        distance_meters REAL NOT NULL,
        thumbnail_captured_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_by TEXT,
        reviewed_at DATETIME
    )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS ix_listing_photo_alerts_status_created "
        "ON listing_photo_location_alerts(status, created_at)"
    )

    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_categories(
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_name TEXT NOT NULL UNIQUE
    )
    """)
    cur.execute("SELECT COUNT(*) AS count FROM knowledge_categories")
    if cur.fetchone()["count"] == 0:
        default_categories = [
            "Agricultural News",
            "Market Updates",
            "Crop Guides",
            "Farming Tips",
            "Weather Advisory",
            "Government Programs",
            "Pest & Disease Alerts",
            "Technology",
            "Training Videos",
        ]
        for category_name in default_categories:
            cur.execute("INSERT OR IGNORE INTO knowledge_categories(category_name) VALUES (?)", (category_name,))

    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_posts(
        post_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category_id INTEGER,
        author TEXT,
        image TEXT,
        video TEXT,
        status TEXT DEFAULT 'Published',
        is_pinned INTEGER NOT NULL DEFAULT 0,
        views INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME,
        FOREIGN KEY(category_id) REFERENCES knowledge_categories(category_id) ON DELETE SET NULL
    )
    """)
    cur.execute("PRAGMA table_info(knowledge_posts)")
    knowledge_post_columns = [row[1] for row in cur.fetchall()]
    if "is_pinned" not in knowledge_post_columns:
        cur.execute(
            "ALTER TABLE knowledge_posts ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
        )
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_likes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        username TEXT,
        UNIQUE(post_id, username),
        FOREIGN KEY(post_id) REFERENCES knowledge_posts(post_id) ON DELETE CASCADE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_comments(
        comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        username TEXT,
        comment TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(post_id) REFERENCES knowledge_posts(post_id) ON DELETE CASCADE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_replies(
        reply_id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id INTEGER NOT NULL,
        username TEXT,
        reply TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(comment_id) REFERENCES knowledge_comments(comment_id) ON DELETE CASCADE
    )
    """)
    
    # Migration: Add recipient column if it doesn't exist (for existing databases)
    try:
        cur.execute("SELECT recipient FROM messages LIMIT 1")
    except SQLAlchemyError:
        # Column doesn't exist, need to migrate
        logger.info("Migrating messages table to add recipient column")
        cur.execute("ALTER TABLE messages ADD COLUMN recipient TEXT")
        # For existing messages, set recipient to a default value or handle appropriately
        # For now, we'll leave existing messages without recipient (they were broadcast messages)

    # Ensure location column exists in inventory
    cur.execute("PRAGMA table_info(inventory)")
    inv_columns = [row[1] for row in cur.fetchall()]
    if 'location' not in inv_columns:
        logger.info("Migrating inventory table to add location column")
        cur.execute("ALTER TABLE inventory ADD COLUMN location TEXT")
    if 'source' not in inv_columns:
        logger.info("Migrating inventory table to add source column")
        cur.execute("ALTER TABLE inventory ADD COLUMN source TEXT DEFAULT 'harvest'")
        cur.execute("UPDATE inventory SET source = 'harvest' WHERE source IS NULL")

    _create_query_indexes(cur)

    cur.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1")
    if not cur.fetchone():
        bootstrap_username = str(current_app.config.get("INITIAL_ADMIN_USERNAME", "")).strip()
        bootstrap_password = current_app.config.get("INITIAL_ADMIN_PASSWORD", "")
        bootstrap_password_error = password_policy_error(
            bootstrap_password,
            (bootstrap_username,),
        ) if bootstrap_password else None
        if bootstrap_username and len(bootstrap_username) <= 128 and not bootstrap_password_error:
            cur.execute(
                "INSERT INTO users(username,password,role) VALUES (?,?,?)",
                (bootstrap_username, generate_password_hash(bootstrap_password), "admin"),
            )
        elif bootstrap_username and bootstrap_password and bootstrap_password_error:
            conn.close()
            raise RuntimeError(
                f"INITIAL_ADMIN_PASSWORD does not meet the password policy: "
                f"{bootstrap_password_error}"
            )
        elif current_app.config.get("APP_ENV") == "production":
            conn.close()
            raise RuntimeError(
                "No administrator exists. Set INITIAL_ADMIN_USERNAME and "
                "INITIAL_ADMIN_PASSWORD for the initial production bootstrap."
            )

    update_analytics()

    conn.commit()

    conn.close()


def _create_query_indexes(cur):
    """Create indexes for frequently filtered, joined, and ordered columns."""
    index_definitions = (
        ("ix_users_email", "users", ("email",)),
        ("ix_users_lower_email", "users", ("email",), "LOWER(email)"),
        ("ix_marketplace_status_listing_date", "marketplace", ("status", "listing_date")),
        ("ix_marketplace_user_status_listing_date", "marketplace", ("user_id", "status", "listing_date")),
        ("ix_marketplace_buyer_status_order_date", "marketplace", ("buyer_username", "status", "order_date")),
        ("ix_marketplace_username_rating", "marketplace", ("username", "buyer_rating")),
        ("ix_marketplace_status_type_listing_date", "marketplace", ("status", "listing_type", "listing_date")),
        ("ix_inventory_farmer_crop_date", "inventory", ("farmer", "crop_id", "date_received")),
        ("ix_inventory_crop_date", "inventory", ("crop_id", "date_received")),
        ("ix_inventory_source_date", "inventory", ("source", "date_received")),
        ("ix_knowledge_posts_status_pin_created", "knowledge_posts", ("status", "is_pinned", "created_at")),
        ("ix_knowledge_posts_category_status_created", "knowledge_posts", ("category_id", "status", "created_at")),
        ("ix_knowledge_comments_post_created", "knowledge_comments", ("post_id", "created_at")),
        ("ix_knowledge_replies_comment_created", "knowledge_replies", ("comment_id", "created_at")),
        ("ix_notifications_username_read_created", "notifications", ("username", "is_read", "created_at")),
        ("ix_messages_sender_recipient_time", "messages", ("sender", "recipient", "timestamp")),
        ("ix_messages_recipient_sender_time", "messages", ("recipient", "sender", "timestamp")),
        ("ix_password_reset_user_used_expiry", "password_reset_tokens", ("user_id", "used_at", "expires_at")),
        ("ix_marketplace_images_listing", "marketplace_images", ("listing_id",)),
        ("ix_cart_user_listing", "cart", ("user_id", "listing_id")),
        ("ix_analytics_period_type_value", "analytics", ("period_type", "period_value")),
    )
    for definition in index_definitions:
        index_name, table_name, columns = definition[:3]
        expression = definition[3] if len(definition) == 4 else None
        cur.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row["name"] for row in cur.fetchall()}
        if not set(columns).issubset(existing_columns):
            continue
        indexed_columns = expression or ", ".join(columns)
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({indexed_columns})"
        )


def update_analytics():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS analytics(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_type TEXT,
        period_value TEXT,
        total_harvest INTEGER,
        top_crop TEXT,
        top_crop_volume INTEGER,
        top_crop_id INTEGER,
        top_location TEXT,
        top_location_volume INTEGER
    )
    """)

    cur.execute("PRAGMA table_info(analytics)")
    analytics_columns = [row[1] for row in cur.fetchall()]
    if 'top_crop' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_crop TEXT")
    if 'top_crop_volume' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_crop_volume INTEGER")
    if 'top_crop_id' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_crop_id INTEGER")
    if 'top_location' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_location TEXT")
    if 'top_location_volume' not in analytics_columns:
        cur.execute("ALTER TABLE analytics ADD COLUMN top_location_volume INTEGER")

    def _upsert_analytics_period(cur, period_type, period_value, total_harvest, crop_name, crop_volume, crop_id, location_name, location_volume):
        cur.execute("""
        SELECT id FROM analytics
        WHERE period_type = ?
          AND period_value = ?
        LIMIT 1
        """, (period_type, period_value))
        existing_row = cur.fetchone()

        if existing_row:
            if total_harvest == 0 and crop_name is None and location_name is None:
                return

            cur.execute("""
            UPDATE analytics
            SET total_harvest = ?,
                top_crop = ?,
                top_crop_volume = ?,
                top_crop_id = ?,
                top_location = ?,
                top_location_volume = ?
            WHERE id = ?
            """, (
                total_harvest,
                crop_name,
                crop_volume,
                crop_id,
                location_name,
                location_volume,
                existing_row[0]
            ))
        else:
            cur.execute("""
            INSERT INTO analytics(
                period_type,
                period_value,
                total_harvest,
                top_crop,
                top_crop_volume,
                top_crop_id,
                top_location,
                top_location_volume
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                period_type,
                period_value,
                total_harvest,
                crop_name,
                crop_volume,
                crop_id,
                location_name,
                location_volume
            ))

    cur.execute("""
    SELECT DISTINCT strftime('%Y-%m', date_received) AS period_value
    FROM inventory
    WHERE date_received IS NOT NULL
      AND strftime('%Y-%m', date_received) IS NOT NULL
    ORDER BY period_value
    """)
    month_values = [row[0] for row in cur.fetchall() if row[0]]

    cur.execute("""
    SELECT DISTINCT period_value
    FROM analytics
    WHERE period_type = ?
      AND period_value IS NOT NULL
    ORDER BY period_value
    """, ("Monthly",))
    existing_months = [row[0] for row in cur.fetchall() if row[0]]

    cur.execute("""
    SELECT DISTINCT strftime('%Y', date_received) AS period_value
    FROM inventory
    WHERE date_received IS NOT NULL
      AND strftime('%Y', date_received) IS NOT NULL
    ORDER BY period_value
    """)
    year_values = [row[0] for row in cur.fetchall() if row[0]]

    cur.execute("""
    SELECT DISTINCT period_value
    FROM analytics
    WHERE period_type = ?
      AND period_value IS NOT NULL
    ORDER BY period_value
    """, ("Yearly",))
    existing_years = [row[0] for row in cur.fetchall() if row[0]]

    month_values = sorted(set(month_values + existing_months))
    year_values = sorted(set(year_values + existing_years))

    if not month_values:
        month_values = [datetime.now().strftime('%Y-%m')]
    if not year_values:
        year_values = [datetime.now().strftime('%Y')]

    for period_value in month_values:
        cur.execute("""
        SELECT COALESCE(SUM(quantity), 0)
        FROM inventory
        WHERE strftime('%Y-%m', date_received) = ?
        """, (period_value,))
        total_harvest = cur.fetchone()[0]

        cur.execute("""
        SELECT c.crops_name, SUM(i.quantity) AS total, i.crop_id
        FROM inventory i
        JOIN crops c ON c.id = i.crop_id
        WHERE SUBSTRING(i.date_received FROM 1 FOR 7) = ?
        GROUP BY i.crop_id, c.crops_name
        ORDER BY total DESC
        LIMIT 1
        """, (period_value,))
        top_crop = cur.fetchone()
        if top_crop:
            crop_name = top_crop[0]
            crop_volume = top_crop[1]
            crop_id = top_crop[2]
        else:
            crop_name = None
            crop_volume = 0
            crop_id = None

        cur.execute("""
        SELECT location, SUM(quantity) as total
        FROM inventory
        WHERE strftime('%Y-%m', date_received) = ?
        GROUP BY location
        ORDER BY total DESC
        LIMIT 1
        """, (period_value,))
        top_location = cur.fetchone()
        if top_location:
            location_name = top_location[0]
            location_volume = top_location[1]
        else:
            location_name = None
            location_volume = 0

        _upsert_analytics_period(
            cur,
            "Monthly",
            period_value,
            total_harvest,
            crop_name,
            crop_volume,
            crop_id,
            location_name,
            location_volume,
        )

    for period_value in year_values:
        cur.execute("""
        SELECT COALESCE(SUM(quantity), 0)
        FROM inventory
        WHERE strftime('%Y', date_received) = ?
        """, (period_value,))
        total_harvest = cur.fetchone()[0]

        cur.execute("""
        SELECT c.crops_name, SUM(i.quantity) AS total, i.crop_id
        FROM inventory i
        JOIN crops c ON c.id = i.crop_id
        WHERE SUBSTRING(i.date_received FROM 1 FOR 4) = ?
        GROUP BY i.crop_id, c.crops_name
        ORDER BY total DESC
        LIMIT 1
        """, (period_value,))
        top_crop = cur.fetchone()
        if top_crop:
            crop_name = top_crop[0]
            crop_volume = top_crop[1]
            crop_id = top_crop[2]
        else:
            crop_name = None
            crop_volume = 0
            crop_id = None

        cur.execute("""
        SELECT location, SUM(quantity) as total
        FROM inventory
        WHERE strftime('%Y', date_received) = ?
        GROUP BY location
        ORDER BY total DESC
        LIMIT 1
        """, (period_value,))
        top_location = cur.fetchone()
        if top_location:
            location_name = top_location[0]
            location_volume = top_location[1]
        else:
            location_name = None
            location_volume = 0

        _upsert_analytics_period(
            cur,
            "Yearly",
            period_value,
            total_harvest,
            crop_name,
            crop_volume,
            crop_id,
            location_name,
            location_volume,
        )

    conn.commit()
    conn.close()

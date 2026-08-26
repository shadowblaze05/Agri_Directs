"""Flask-SQLAlchemy database compatibility and schema helpers.

The application historically exposed a DB-API-like ``get_db`` function. This
module preserves that interface while keeping PostgreSQL translation and schema
management out of HTTP route modules.
"""

import logging
import os
import re
from collections import defaultdict
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from ..extensions import db
from ..algorithms.market_analysis import build_market_analysis

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logger = logging.getLogger(__name__)

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
        translated_sql, pragma_params = self._translate_sql(sql)
        effective_params = pragma_params if pragma_params is not None else params
        translated_sql, named_params = self._named_parameters(translated_sql, effective_params)
        self._result = db.session.execute(text(translated_sql), named_params)
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


def _compat_row(row):
    if row is None:
        return None
    return CompatRow(row._mapping)


class SQLAlchemyConnection:
    """Connection-shaped facade backed by Flask-SQLAlchemy's scoped session."""

    def cursor(self):
        return PostgreSQLCursor()

    def commit(self):
        db.session.commit()

    def close(self):
        db.session.remove()


def _save_upload_file(uploaded_file, subfolder):
    if not uploaded_file or uploaded_file.filename == "":
        return None

    upload_dir = os.path.join(BASE_DIR, "static", "uploads", "knowledge", subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(uploaded_file.filename)
    if not filename:
        return None

    file_path = os.path.join(upload_dir, filename)
    uploaded_file.save(file_path)
    return f"/static/uploads/knowledge/{subfolder}/{filename}"


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
        crop_name = None
        if row["crop_id"] is not None:
            crop_row = cur.execute("SELECT crops_name FROM crops WHERE id=?", (row["crop_id"],)).fetchone()
            if crop_row:
                crop_name = crop_row["crops_name"]

        if not crop_name:
            continue

        existing = cur.execute(
            "SELECT id FROM inventory WHERE crop_name=? AND quantity=? AND farmer=? AND date_received=? AND COALESCE(location, '')=COALESCE(?, '')",
            (crop_name, row["quantity"], row["farmer"], row["date_received"], row["location"])
        ).fetchone()
        if existing:
            continue

        cur.execute(
            "INSERT INTO inventory(crop_name, quantity, farmer, date_received, location) VALUES (?, ?, ?, ?, ?)",
            (crop_name, row["quantity"], row["farmer"], row["date_received"], row["location"])
        )

    if harvest_rows and not inventory_exists:
        logger.info("Backfilled dashboard inventory from legacy harvest records")


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'user',
        location TEXT,
        reliability_score REAL DEFAULT NULL,
        reliability_status TEXT DEFAULT 'Not Yet Rated',
        completed_transactions INTEGER DEFAULT 0,
        cancelled_transactions INTEGER DEFAULT 0,
        total_transactions INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        crop_name TEXT,
        quantity INTEGER,
        farmer TEXT,
        date_received TEXT,
        location TEXT
    )
    """)

    # Create referenced domain tables before PostgreSQL validates foreign keys.
    _seed_default_crops(cur)

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
        expiry_date TEXT,
        description TEXT,
        location TEXT,
        delivery_confirmed INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (crop_id) REFERENCES crops(id)
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

    cur.execute("PRAGMA table_info(users)")
    users_columns = [row[1] for row in cur.fetchall()]
    # Keep databases created before the expanded account model compatible with
    # the profile-management pages.
    profile_columns = {
        'email': 'TEXT',
        'first_name': 'TEXT',
        'last_name': 'TEXT',
        'phone_number': 'TEXT',
        'profile_picture': 'TEXT',
        'bio': 'TEXT',
        'is_verified': 'INTEGER DEFAULT 0',
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
        timestamp TEXT
    )
    """)
    
    # Create notifications table (used by the notifications endpoint)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        title TEXT,
        message TEXT,
        type TEXT,
        created_at TEXT,
        is_read INTEGER DEFAULT 0
    )
    """)

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
        views INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME,
        FOREIGN KEY(category_id) REFERENCES knowledge_categories(category_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_likes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER,
        username TEXT,
        UNIQUE(post_id, username)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_comments(
        comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER,
        username TEXT,
        comment TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_replies(
        reply_id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id INTEGER,
        username TEXT,
        reply TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

    # Insert default user if not exists
    cur.execute("SELECT * FROM users WHERE username=?", ("admin",))
    if not cur.fetchone():
        cur.execute("INSERT INTO users(username,password,role) VALUES (?,?,?)",
                    ("admin", generate_password_hash("admin"), 'admin'))

    update_analytics()

    conn.commit()

    conn.close()

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
        SELECT crop_name, SUM(quantity) as total
        FROM inventory
        WHERE strftime('%Y-%m', date_received) = ?
        GROUP BY crop_name
        ORDER BY total DESC
        LIMIT 1
        """, (period_value,))
        top_crop = cur.fetchone()
        if top_crop:
            crop_name = top_crop[0]
            crop_volume = top_crop[1]
            crop_row = cur.execute("SELECT id FROM crops WHERE crops_name=?", (crop_name,)).fetchone()
            crop_id = crop_row[0] if crop_row else None
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
        SELECT crop_name, SUM(quantity) as total
        FROM inventory
        WHERE strftime('%Y', date_received) = ?
        GROUP BY crop_name
        ORDER BY total DESC
        LIMIT 1
        """, (period_value,))
        top_crop = cur.fetchone()
        if top_crop:
            crop_name = top_crop[0]
            crop_volume = top_crop[1]
            crop_row = cur.execute("SELECT id FROM crops WHERE crops_name=?", (crop_name,)).fetchone()
            crop_id = crop_row[0] if crop_row else None
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

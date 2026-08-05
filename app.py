from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import csv
import os
import logging
import calendar
from datetime import datetime, timedelta
from collections import defaultdict
import requests
import jwt
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "agridirect_secret")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

API_KEY = os.environ.get("API_KEY", "mysecurekey123")
JWT_SECRET = os.environ.get("JWT_SECRET", "jwt_secret_key_agridirect")

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_inventory_datetime(value):
    """Parse stored inventory timestamps in a tolerant way."""
    if not value:
        return datetime.now()

    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d")
        except ValueError:
            return datetime.now()


def _linear_forecast(values):
    """Return a simple linear forecast for the next period."""
    if not values:
        return 0
    if len(values) < 2:
        return max(0, int(values[-1]))

    x_values = list(range(len(values)))
    mean_x = sum(x_values) / len(x_values)
    mean_y = sum(values) / len(values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, values))
    denominator = sum((x - mean_x) ** 2 for x in x_values)
    slope = numerator / denominator if denominator else 0
    intercept = mean_y - slope * mean_x
    forecast = intercept + slope * len(values)
    return max(0, int(round(forecast)))


def build_market_analysis(records):
    """Generate decision-support insights from inventory history."""
    if not records:
        return {
            "summary": {
                "total_quantity": 0,
                "active_crops": 0,
                "average_monthly_supply": 0,
                "market_pressure": "balanced",
                "current_month": datetime.now().strftime("%B")
            },
            "price_monitoring": [],
            "risk_alerts": [],
            "recommendations": [],
            "forecast": []
        }

    crop_totals = defaultdict(int)
    monthly_totals = defaultdict(int)
    crop_history = defaultdict(list)
    season_map = {
        "rice": [5, 6, 7, 8, 9, 10],
        "corn": [4, 5, 6, 7, 8],
        "banana": [1, 2, 3, 4, 5, 6],
        "mango": [3, 4, 5, 6, 7],
        "cabbage": [8, 9, 10, 11, 12],
        "eggplant": [4, 5, 6, 7, 8],
        "tomato": [1, 2, 3, 4, 5, 6],
        "cassava": [1, 2, 3, 4, 5, 6],
        "sugarcane": [7, 8, 9, 10, 11],
        "pepper": [5, 6, 7, 8, 9]
    }

    for row in records:
        crop_name = str(row["crop_name"] or "").strip()
        quantity = int(row["quantity"] or 0)
        if not crop_name or quantity <= 0:
            continue

        crop_totals[crop_name] += quantity
        month_key = _parse_inventory_datetime(row.get("date_received")).strftime("%Y-%m")
        monthly_totals[month_key] += quantity
        crop_history[crop_name].append((month_key, quantity))

    if not crop_totals:
        return {
            "summary": {
                "total_quantity": 0,
                "active_crops": 0,
                "average_monthly_supply": 0,
                "market_pressure": "balanced",
                "current_month": datetime.now().strftime("%B")
            },
            "price_monitoring": [],
            "risk_alerts": [],
            "recommendations": [],
            "forecast": []
        }

    month_values = list(monthly_totals.values())
    average_monthly_supply = round(sum(month_values) / len(month_values), 2) if month_values else 0
    current_month_name = datetime.now().strftime("%B")

    price_monitoring = []
    risk_alerts = []
    forecast = []

    for crop_name, total_quantity in sorted(crop_totals.items()):
        history_entries = sorted(crop_history.get(crop_name, []), key=lambda item: item[0])
        monthly_series = [value for _, value in history_entries]
        average_supply = sum(monthly_series) / len(monthly_series) if monthly_series else total_quantity
        supply_pressure = total_quantity / max(average_supply, 1)
        trend_change = 0
        if len(monthly_series) >= 2:
            trend_change = (monthly_series[-1] - monthly_series[-2]) / max(monthly_series[-2], 1)

        price_index = round(100 + (supply_pressure * 8) + (trend_change * 25) - 10)
        price_index = max(60, min(180, price_index))

        demand_score = min(1.0, supply_pressure / 1.5)
        seasonal_score = 1.0 if (datetime.now().month in season_map.get(crop_name.lower(), [])) else 0.7
        recommendation_score = round((demand_score * 0.45) + ((price_index - 80) / 100 * 0.35) + (seasonal_score * 0.2), 2)

        price_monitoring.append({
            "crop": crop_name,
            "current_supply": total_quantity,
            "average_supply": round(average_supply, 2),
            "price_index": price_index,
            "trend": "upward" if trend_change > 0 else "downward" if trend_change < 0 else "stable",
            "demand_signal": "strong" if demand_score >= 0.7 else "moderate" if demand_score >= 0.4 else "weak",
            "recommendation_score": recommendation_score
        })

        if supply_pressure >= 1.35:
            risk_alerts.append({
                "crop": crop_name,
                "type": "Oversupply risk",
                "message": f"Current supply for {crop_name} is {round(supply_pressure * 100)}% above the recent average.",
                "severity": "high"
            })
        elif supply_pressure <= 0.75:
            risk_alerts.append({
                "crop": crop_name,
                "type": "Undersupply risk",
                "message": f"Current supply for {crop_name} is {round((1 - supply_pressure) * 100)}% below the recent average.",
                "severity": "medium"
            })

        forecast.append({
            "crop": crop_name,
            "forecast_quantity": _linear_forecast(monthly_series),
            "trend": "increasing" if (monthly_series[-1] if monthly_series else 0) >= (monthly_series[-2] if len(monthly_series) > 1 else 0) else "decreasing",
            "recommendation_score": recommendation_score,
            "seasonal_fit": "favorable" if seasonal_score >= 0.9 else "neutral"
        })

    recommendations = sorted(
        [
            {
                "crop": item["crop"],
                "score": item["recommendation_score"],
                "reason": f"Demand signal is {item['demand_signal']} with a price index of {item['price_index']}"
            }
            for item in price_monitoring
        ],
        key=lambda item: item["score"],
        reverse=True
    )[:3]

    market_pressure = "balanced"
    if any(alert["type"] == "Oversupply risk" for alert in risk_alerts):
        market_pressure = "oversupply"
    if any(alert["type"] == "Undersupply risk" for alert in risk_alerts):
        market_pressure = "undersupply"

    return {
        "summary": {
            "total_quantity": sum(crop_totals.values()),
            "active_crops": len(crop_totals),
            "average_monthly_supply": average_monthly_supply,
            "market_pressure": market_pressure,
            "current_month": current_month_name
        },
        "price_monitoring": price_monitoring,
        "risk_alerts": risk_alerts,
        "recommendations": recommendations,
        "forecast": sorted(forecast, key=lambda item: item["forecast_quantity"], reverse=True)
    }


def geocode_location(location):
    """Geocode a location string to lat/lng using Google Maps API or a fallback."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        # fallback coordinates if no API key is configured
        lat = 14.5995 + (hash(location) % 100 - 50) / 100.0
        lng = 120.9842 + (hash(location + 'salt') % 100 - 50) / 100.0
        return lat, lng

    try:
        if location and not location.lower().endswith('philippines'):
            location_query = f"{location}, Philippines"
        else:
            location_query = location

        if api_key:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(location_query)}&key={api_key}"
            response = requests.get(url, timeout=5)
            data = response.json()
            if data.get('status') == 'OK' and data.get('results'):
                loc = data['results'][0]['geometry']['location']
                return loc['lat'], loc['lng']
        else:
            nominatim_url = "https://nominatim.openstreetmap.org/search"
            response = requests.get(
                nominatim_url,
                params={"q": location_query, "format": "json", "limit": 1},
                headers={"User-Agent": "Agri-Direct/1.0"},
                timeout=5
            )
            if response.ok:
                results = response.json()
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        logger.warning(f"Geocode lookup failed for '{location}': {e}")

    if not location:
        return 14.5995, 120.9842

    lat = 14.5995 + (hash(location) % 100 - 50) / 100.0
    lng = 120.9842 + (hash(location + 'salt') % 100 - 50) / 100.0
    return lat, lng


# ============= JWT FUNCTIONS =============

def generate_jwt_token(username):
    """Generate JWT token for API authentication"""
    try:
        payload = {
            "user": username,
            "exp": datetime.utcnow() + timedelta(hours=24),
            "iat": datetime.utcnow()
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return token
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        return None


def verify_jwt_token(token):
    """Verify JWT token and return username if valid"""
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("user")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """Decorator to protect API endpoints with JWT"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Missing authorization token"}), 401
        
        username = verify_jwt_token(token)
        if not username:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        return f(*args, **kwargs)
    return decorated


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        conn.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.OperationalError:
        pass
    return conn


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
    if 'buyer_rating' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_rating INTEGER DEFAULT NULL")
    if 'buyer_rating_date' not in marketplace_columns:
        cur.execute("ALTER TABLE marketplace ADD COLUMN buyer_rating_date TEXT")

    cur.execute("PRAGMA table_info(users)")
    users_columns = [row[1] for row in cur.fetchall()]
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

    _seed_default_crops(cur)
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
    except sqlite3.OperationalError:
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

@app.route("/")
def home():
    if "user" in session:
        return redirect("/dashboard")
    return redirect("/login")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()

        if user:
            if check_password_hash(user["password"], password):
                session["user"] = username
                session["role"] = user["role"] if user["role"] else 'buyer'
                logger.info(f"User {username} logged in")
                return redirect("/dashboard")
            else:
                logger.warning(f"Invalid password for {username}")
        else:
            logger.warning(f"User {username} not found")

        flash("Invalid username or password")

    return render_template("login.html")


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET","POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        # New registrations are simple users by default
        role = "user"

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute("INSERT INTO users(username,password,role) VALUES (?,?,?)",
                        (username,password,role))
            conn.commit()
            logger.info(f"User {username} registered with role {role}")
            flash("Registration successful! Please login.")
            return redirect("/login")
        except sqlite3.IntegrityError:
            flash("Username already exists")
            logger.warning(f"Registration failed: username {username} already exists")
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (session["user"],))
    user = cur.fetchone()

    if request.method == "POST":
        location = request.form.get("location", "").strip()
        cur.execute("UPDATE users SET location=? WHERE username=?", (location, session["user"]))
        conn.commit()
        flash("Profile updated successfully")
        return redirect("/profile")

    # Always show inventory items that belong to the logged-in user
    inventory = []
    cur.execute(
        "SELECT crop_name, SUM(quantity) as total_quantity, MAX(date_received) as last_received "
        "FROM inventory WHERE farmer=? GROUP BY crop_name ORDER BY last_received DESC",
        (session["user"],)
    )
    inventory = cur.fetchall()

    conn.close()
    return render_template("profile.html", user=user, inventory=inventory)


@app.route("/inventory/buy", methods=["POST"])
def inventory_buy():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    # Allow any logged-in user to manage their own posted inventory

    data = request.get_json() or {}
    crop_name = str(data.get("crop_name", "")).strip()
    quantity = data.get("quantity")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a valid number"}), 400

    if not crop_name:
        return jsonify({"error": "Crop name is required"}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than zero"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(quantity) AS total FROM inventory WHERE farmer=? AND crop_name=?", (session["user"], crop_name))
    row = cur.fetchone()
    total = row["total"] or 0

    if quantity > total:
        conn.close()
        return jsonify({"error": "Buy quantity exceeds available inventory"}), 400

    needed = quantity
    cur.execute(
        "SELECT id, quantity FROM inventory WHERE farmer=? AND crop_name=? ORDER BY date_received DESC",
        (session["user"], crop_name)
    )
    rows = cur.fetchall()

    for item in rows:
        if needed <= 0:
            break
        item_qty = item["quantity"]
        if item_qty <= needed:
            cur.execute("DELETE FROM inventory WHERE id=?", (item["id"],))
            needed -= item_qty
        else:
            cur.execute("UPDATE inventory SET quantity=? WHERE id=?", (item_qty - needed, item["id"]))
            needed = 0

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Inventory updated after purchase"})


@app.route("/inventory/edit_crop", methods=["POST"])
def inventory_edit_crop():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    # Allow any logged-in user to edit their own posted inventory

    data = request.get_json() or {}
    crop_name = str(data.get("crop_name", "")).strip()
    quantity = data.get("quantity")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a valid number"}), 400

    if not crop_name:
        return jsonify({"error": "Crop name is required"}), 400
    if quantity < 0:
        return jsonify({"error": "Quantity cannot be negative"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(quantity) AS total FROM inventory WHERE farmer=? AND crop_name=?", (session["user"], crop_name))
    row = cur.fetchone()
    current_total = row["total"] or 0

    if quantity == current_total:
        conn.close()
        return jsonify({"status": "success", "message": "Inventory unchanged"})

    if quantity > current_total:
        add_amount = quantity - current_total
        cur.execute("SELECT location FROM users WHERE username=?", (session["user"],))
        user_loc = cur.fetchone()["location"]
        cur.execute(
            "INSERT INTO inventory(crop_name,quantity,farmer,date_received,location) VALUES(?,?,?,?,?)",
            (crop_name, add_amount, session["user"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_loc)
        )
    else:
        remove_amount = current_total - quantity
        cur.execute(
            "SELECT id, quantity FROM inventory WHERE farmer=? AND crop_name=? ORDER BY date_received DESC",
            (session["user"], crop_name)
        )
        rows = cur.fetchall()
        needed = remove_amount
        for item in rows:
            if needed <= 0:
                break
            item_qty = item["quantity"]
            if item_qty <= needed:
                cur.execute("DELETE FROM inventory WHERE id=?", (item["id"],))
                needed -= item_qty
            else:
                cur.execute("UPDATE inventory SET quantity=? WHERE id=?", (item_qty - needed, item["id"]))
                needed = 0

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Inventory adjusted successfully"})


@app.route("/inventory/delete_crop", methods=["POST"])
def inventory_delete_crop():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    # Allow any logged-in user to delete their own posted inventory

    data = request.get_json() or {}
    crop_name = str(data.get("crop_name", "")).strip()

    if not crop_name:
        return jsonify({"error": "Crop name is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory WHERE farmer=? AND crop_name=?", (session["user"], crop_name))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Crop inventory deleted"})


@app.route("/admin/knowledge")
def admin_knowledge():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT kp.post_id, kp.title, kp.status, kp.created_at, kp.views, kc.category_name, kp.author
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        ORDER BY kp.created_at DESC
    """)
    posts = cur.fetchall()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    cur.execute("SELECT COUNT(*) AS total_posts FROM knowledge_posts")
    total_posts = cur.fetchone()["total_posts"]
    cur.execute("SELECT COUNT(*) AS published_posts FROM knowledge_posts WHERE status = 'Published'")
    published_posts = cur.fetchone()["published_posts"]
    cur.execute("SELECT COUNT(*) AS draft_posts FROM knowledge_posts WHERE status = 'Draft'")
    draft_posts = cur.fetchone()["draft_posts"]
    conn.close()
    return render_template(
        "admin_knowledge.html",
        posts=posts,
        categories=categories,
        total_posts=total_posts,
        published_posts=published_posts,
        draft_posts=draft_posts,
    )


@app.route("/admin/knowledge/create", methods=["GET", "POST"])
def create_knowledge_post():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    conn.close()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id") or None
        status = request.form.get("status", "Published")
        if not title or not content:
            flash("Title and content are required")
            return render_template("create_post.html", categories=categories)

        image_path = _save_upload_file(request.files.get("image"), "images")
        video_path = _save_upload_file(request.files.get("video"), "videos")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_posts (title, content, category_id, author, image, video, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, content, category_id, session.get("user"), image_path, video_path, status),
        )
        conn.commit()
        conn.close()
        flash("Article created successfully")
        return redirect("/admin/knowledge")

    return render_template("create_post.html", categories=categories)


@app.route("/admin/knowledge/edit/<int:post_id>", methods=["GET", "POST"])
def edit_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM knowledge_posts WHERE post_id=?", (post_id,))
    post = cur.fetchone()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    conn.close()

    if not post:
        flash("Post not found")
        return redirect("/admin/knowledge")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id") or None
        status = request.form.get("status", "Published")
        if not title or not content:
            flash("Title and content are required")
            return render_template("edit_post.html", post=post, categories=categories)

        image_path = _save_upload_file(request.files.get("image"), "images") or post["image"]
        video_path = _save_upload_file(request.files.get("video"), "videos") or post["video"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_posts
            SET title=?, content=?, category_id=?, image=?, video=?, status=?, updated_at=CURRENT_TIMESTAMP
            WHERE post_id=?
            """,
            (title, content, category_id, image_path, video_path, status, post_id),
        )
        conn.commit()
        conn.close()
        flash("Article updated successfully")
        return redirect("/admin/knowledge")

    return render_template("edit_post.html", post=post, categories=categories)


@app.route("/admin/knowledge/delete/<int:post_id>", methods=["POST"])
def delete_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM knowledge_replies WHERE comment_id IN (SELECT comment_id FROM knowledge_comments WHERE post_id=?)", (post_id,))
    cur.execute("DELETE FROM knowledge_comments WHERE post_id=?", (post_id,))
    cur.execute("DELETE FROM knowledge_likes WHERE post_id=?", (post_id,))
    cur.execute("DELETE FROM knowledge_posts WHERE post_id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("Article deleted successfully")
    return redirect("/admin/knowledge")


@app.route("/knowledge")
def knowledge_feed():
    if "user" not in session:
        return redirect("/login")

    query = request.args.get("q", "").strip()
    category_id = request.args.get("category_id", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()

    sql = """
        SELECT kp.post_id, kp.title, kp.content, kp.image, kp.video, kp.status, kp.views, kp.created_at,
               kp.author, kc.category_name, kc.category_id,
               (SELECT COUNT(*) FROM knowledge_likes kl WHERE kl.post_id = kp.post_id) AS like_count,
               (SELECT COUNT(*) FROM knowledge_comments kcmt WHERE kcmt.post_id = kp.post_id) AS comment_count
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        WHERE kp.status = 'Published'
    """
    params = []
    if query:
        sql += " AND (kp.title LIKE ? OR kp.content LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if category_id:
        sql += " AND kp.category_id = ?"
        params.append(category_id)
    sql += " ORDER BY kp.created_at DESC"

    posts = cur.execute(sql, params).fetchall()
    conn.close()
    return render_template("knowledge.html", posts=posts, categories=categories, query=query, category_id=category_id)


@app.route("/knowledge/<int:post_id>")
def knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT kp.post_id, kp.title, kp.content, kp.image, kp.video, kp.status, kp.views, kp.created_at,
               kp.author, kp.category_id, kc.category_name,
               (SELECT COUNT(*) FROM knowledge_likes kl WHERE kl.post_id = kp.post_id) AS like_count
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        WHERE kp.post_id = ?
    """, (post_id,))
    post = cur.fetchone()
    if not post:
        conn.close()
        flash("Article not found")
        return redirect("/knowledge")

    cur.execute("UPDATE knowledge_posts SET views = views + 1 WHERE post_id=?", (post_id,))
    conn.commit()

    cur.execute("SELECT comment_id, username, comment, created_at FROM knowledge_comments WHERE post_id=? ORDER BY created_at ASC", (post_id,))
    comments = cur.fetchall()
    replies = {}
    for comment in comments:
        cur.execute("SELECT reply_id, username, reply, created_at FROM knowledge_replies WHERE comment_id=? ORDER BY created_at ASC", (comment["comment_id"],))
        replies[comment["comment_id"]] = cur.fetchall()

    cur.execute("SELECT COUNT(*) AS liked FROM knowledge_likes WHERE post_id=? AND username=?", (post_id, session.get("user")))
    liked = cur.fetchone()["liked"] > 0
    conn.close()
    return render_template("knowledge_post.html", post=post, comments=comments, replies=replies, liked=liked)


@app.route("/knowledge/like/<int:post_id>", methods=["POST"])
def like_knowledge_post(post_id):
    if "user" not in session:
        return jsonify({"status": "error", "message": "Please log in first"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS liked FROM knowledge_likes WHERE post_id=? AND username=?", (post_id, session.get("user")))
    already_liked = cur.fetchone()["liked"] > 0

    if already_liked:
        cur.execute("DELETE FROM knowledge_likes WHERE post_id=? AND username=?", (post_id, session.get("user")))
        status = "unliked"
    else:
        cur.execute("INSERT INTO knowledge_likes (post_id, username) VALUES (?, ?)", (post_id, session.get("user")))
        status = "liked"

    conn.commit()
    cur.execute("SELECT COUNT(*) AS like_count FROM knowledge_likes WHERE post_id=?", (post_id,))
    like_count = cur.fetchone()["like_count"]
    conn.close()
    return jsonify({"status": status, "like_count": like_count})


@app.route("/knowledge/comment/<int:post_id>", methods=["POST"])
def comment_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")

    comment = request.form.get("comment", "").strip()
    if not comment:
        flash("Comment cannot be empty")
        return redirect(url_for("knowledge_post", post_id=post_id))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO knowledge_comments (post_id, username, comment) VALUES (?, ?, ?)", (post_id, session.get("user"), comment))
    conn.commit()
    conn.close()
    flash("Comment added")
    return redirect(url_for("knowledge_post", post_id=post_id))


@app.route("/knowledge/reply/<int:comment_id>", methods=["POST"])
def reply_to_comment(comment_id):
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Only admins can reply to comments")
        return redirect("/dashboard")

    reply = request.form.get("reply", "").strip()
    if not reply:
        flash("Reply cannot be empty")
        return redirect("/knowledge")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT post_id FROM knowledge_comments WHERE comment_id=?", (comment_id,))
    comment_row = cur.fetchone()
    if comment_row:
        cur.execute("INSERT INTO knowledge_replies (comment_id, username, reply) VALUES (?, ?, ?)", (comment_id, session.get("user"), reply))
        conn.commit()
    conn.close()
    flash("Reply posted")
    return redirect(url_for("knowledge_post", post_id=comment_row["post_id"] if comment_row else 1))


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/admin")
def admin():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory ORDER BY date_received DESC")
    inventory = cur.fetchall()
    cur.execute("SELECT username, role, reliability_status, completed_transactions, cancelled_transactions, total_transactions FROM users ORDER BY role, username")
    users = cur.fetchall()
    conn.close()
    return render_template("admin.html", inventory=inventory, users=users)


@app.route("/inventory/edit/<int:item_id>", methods=["GET", "POST"])
def edit_inventory(item_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory WHERE id=?", (item_id,))
    item = cur.fetchone()

    if not item:
        conn.close()
        flash("Inventory item not found")
        return redirect("/dashboard")

    can_modify = session.get("role") == "admin" or (item["farmer"] == session["user"])
    if not can_modify:
        conn.close()
        flash("You are not allowed to modify this item")
        return redirect("/dashboard")

    if request.method == "POST":
        cropped_name = request.form.get("crop_name", item["crop_name"]).strip()
        quantity = request.form.get("quantity", item["quantity"])

        try:
            quantity = int(quantity)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a positive number")
            conn.close()
            return redirect(request.url)

        cur.execute("UPDATE inventory SET crop_name=?, quantity=? WHERE id=?",
                    (cropped_name, quantity, item_id))
        conn.commit()
        conn.close()
        flash("Inventory item updated successfully")
        return redirect("/dashboard")

    conn.close()
    return render_template("edit_inventory.html", item=item)


@app.route("/inventory/delete/<int:item_id>")
def delete_inventory(item_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        conn.close()
        flash("Inventory item not found")
        return redirect("/dashboard")

    can_modify = session.get("role") == "admin" or (item["farmer"] == session["user"])
    if not can_modify:
        conn.close()
        flash("You are not allowed to delete this item")
        return redirect("/dashboard")

    cur.execute("DELETE FROM inventory WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    flash("Inventory item deleted")
    return redirect("/dashboard")


# ---------------- DASHBOARD ----------------

@app.route("/crop-types")
def crop_types():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT crop_name, SUM(quantity) as total FROM inventory WHERE source IS NULL OR source = 'harvest' GROUP BY crop_name ORDER BY total DESC")
    crops = cur.fetchall()
    crop_types_count = len(crops)
    conn.close()

    return render_template("crop_types.html", crops=crops, crop_types_count=crop_types_count)


@app.route("/market-intelligence")
def market_intelligence():
    if "user" not in session:
        return redirect(url_for("login"))

    summary_cards = [
        {"label": "Market value", "badge": "Stable", "value": "₱1.86M", "detail": "Reflects current trade volume for the period."},
        {"label": "Average price index", "badge": "+6%", "value": "118", "detail": "Demand remains healthy across core crops."},
        {"label": "Active crops", "badge": "High", "value": "8", "detail": "Coverage includes staples and high-value produce."},
        {"label": "Alert level", "badge": "Watch", "value": "Moderate", "detail": "Monitor leafy crops for oversupply pressure."},
    ]

    pulse_items = [
        {"label": "Rice", "value": "High demand", "progress": 82},
        {"label": "Corn", "value": "Balanced", "progress": 64},
        {"label": "Banana", "value": "Watch", "progress": 58},
        {"label": "Tomato", "value": "Risk", "progress": 46},
    ]

    focus_items = [
        {"title": "Seasonal planting window", "badge": "Priority", "detail": "Planting recommendations are strongest for rice and corn this quarter.", "metric": "+12%", "timeline": "Next 2 weeks"},
        {"title": "Buyer interest cluster", "badge": "Momentum", "detail": "Fresh produce demand is strongest in high-growth market zones.", "metric": "+8%", "timeline": "This week"},
    ]

    insight_items = [
        {"title": "Demand resilience", "level": "Positive", "desc": "Demand remains firm for staples despite mild volatility."},
        {"title": "Supply caution", "level": "Watch", "desc": "Leafy produce is nearing the upper comfort band."},
    ]

    return render_template(
        "market_intelligence.html",
        active_page="summary",
        summary_cards=summary_cards,
        price_labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        price_series=[88, 90, 94, 98, 103, 111],
        pulse_items=pulse_items,
        focus_items=focus_items,
        insight_items=insight_items,
    )


@app.route("/market-intelligence/price-monitoring")
def market_intelligence_price_monitoring():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template(
        "market_intelligence_price.html",
        active_page="price",
        price_items=[
            {"crop": "Rice", "current_price": "₱42/kg", "variance": "+4.3%", "trend": "Rising", "signal": "Strong demand"},
            {"crop": "Corn", "current_price": "₱28/kg", "variance": "+1.1%", "trend": "Steady", "signal": "Balanced flow"},
            {"crop": "Banana", "current_price": "₱35/kg", "variance": "-0.8%", "trend": "Cooling", "signal": "Moderate pressure"},
            {"crop": "Tomato", "current_price": "₱60/kg", "variance": "+2.7%", "trend": "Rising", "signal": "Short supply"},
        ],
        detail_items=[
            {"label": "Peak price", "value": "₱60/kg", "note": "Observed in tomato during current cycle."},
            {"label": "Lowest price", "value": "₱28/kg", "note": "Corn remains the most stable reference price."},
            {"label": "Volatility", "value": "Low", "note": "Most commodities stayed within normal range."},
            {"label": "Coverage", "value": "4 crops", "note": "Prototype includes major staples and produce."},
        ],
        trend_labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        trend_series=[40, 42, 44, 47, 49, 52],
    )


@app.route("/market-intelligence/crop-recommendations")
def market_intelligence_crop_recommendations():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template(
        "market_intelligence_recommendations.html",
        active_page="recommendations",
        recommendation_items=[
            {"crop": "Rice", "score": 92, "reason": "High demand and strong market fit", "demand": "High", "seasonal": "Excellent"},
            {"crop": "Corn", "score": 84, "reason": "Balanced pricing with dependable output", "demand": "Balanced", "seasonal": "Good"},
            {"crop": "Banana", "score": 76, "reason": "Stable pulse with broad demand", "demand": "Moderate", "seasonal": "Fair"},
            {"crop": "Tomato", "score": 69, "reason": "Price premium but short supply risk", "demand": "High", "seasonal": "Watch"},
        ],
        recommendation_labels=["Rice", "Corn", "Banana", "Tomato", "Cabbage"],
        recommendation_scores=[92, 84, 76, 69, 61],
    )


@app.route("/market-intelligence/demand-forecasting")
def market_intelligence_demand_forecasting():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template(
        "market_intelligence_forecast.html",
        active_page="forecast",
        forecast_items=[
            {"crop": "Tomato", "note": "Demand is expected to climb steadily", "confidence": "High", "historical": "1.2k", "projected": "1.6k"},
            {"crop": "Rice", "note": "Stable demand reinforces planning confidence", "confidence": "High", "historical": "2.4k", "projected": "2.7k"},
            {"crop": "Corn", "note": "Demand outlook remains consistent", "confidence": "Medium", "historical": "1.0k", "projected": "1.1k"},
        ],
        forecast_labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
        historical_series=[120, 132, 128, 145, 149, 160, 168],
        projected_series=[170, 177, 184, 193, 201, 210, 219],
    )


@app.route("/market-intelligence/supply-balance")
def market_intelligence_supply_balance():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template(
        "market_intelligence_supply.html",
        active_page="supply",
        supply_items=[
            {"crop": "Cabbage", "status": "Oversupply", "note": "Current stock exceeds the comfort range", "band": "Upper", "shift": "+18%"},
            {"crop": "Tomato", "status": "Undersupply", "note": "Supply is tightening around peak demand", "band": "Lower", "shift": "-12%"},
            {"crop": "Rice", "status": "Balanced", "note": "Current positioning remains steady", "band": "Safe", "shift": "+2%"},
        ],
        supply_labels=["Cabbage", "Tomato", "Rice", "Corn"],
        supply_series=[82, 54, 41, 38],
    )


@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM inventory WHERE source IS NULL OR source = 'harvest' ORDER BY date_received DESC LIMIT 20")
    data = cur.fetchall()

    update_analytics()

    cur.execute("""SELECT crop_name, SUM(quantity) as total FROM inventory WHERE source IS NULL OR source = 'harvest' GROUP BY crop_name ORDER BY total DESC""")
    crops = cur.fetchall()

    cur.execute("SELECT location, SUM(quantity) as total FROM inventory WHERE (source IS NULL OR source = 'harvest') AND location IS NOT NULL AND location != '' GROUP BY location ORDER BY total DESC")
    locations = cur.fetchall()
    location_count = len(locations)

    latest_analytics = cur.execute("""
        SELECT total_harvest, top_location, top_location_volume
        FROM analytics
        WHERE period_type = ?
        ORDER BY period_value DESC
        LIMIT 1
    """, ("Monthly",)).fetchone()

    analytics_history = cur.execute("""
        SELECT period_value, total_harvest, top_crop, top_crop_volume, top_location, top_location_volume
        FROM analytics
        WHERE period_type = ?
          AND (top_location NOT IN ('North', 'South') OR top_location IS NULL)
        ORDER BY period_value DESC
        LIMIT 5
    """, ("Monthly",)).fetchall()

    conn.close()

    total = latest_analytics["total_harvest"] if latest_analytics else sum(row['quantity'] for row in data)
    top_location_name = latest_analytics["top_location"] if latest_analytics else None
    top_location_volume = latest_analytics["top_location_volume"] if latest_analytics else 0
    crop_count = len(crops)

    return render_template("dashboard.html",
                       inventory=data,
                       total=total,
                       crops=crops,
                       locations=locations,
                       location_count=location_count,
                       top_location_name=top_location_name,
                       top_location_volume=top_location_volume,
                       crop_count=crop_count,
                       analytics_history=analytics_history)


# ---------------- CSV UPLOAD ----------------

@app.route("/upload", methods=["GET","POST"])
def upload():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role, location FROM users WHERE username=?", (session["user"],))
    user = cur.fetchone()
    role = user[0] if user else 'user'
    location = user[1] if user else None

    if request.method == "POST":
        # Require that the user has a profile location before accepting harvest uploads
        if not location:
            flash("You must set your location in your profile before uploading harvest data.")
            conn.close()
            return redirect(request.url)

        file = request.files.get("file")
        crop_id = request.form.get("crop_id")
        manual_quantity = request.form.get("manual_quantity", "").strip()
        manual_date = request.form.get("manual_date", "").strip()

        processed_any = False

        if file and file.filename:
            if not file.filename.endswith('.csv'):
                flash("Only CSV files are allowed")
                conn.close()
                return redirect(request.url)

            filename = secure_filename(file.filename)
            path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(path)

            try:
                with open(path, newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)

                    for row in reader:
                        try:
                            cleaned_row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
                            crop = cleaned_row.get("crop_name", "").strip()
                            
                            cur.execute(
                                "SELECT id FROM crops WHERE crops_name=?",
                                (crop,)
                            )

                            crop_record = cur.fetchone()

                            if not crop_record:
                                flash(f"Crop '{crop}' not found.")
                                continue

                            crop_id = crop_record[0]
                            
                            quantity_str = cleaned_row.get("quantity", "").strip()

                            if not crop:
                                logger.warning(f"Skipped row with empty crop_name")
                                continue

                            try:
                                quantity = int(quantity_str)
                            except ValueError:
                                logger.error(f"Invalid quantity: {quantity_str}")
                                flash(f"Error: Invalid quantity '{quantity_str}' in CSV row")
                                continue

                            if quantity <= 0:
                                logger.warning(f"Skipped row with non-positive quantity: {quantity}")
                                continue

                            crop_name = cur.execute("SELECT crops_name FROM crops WHERE id=?", (crop_id,)).fetchone()["crops_name"] if cur.execute("SELECT crops_name FROM crops WHERE id=?", (crop_id,)).fetchone() else None
                            if not crop_name:
                                flash(f"Crop '{crop}' could not be resolved for upload")
                                continue

                            try:
                                row_date = cleaned_row.get("date_received", "").strip()
                                if row_date:
                                    date_received = datetime.strptime(row_date, "%Y-%m-%d").strftime("%Y-%m-%d %H:%M:%S")
                                else:
                                    date_received = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                date_received = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            cur.execute("""
                            INSERT INTO inventory(
                                crop_name,
                                quantity,
                                farmer,
                                date_received,
                                location
                            )
                            VALUES(?,?,?,?,?)
                            """, (
                                crop_name,
                                quantity,
                                session["user"],
                                date_received,
                                location
                            ))
                            processed_any = True

                        except Exception as e:
                            logger.error(f"Error processing row: {row}, {e}")
                            flash(f"Error processing CSV row: {row}")

                if processed_any:
                    conn.commit()
                    update_analytics()
                    flash("CSV upload successful!")
                    logger.info(f"User {session['user']} uploaded {filename}")
                else:
                    flash("CSV upload completed, but no valid records were added.")

            except Exception as e:
                flash(f"Error processing file: {str(e)}")
                logger.error(f"Upload error: {str(e)}")
                conn.close()
                return redirect(request.url)

        elif crop_id:
            if not manual_quantity:
                flash("Quantity is required for manual crop entry")
                conn.close()
                return redirect(request.url)

            try:
                quantity = int(manual_quantity)
            except ValueError:
                flash("Quantity must be a valid number")
                conn.close()
                return redirect(request.url)

            if quantity <= 0:
                flash("Quantity must be greater than zero")
                conn.close()
                return redirect(request.url)

            try:
                if manual_date:
                    date_received = datetime.strptime(manual_date, "%Y-%m-%d").strftime("%Y-%m-%d %H:%M:%S")
                else:
                    date_received = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                flash("Invalid date format. Use YYYY-MM-DD.")
                conn.close()
                return redirect(request.url)

            crop_name_row = cur.execute("SELECT crops_name FROM crops WHERE id=?", (crop_id,)).fetchone()
            crop_name = crop_name_row["crops_name"] if crop_name_row else None
            if not crop_name:
                flash("Selected crop could not be found")
                conn.close()
                return redirect(request.url)

            cur.execute("""
            INSERT INTO inventory(
                crop_name,
                quantity,
                farmer,
                date_received,
                location
            )
            VALUES(?,?,?,?,?)
            """, (
                crop_name,
                quantity,
                session["user"],
                date_received,
                location
            ))
            conn.commit()
            update_analytics()
            processed_any = True
            flash("Manual harvest entry added successfully!")
            logger.info(f"User {session['user']} manually posted crop {crop_id} x{quantity}")

        else:
            flash("Please upload a CSV file or enter harvest details manually.")
            conn.close()
            return redirect(request.url)

        ##return redirect("/dashboard")
    
    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    crops = cur.fetchall()

    conn.close()
    return render_template("upload.html", crops=crops)

# ---------------- REST API ----------------

@app.route("/token", methods=["POST"])
def get_token():
    """Generate JWT token for authenticated users"""
    username = request.form.get("username")
    password = request.form.get("password")
    
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cur.fetchone()
    conn.close()
    
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid credentials"}), 401
    
    token = generate_jwt_token(username)
    if not token:
        return jsonify({"error": "Failed to generate token"}), 500
    
    logger.info(f"Token generated for user {username}")
    return jsonify({"token": token, "expires_in": 86400})


@app.route("/api/harvest", methods=["POST"])
@token_required
def api_harvest():
    """POST harvest data - Protected with JWT"""
    try:
        data = request.json
        
        # Validate input
        if not data.get("crop_name") or not data.get("quantity"):
            return jsonify({"error": "Missing crop_name or quantity"}), 400

        # Require location in API submissions
        if not data.get("location"):
            return jsonify({"error": "Missing location - location is required"}), 400
        
        try:
            quantity = int(data["quantity"])
            if quantity <= 0:
                return jsonify({"error": "Quantity must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Quantity must be a number"}), 400
        
        token = request.headers.get("Authorization")
        username = verify_jwt_token(token)
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
        INSERT INTO inventory(crop_name,quantity,farmer,date_received,location)
        VALUES(?,?,?,?,?)
        """, (
            data["crop_name"].strip(),
            quantity,
            data.get("farmer", username),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("location")
        ))
        
        conn.commit()
        conn.close()
        update_analytics()
        
        logger.info(f"Harvest recorded via API: {data['crop_name']} x{quantity} by {username}")
        return jsonify({"status": "harvest recorded", "crop": data["crop_name"], "quantity": quantity}), 201
    
    except Exception as e:
        logger.error(f"API Error: {str(e)}")
        return jsonify({"error": str(e)}), 500
    

# ============= MARKETPLACE ROUTES =============

@app.route("/marketplace")
def marketplace():
    """View all marketplace listings"""
    if "user" not in session:
        return redirect("/login")
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get all available listings with user info
    cur.execute("""
        SELECT m.*, u.username as seller_name, u.location as seller_location,
               u.reliability_score, u.reliability_status,
               u.completed_transactions, u.cancelled_transactions, u.total_transactions
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.status = 'available'
        ORDER BY m.listing_date DESC
    """)
    listings = cur.fetchall()
    
    # Get user's inventory for selling
    cur.execute("""
        SELECT crop_name, SUM(quantity) as total_quantity
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING total_quantity > 0
    """, (session["user"],))
    user_inventory = cur.fetchall()
    
    # Get all crops for the add listing form
    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    crops = cur.fetchall()

    # Delivered orders belonging to this buyer that still need a rating.
    cur.execute("""
        SELECT m.id, m.crop_name, m.delivery_date, u.username AS seller_name
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.buyer_username = ?
          AND m.status IN ('sold', 'delivered')
          AND m.buyer_rating IS NULL
        ORDER BY COALESCE(m.delivery_date, m.order_date) DESC
    """, (session["user"],))
    pending_ratings = cur.fetchall()
    
    conn.close()
    
    return render_template("marketplace.html", 
                         listings=listings, 
                         user_inventory=user_inventory,
                         crops=crops,
                         pending_ratings=pending_ratings)

@app.route("/marketplace/add", methods=["GET", "POST"])
def add_marketplace_listing():
    """Add a new listing to the marketplace"""
    if "user" not in session:
        return redirect("/login")
    
    if request.method == "POST":
        crop_id = request.form.get("crop_id")
        amount = request.form.get("amount")
        price = request.form.get("price")
        unit = request.form.get("unit", "kg")
        description = request.form.get("description", "").strip()
        expiry_days = request.form.get("expiry_days", 30)
        
        # Validate inputs
        if not crop_id or not amount or not price:
            flash("All fields are required")
            return redirect(request.url)
        
        try:
            amount = int(amount)
            price = float(price)
            expiry_days = int(expiry_days)
        except ValueError:
            flash("Invalid number format")
            return redirect(request.url)
        
        if amount <= 0 or price <= 0:
            flash("Amount and price must be positive")
            return redirect(request.url)
        
        conn = get_db()
        cur = conn.cursor()
        
        # Get crop name
        cur.execute("SELECT crops_name FROM crops WHERE id = ?", (crop_id,))
        crop = cur.fetchone()
        if not crop:
            flash("Invalid crop selected")
            conn.close()
            return redirect(request.url)
        
        crop_name = crop["crops_name"]
        
        # Check if user has enough inventory
        cur.execute("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE farmer = ? AND crop_name = ?
        """, (session["user"], crop_name))
        inventory = cur.fetchone()
        
        if not inventory or inventory["total"] < amount:
            flash(f"You don't have enough {crop_name} in your inventory. Available: {inventory['total'] if inventory else 0}")
            conn.close()
            return redirect(request.url)
        
        # Get user ID
        cur.execute("SELECT id, location FROM users WHERE username = ?", (session["user"],))
        user = cur.fetchone()
        
        if not user:
            flash("User not found")
            conn.close()
            return redirect(request.url)
        
        # Calculate expiry date
        expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert listing
        cur.execute("""
            INSERT INTO marketplace(
                user_id, username, crop_id, crop_name, amount, price,
                unit, status, listing_date, expiry_date, description, location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user["id"],
            session["user"],
            crop_id,
            crop_name,
            amount,
            price,
            unit,
            "available",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            expiry_date,
            description,
            user["location"]
        ))
        
        conn.commit()
        conn.close()
        
        flash(f"Listing for {crop_name} added successfully!")
        return redirect("/marketplace")
    
    # GET request - show form
    conn = get_db()
    cur = conn.cursor()
    
    # Get ONLY the crops that the user has in their inventory (unique crop names)
    cur.execute("""
        SELECT DISTINCT crop_name
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING SUM(quantity) > 0
        ORDER BY crop_name
    """, (session["user"],))
    user_crops = cur.fetchall()
    
    # Get the crop IDs for these crop names
    user_crops_with_ids = []
    for crop in user_crops:
        cur.execute("SELECT id FROM crops WHERE crops_name = ?", (crop["crop_name"],))
        crop_id = cur.fetchone()
        if crop_id:
            # Get total quantity available
            cur.execute("""
                SELECT SUM(quantity) as total_quantity
                FROM inventory
                WHERE farmer = ? AND crop_name = ?
            """, (session["user"], crop["crop_name"]))
            total = cur.fetchone()
            user_crops_with_ids.append({
                "id": crop_id["id"],
                "crops_name": crop["crop_name"],
                "total_quantity": total["total_quantity"] if total else 0
            })
    
    # Get user's inventory for display
    cur.execute("""
        SELECT crop_name, SUM(quantity) as total_quantity
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING total_quantity > 0
        ORDER BY crop_name
    """, (session["user"],))
    user_inventory = cur.fetchall()
    
    conn.close()
    
    # If user has no crops in inventory, show a message
    if not user_crops_with_ids:
        flash("You don't have any crops in your inventory. Please upload harvest data first.", "warning")
    
    return render_template("add_listing.html", 
                         crops=user_crops_with_ids, 
                         user_inventory=user_inventory)

@app.route("/marketplace/buy/<int:listing_id>", methods=["POST"])
def buy_marketplace_item(listing_id):
    """Purchase an item from the marketplace"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    quantity = data.get("quantity", 1)
    
    try:
        quantity = int(quantity)
    except ValueError:
        return jsonify({"error": "Invalid quantity"}), 400
    
    if quantity <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get current user's ID
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    
    current_user_id = current_user["id"]
    
    # Get the listing
    cur.execute("""
        SELECT m.*, u.username as seller_name
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.id = ? AND m.status = 'available'
    """, (listing_id,))
    listing = cur.fetchone()
    
    if not listing:
        conn.close()
        return jsonify({"error": "Listing not found or no longer available"}), 404
    
    if listing["user_id"] == current_user_id:
        conn.close()
        return jsonify({"error": "You cannot buy your own listing"}), 400
    
    if quantity > listing["amount"]:
        conn.close()
        return jsonify({"error": f"Only {listing['amount']} units available"}), 400
    
    # Determine seller username reliably
    seller_username = None
    try:
        seller_username = listing["seller_name"]
    except Exception:
        try:
            seller_username = listing["username"]
        except Exception:
            cur.execute("SELECT username FROM users WHERE id = ?", (listing["user_id"],))
            rr = cur.fetchone()
            seller_username = rr["username"] if rr else None

    # Calculate total price
    total_price = quantity * listing["price"]
    order_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Update the listing and create an order record for partial purchases
    if quantity == listing["amount"]:
        cur.execute("UPDATE marketplace SET status = 'sold', buyer_username = ?, order_status = 'sold', order_date = ?, delivery_confirmed = 0 WHERE id = ?", (
            session["user"],
            order_timestamp,
            listing_id
        ))
    else:
        cur.execute("""
            INSERT INTO marketplace (
                user_id, username, buyer_username, crop_id, crop_name, amount, price, unit,
                status, order_status, listing_date, order_date, expiry_date, description, location, delivery_confirmed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            listing["user_id"],
            listing["username"],
            session["user"],
            listing["crop_id"],
            listing["crop_name"],
            quantity,
            listing["price"],
            listing["unit"],
            "sold",
            "sold",
            listing["listing_date"],
            order_timestamp,
            listing["expiry_date"],
            listing["description"],
            listing["location"],
            0
        ))
        cur.execute("""
            UPDATE marketplace 
            SET amount = amount - ? 
            WHERE id = ?
        """, (quantity, listing_id))
    
    # Add to buyer's inventory (purchase source does not appear on harvest dashboard)
    cur.execute("""
        INSERT INTO inventory(crop_name, quantity, farmer, date_received, location, source)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        listing["crop_name"],
        quantity,
        session["user"],
        order_timestamp,
        listing["location"],
        "purchase"
    ))
    
    # Remove from seller's inventory
    cur.execute("""
        SELECT id, quantity FROM inventory 
        WHERE farmer = ? AND crop_name = ? 
        ORDER BY date_received ASC
    """, (seller_username, listing["crop_name"]))
    seller_inventory = cur.fetchall()
    
    remaining = quantity
    for item in seller_inventory:
        if remaining <= 0:
            break
        if item["quantity"] <= remaining:
            cur.execute("DELETE FROM inventory WHERE id = ?", (item["id"],))
            remaining -= item["quantity"]
        else:
            cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?", 
                       (item["quantity"] - remaining, item["id"]))
            remaining = 0
    
    conn.commit()

    # Create notification for the seller about the purchase
    try:
        if seller_username:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (
                    seller_username,
                    "Item Sold",
                    f"{session['user']} purchased {quantity} {listing['crop_name']} from your listing.",
                    "marketplace",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    0
                )
            )
            conn.commit()
            logger.info(f"Marketplace purchase notification created for {seller_username}")
    except Exception:
        logger.exception("Failed to create marketplace purchase notification")

    conn.close()
    
    return jsonify({
        "status": "success",
        "message": f"Purchased {quantity} {listing['crop_name']} for ₱{total_price:.2f}"
    })

@app.route("/marketplace/complete-order/<int:listing_id>", methods=["POST"])
def complete_marketplace_order(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("SELECT * FROM marketplace WHERE id = ? AND user_id = ? AND status = 'sold'", (listing_id, current_user["id"]))
    listing = cur.fetchone()

    if not listing:
        conn.close()
        return jsonify({"error": "Order not found or not eligible for completion"}), 404

    cur.execute(
        "UPDATE marketplace SET status = 'delivered', order_status = 'delivered', delivery_date = ?, delivery_confirmed = 1 WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing_id)
    )

    cur.execute("""
        UPDATE users
        SET completed_transactions = COALESCE(completed_transactions, 0) + 1,
            total_transactions = COALESCE(total_transactions, 0) + 1
        WHERE username = ?
    """, (session["user"],))

    if listing["buyer_username"]:
        try:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (
                    listing["buyer_username"],
                    "Order Delivered",
                    f"Your order for {listing['crop_name']} has been marked delivered by {session['user']}.",
                    "marketplace",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    0
                )
            )
        except Exception:
            logger.exception("Failed to create delivery notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Order marked as delivered."})

@app.route("/marketplace/my-purchases")
def my_marketplace_purchases():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.*, u.username AS seller_name, u.location AS seller_location
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.buyer_username = ? AND m.status IN ('sold', 'delivered')
        ORDER BY COALESCE(m.delivery_date, m.order_date) DESC
    """, (session["user"],))
    purchases = cur.fetchall()
    conn.close()
    return render_template("my_purchases.html", purchases=purchases)


@app.route("/marketplace/rate/<int:listing_id>", methods=["POST"])
def rate_marketplace_seller(listing_id):
    if "user" not in session:
        return redirect("/login")

    try:
        rating = int(request.form.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0
    if rating not in (1, 2, 3, 4, 5):
        flash("Please choose a rating from 1 to 5 stars.")
        return redirect("/marketplace/my-purchases")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username FROM marketplace
        WHERE id = ? AND buyer_username = ? AND status IN ('sold', 'delivered') AND buyer_rating IS NULL
    """, (listing_id, session["user"]))
    order = cur.fetchone()
    if not order:
        conn.close()
        flash("This order cannot be rated, or it has already been rated.")
        return redirect("/marketplace/my-purchases")

    cur.execute("UPDATE marketplace SET buyer_rating = ?, buyer_rating_date = ? WHERE id = ?", (
        rating, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing_id))
    cur.execute("SELECT AVG(buyer_rating) AS average_rating, COUNT(buyer_rating) AS rating_count FROM marketplace WHERE username = ? AND buyer_rating IS NOT NULL", (order["username"],))
    rating_summary = cur.fetchone()
    rating_count = rating_summary["rating_count"] or 0
    average_rating = rating_summary["average_rating"]
    if rating_count > 0 and average_rating is not None:
        status = "High Reliability" if average_rating >= 4 else "Medium Reliability" if average_rating >= 3 else "Low Reliability"
        cur.execute("UPDATE users SET reliability_score = ?, reliability_status = ? WHERE username = ?", (round(average_rating, 2), status, order["username"]))
    else:
        cur.execute("UPDATE users SET reliability_score = NULL, reliability_status = 'Not Yet Rated' WHERE username = ?", (order["username"],))
    conn.commit()
    conn.close()
    flash("Thank you. Your rating has been submitted.")
    return redirect("/marketplace/my-purchases")

@app.route("/marketplace/my-listings")
def my_marketplace_listings():
    """View user's own marketplace listings"""
    if "user" not in session:
        return redirect("/login")
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        flash("User not found")
        return redirect("/marketplace")
    current_user_id = current_user["id"]

    cur.execute("""
        SELECT m.*
        FROM marketplace m
        WHERE m.user_id = ? AND m.status = 'available'
        ORDER BY m.listing_date DESC
    """, (current_user_id,))
    active_listings = cur.fetchall()

    cur.execute("""
        SELECT m.*
        FROM marketplace m
        WHERE m.user_id = ? AND m.status = 'sold'
        ORDER BY order_date DESC
    """, (current_user_id,))
    sold_orders = cur.fetchall()

    cur.execute("""
        SELECT m.*
        FROM marketplace m
        WHERE m.user_id = ? AND m.status = 'delivered'
        ORDER BY delivery_date DESC
    """, (current_user_id,))
    delivered_orders = cur.fetchall()
    
    conn.close()
    
    return render_template("my_listings.html", 
                         active_listings=active_listings, 
                         sold_orders=sold_orders,
                         delivered_orders=delivered_orders)

@app.route("/marketplace/delete/<int:listing_id>", methods=["POST"])
def delete_marketplace_listing(listing_id):
    """Delete a marketplace listing"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    current_user_id = current_user["id"]

    cur.execute("SELECT * FROM marketplace WHERE id = ? AND user_id = ?", 
                (listing_id, current_user_id))
    listing = cur.fetchone()
    
    if not listing:
        conn.close()
        return jsonify({"error": "Listing not found or you don't have permission"}), 404
    
    cur.execute("DELETE FROM marketplace WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Listing deleted"})

@app.route("/marketplace/trade/<int:listing_id>", methods=["GET", "POST"])
def trade_marketplace_item(listing_id):
    """Trade an item from the marketplace"""
    if "user" not in session:
        return redirect("/login")
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get current user's ID
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        flash("User not found")
        conn.close()
        return redirect("/marketplace")
    
    current_user_id = current_user["id"]
    
    # Get the listing
    cur.execute("""
        SELECT m.*, u.username as seller_name, u.reliability_score, u.reliability_status, u.location AS seller_location
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.id = ? AND m.status = 'available'
    """, (listing_id,))
    listing = cur.fetchone()
    
    if not listing:
        flash("Listing not found or no longer available")
        conn.close()
        return redirect("/marketplace")
    
    if listing["user_id"] == current_user_id:
        flash("You cannot trade with yourself")
        conn.close()
        return redirect("/marketplace")
    
    if request.method == "POST":
        trade_crop = request.form.get("trade_crop")
        trade_amount = request.form.get("trade_amount")
        
        if not trade_crop or not trade_amount:
            flash("Please select a crop and enter amount")
            conn.close()
            return redirect(request.url)
        
        try:
            trade_amount = int(trade_amount)
        except ValueError:
            flash("Invalid trade amount")
            conn.close()
            return redirect(request.url)
        
        if trade_amount <= 0:
            flash("Trade amount must be positive")
            conn.close()
            return redirect(request.url)
        
        # Check if user has the crop to trade
        cur.execute("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE farmer = ? AND crop_name = ?
        """, (session["user"], trade_crop))
        inventory = cur.fetchone()
        
        if not inventory or inventory["total"] < trade_amount:
            flash(f"You don't have enough {trade_crop} to trade. Available: {inventory['total'] if inventory else 0}")
            conn.close()
            return redirect(request.url)
        
        # Process trade - Remove from buyer's inventory
        cur.execute("""
            SELECT id, quantity FROM inventory
            WHERE farmer = ? AND crop_name = ?
            ORDER BY date_received ASC
        """, (session["user"], trade_crop))
        buyer_items = cur.fetchall()
        
        remaining = trade_amount
        for item in buyer_items:
            if remaining <= 0:
                break
            if item["quantity"] <= remaining:
                cur.execute("DELETE FROM inventory WHERE id = ?", (item["id"],))
                remaining -= item["quantity"]
            else:
                cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?", 
                           (item["quantity"] - remaining, item["id"]))
                remaining = 0
        
        # Add traded crop to seller's inventory
        # Resolve seller username reliably
        seller_username = None
        try:
            seller_username = listing["seller_name"]
        except Exception:
            try:
                seller_username = listing["username"]
            except Exception:
                cur.execute("SELECT username FROM users WHERE id = ?", (listing["user_id"],))
                rr = cur.fetchone()
                seller_username = rr["username"] if rr else None

        cur.execute("""
            INSERT INTO inventory(crop_name, quantity, farmer, date_received, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            trade_crop,
            trade_amount,
            seller_username,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            listing["location"],
            "trade"
        ))
        
        # Add seller's crop to buyer's inventory
        cur.execute("""
            INSERT INTO inventory(crop_name, quantity, farmer, date_received, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            listing["crop_name"],
            listing["amount"],
            session["user"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            session.get("location", ""),
            "trade"
        ))
        
        # Update listing status
        cur.execute("UPDATE marketplace SET status = 'traded' WHERE id = ?", (listing_id,))
        
        conn.commit()
        # Notify seller that a trade occurred
        try:
            if seller_username:
                cur.execute(
                    "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                    (
                        seller_username,
                        "Item Traded",
                        f"{session['user']} completed a trade: gave {trade_amount} {trade_crop} and received your {listing['amount']} {listing['crop_name']}.",
                        "marketplace",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        0
                    )
                )
                conn.commit()
                logger.info(f"Marketplace trade notification created for {seller_username}")
        except Exception:
            logger.exception("Failed to create marketplace trade notification")

        conn.close()

        flash(f"Trade successful! You received {listing['amount']} {listing['crop_name']} and gave {trade_amount} {trade_crop}")
        return redirect("/marketplace")
    
    # GET request - show trade form
    cur.execute("""
        SELECT crop_name, SUM(quantity) as total_quantity
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING total_quantity > 0
    """, (session["user"],))
    user_inventory = cur.fetchall()
    
    conn.close()
    
    return render_template("trade_listing.html", listing=listing, user_inventory=user_inventory)

# ============= REAL-TIME DATA ENDPOINTS =============

@app.route("/dashboard-data")
def dashboard_data():
    """Return only the inventory table HTML for real-time updates"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM inventory WHERE source IS NULL OR source = 'harvest' ORDER BY date_received DESC LIMIT 20")
    data = cur.fetchall()
    
    conn.close()
    
    return render_template("inventory_table.html", inventory=data)


@app.route("/api/market-insights")
def api_market_insights():
    """Return algorithm-driven market monitoring and recommendation insights."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT crop_name, quantity, date_received FROM inventory ORDER BY date_received DESC")
    rows = cur.fetchall()
    conn.close()

    records = [{"crop_name": row["crop_name"], "quantity": row["quantity"], "date_received": row["date_received"]} for row in rows]
    return jsonify(build_market_analysis(records))


@app.route("/api/forecast")
def api_forecast():
    """Return crop demand forecasting results."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT crop_name, quantity, date_received FROM inventory ORDER BY date_received DESC")
    rows = cur.fetchall()
    conn.close()

    records = [{"crop_name": row["crop_name"], "quantity": row["quantity"], "date_received": row["date_received"]} for row in rows]
    analysis = build_market_analysis(records)
    return jsonify({"forecast": analysis.get("forecast", [])})


#NEW MARKETPLACE API
@app.route("/api/listing/<int:listing_id>")
def get_listing_api(listing_id):
    """Get listing details for the trade modal"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace WHERE id = ?", (listing_id,))
    listing = cur.fetchone()
    conn.close()
    
    if not listing:
        return jsonify({"error": "Listing not found"}), 404
    
    return jsonify({
        "crop_name": listing["crop_name"],
        "amount": listing["amount"],
        "unit": listing["unit"]
    })

@app.route("/api/stats")
def api_stats():
    """Get inventory statistics"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    monthly_offset = request.args.get("monthly_offset", "0")
    yearly_offset = request.args.get("yearly_offset", "0")
    try:
        monthly_offset = max(0, int(monthly_offset))
    except ValueError:
        monthly_offset = 0
    try:
        yearly_offset = max(0, int(yearly_offset))
    except ValueError:
        yearly_offset = 0

    def month_start(reference, offset):
        year = reference.year
        month = reference.month - offset
        while month <= 0:
            month += 12
            year -= 1
        return datetime(year, month, 1, 0, 0, 0)

    def month_end(start_date):
        if start_date.month == 12:
            next_month = datetime(start_date.year + 1, 1, 1, 0, 0, 0)
        else:
            next_month = datetime(start_date.year, start_date.month + 1, 1, 0, 0, 0)
        return next_month - timedelta(seconds=1)

    conn = get_db()
    cur = conn.cursor()

    # Total quantity
    cur.execute("SELECT SUM(quantity) as total FROM inventory WHERE source IS NULL OR source = 'harvest'")
    total = cur.fetchone()["total"] or 0

    # Crop summary
    cur.execute("SELECT crop_name, SUM(quantity) as total FROM inventory WHERE source IS NULL OR source = 'harvest' GROUP BY crop_name ORDER BY total DESC")
    crops = cur.fetchall()

    # Top crop
    top_crop = crops[0]["crop_name"] if crops else "N/A"

    # Number of entries
    cur.execute("SELECT COUNT(*) as count FROM inventory")
    entry_count = cur.fetchone()["count"]

    # Unique location count (using location entries from inventory)
    cur.execute("SELECT COUNT(DISTINCT location) as location_count FROM inventory WHERE location IS NOT NULL AND location != ''")
    location_count = cur.fetchone()["location_count"] or 0

    now = datetime.now()
    selected_month_start = month_start(now, monthly_offset)
    selected_month_end = month_end(selected_month_start)
    previous_month_start = month_start(now, monthly_offset + 1)
    previous_month_end = selected_month_start - timedelta(seconds=1)

    selected_year = now.year - yearly_offset
    selected_year_start = datetime(selected_year, 1, 1, 0, 0, 0)
    selected_year_end = datetime(selected_year, 12, 31, 23, 59, 59)
    previous_year_start = datetime(selected_year - 1, 1, 1, 0, 0, 0)
    previous_year_end = datetime(selected_year - 1, 12, 31, 23, 59, 59)

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? AND date_received <= ? GROUP BY crop_name ORDER BY total DESC LIMIT 10",
        (selected_month_start.strftime("%Y-%m-%d %H:%M:%S"), selected_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_monthly = [{"name": row["crop_name"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT location, SUM(quantity) as total FROM inventory WHERE location IS NOT NULL AND location != '' AND date_received >= ? AND date_received <= ? GROUP BY location ORDER BY total DESC LIMIT 10",
        (selected_month_start.strftime("%Y-%m-%d %H:%M:%S"), selected_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_monthly_locations = [{"name": row["location"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? AND date_received <= ? GROUP BY crop_name ORDER BY total DESC LIMIT 10",
        (selected_year_start.strftime("%Y-%m-%d %H:%M:%S"), selected_year_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_yearly = [{"name": row["crop_name"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT location, SUM(quantity) as total FROM inventory WHERE location IS NOT NULL AND location != '' AND date_received >= ? AND date_received <= ? GROUP BY location ORDER BY total DESC LIMIT 10",
        (selected_year_start.strftime("%Y-%m-%d %H:%M:%S"), selected_year_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_yearly_locations = [{"name": row["location"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? AND date_received <= ? GROUP BY crop_name",
        (selected_month_start.strftime("%Y-%m-%d %H:%M:%S"), selected_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    current_month = {row["crop_name"]: row["total"] for row in cur.fetchall()}

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? AND date_received <= ? GROUP BY crop_name",
        (previous_month_start.strftime("%Y-%m-%d %H:%M:%S"), previous_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    previous_month = {row["crop_name"]: row["total"] for row in cur.fetchall()}

    crop_names = sorted(set(current_month) | set(previous_month))
    monthly_comparison = [
        {
            "name": name,
            "current": current_month.get(name, 0),
            "previous": previous_month.get(name, 0)
        }
        for name in crop_names
    ]

    selected_month_label = f"{calendar.month_name[selected_month_start.month]} {selected_month_start.year}"
    previous_month_label = f"{calendar.month_name[previous_month_start.month]} {previous_month_start.year}"
    selected_year_label = str(selected_year)
    previous_year_label = str(selected_year - 1)

    conn.close()

    return jsonify({
        "total_quantity": total,
        "top_crop": top_crop,
        "crops_count": len(crops),
        "entry_count": entry_count,
        "location_count": location_count,
        "crops": [{"name": crop["crop_name"], "quantity": crop["total"]} for crop in crops],
        "monthly_comparison": monthly_comparison,
        "top_monthly": top_monthly,
        "top_yearly": top_yearly,
        "top_monthly_locations": top_monthly_locations,
        "top_yearly_locations": top_yearly_locations,
        "selected_month_label": selected_month_label,
        "previous_month_label": previous_month_label,
        "selected_year_label": selected_year_label,
        "previous_year_label": previous_year_label
    })
    
    
@app.route("/api/users", methods=["GET"])
def get_users():
    """Get list of all users for chat recipient selection"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT username FROM users WHERE username != ? ORDER BY username", (session["user"],))
    users = cur.fetchall()
    
    conn.close()
    
    users_list = [user["username"] for user in users]
    users_list.append("AgriBot")
    
    return jsonify(users_list)


@app.route("/api/bot", methods=["POST"])
def bot_response():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    message = data.get("message", "").strip().lower()

    if not message:
        reply = "Hello! I am AgriBot. Ask me about uploads, crops or page features."
    elif "upload" in message or "harvest" in message:
        reply = "To upload harvest data, use the Upload page and submit a valid CSV. Each crop entry will be stored with your user name."
    elif "admin" in message or "manager" in message:
        reply = "Admin users can access the Admin page to manage inventory and users. Only admins have full modify rights."
    elif "hello" in message or "hi" in message:
        reply = "Hello! I am AgriBot. How can I assist you today?"
    elif "profile" in message:
        reply = "You can view your profile from the top-right menu. It shows your user role and account details."
    elif "about" in message:
        reply = "Visit the About page to learn more about Agri-Direct and how it helps buyers, farmers, and administrators."
    else:
        reply = "AgriBot here! I can help you with uploads, dashboards, profiles, and account roles."

    # Store the bot's response in the database
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO messages(sender, recipient, message, timestamp) VALUES (?, ?, ?, ?)",
                ("AgriBot", session["user"], reply, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

    return jsonify({"message": reply})


@app.route("/api/messages", methods=["GET"])
def get_messagess():
    """Get chat messages for current conversation"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    recipient = request.args.get("recipient")
    if not recipient:
        return jsonify({"error": "Recipient required"}), 400
    
    current_user = session["user"]
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get messages between current user and recipient (both directions)
    cur.execute("""
        SELECT sender, recipient, message, timestamp 
        FROM messages 
        WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
        ORDER BY timestamp DESC, id DESC LIMIT 50
    """, (current_user, recipient, recipient, current_user))
    
    messages = cur.fetchall()
    conn.close()
    
    # Reverse to show oldest first
    messages_list = [{
        "sender": msg["sender"], 
        "recipient": msg["recipient"],
        "message": msg["message"], 
        "timestamp": msg["timestamp"]
    } for msg in reversed(messages)]
    
    return jsonify(messages_list)


@app.route("/api/messages", methods=["POST"])
def send_message():
    """Send a chat message"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    message = data.get("message", "").strip()
    recipient = data.get("recipient", "").strip()
    
    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400
    
    if not recipient:
        return jsonify({"error": "Recipient required"}), 400
    
    # Prevent sending messages to self
    if recipient == session["user"]:
        return jsonify({"error": "Cannot send message to yourself"}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("INSERT INTO messages(sender, recipient, message, timestamp) VALUES (?, ?, ?, ?)",
                (session["user"], recipient, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")))
    
    # If sending to AgriBot, generate and store bot response
    if recipient == "AgriBot":
        bot_message = message.lower()
        if not bot_message:
            reply = "Hello! I am AgriBot. Ask me about uploads, crops or page features."
        elif "upload" in bot_message or "harvest" in bot_message:
            reply = "To upload harvest data, use the Upload page and submit a valid CSV. Each crop entry will be stored with your user name."
        elif "admin" in bot_message or "manager" in bot_message:
            reply = "Admin users can access the Admin page to manage inventory and users. Only admins have full modify rights."
        elif "hello" in bot_message or "hi" in bot_message:
            reply = "Hello! I am AgriBot. How can I assist you today?"
        elif "profile" in bot_message:
            reply = "You can view your profile from the top-right menu. It shows your user role and account details."
        elif "about" in bot_message:
            reply = "Visit the About page to learn more about Agri-Direct and how it helps buyers, farmers, and administrators."
        else:
            reply = "AgriBot here! I can help you with uploads, dashboards, profiles, and account roles."
        
        cur.execute("INSERT INTO messages(sender, recipient, message, timestamp) VALUES (?, ?, ?, ?)",
                    ("AgriBot", session["user"], reply, datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Message sent from {session['user']} to {recipient}: {message}")
    return jsonify({"status": "success"})


# ---------------- LOGOUT ----------------

@app.route("/total-harvest")
def total_harvest():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(quantity) AS total FROM inventory")
    total = cur.fetchone()["total"] or 0

    cur.execute("SELECT crop_name, SUM(quantity) AS total FROM inventory GROUP BY crop_name ORDER BY total DESC")
    crop_totals = cur.fetchall()

    conn.close()
    return render_template("total_harvest.html", total=total, crop_totals=crop_totals)

@app.route("/top-crop")
def top_crop():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    # Get Top 5 crops
    cur.execute("""
        SELECT crop_name,
               SUM(quantity) AS total
        FROM inventory
        GROUP BY crop_name
        ORDER BY total DESC
        LIMIT 5
    """)

    top_crops = cur.fetchall()

    top = top_crops[0] if top_crops else None

    conn.close()

    return render_template(
        "top_crop.html",
        top=top,
        top_crops=top_crops
    )
    
@app.route("/locations")
def locations():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    # All locations
    cur.execute("""
        SELECT location,
               SUM(quantity) AS total
        FROM inventory
        WHERE location IS NOT NULL
          AND location != ''
        GROUP BY location
        ORDER BY total DESC
    """)

    locations_data = cur.fetchall()
    location_count = len(locations_data)

    # User locations
    cur.execute("""
        SELECT username, location
        FROM users
        WHERE location IS NOT NULL
          AND location != ''
    """)

    user_locations_raw = cur.fetchall()

    user_locations = []

    for user in user_locations_raw:
        lat, lng = geocode_location(user["location"])

        user_locations.append({
            "username": user["username"],
            "location": user["location"],
            "lat": lat,
            "lng": lng
        })

    conn.close()

    return render_template(
        "locations.html",
        locations=locations_data,
        location_count=location_count,
        user_locations=user_locations
    )

# ============= MESSAGING ROUTES =============

@app.route("/messages")
def messages_page():
    """Display the main messaging page"""
    if "user" not in session:
        return redirect("/login")
    
    return render_template("messages.html")


@app.route("/messages/conversations")
def get_conversations():
    """Get list of conversations for current user"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    username = session["user"]
    conn = get_db()
    cur = conn.cursor()
    
    # Get all unique people the user has messaged with (either sent or received)
    cur.execute("""
    SELECT DISTINCT
        CASE
            WHEN sender=? THEN recipient
            ELSE sender
        END AS person
    FROM messages
    WHERE sender=? OR recipient=?
    ORDER BY 1
    """, (username, username, username))
    
    people = cur.fetchall()
    conversations = []
    
    for person_row in people:
        person = person_row[0]

        # Get the last message between user and this person
        cur.execute("""
        SELECT message, timestamp
        FROM messages
        WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)
        ORDER BY timestamp DESC
        LIMIT 1
        """, (username, person, person, username))

        last_msg = cur.fetchone()

        conversations.append({
            "person": person,
            "last_message": last_msg[0] if last_msg else None,
            "last_timestamp": last_msg[1] if last_msg else None
        })

    # Note: conversations should only include users with messages; search will query users separately.

    # Ensure AgriBot appears as a contact (so users can message the bot)
    if not any((c["person"] or "").lower() == "agribot" for c in conversations):
        cur.execute("""
        SELECT message, timestamp
        FROM messages
        WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)
        ORDER BY timestamp DESC
        LIMIT 1
        """, ("AgriBot", username, username, "AgriBot"))
        last = cur.fetchone()
        conversations.append({
            "person": "AgriBot",
            "last_message": last[0] if last else None,
            "last_timestamp": last[1] if last else None
        })

    conn.close()
    return jsonify(conversations)


@app.route('/users/search')
def users_search():
    """Search for users by username. Returns up to 20 matches excluding the current user."""
    if "user" not in session:
        return jsonify([])

    q = str(request.args.get('q', '')).strip()
    if not q:
        return jsonify([])

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE username != ? AND username LIKE ? ORDER BY username LIMIT 20", (session['user'], f"%{q}%"))
    rows = cur.fetchall()
    conn.close()
    return jsonify([r[0] for r in rows])


@app.route("/messages/<person>")
def get_messages(person):
    """Get conversation history with a specific person"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    username = session["user"]
    person = str(person).strip()
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get all messages between user and this person
    cur.execute("""
    SELECT sender, message, timestamp
    FROM messages
    WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)
    ORDER BY timestamp ASC
    """, (username, person, person, username))
    
    messages = cur.fetchall()
    conn.close()
    
    # Convert to list of lists for JSON serialization
    return jsonify([list(msg) for msg in messages])


@app.route("/messages/send", methods=["POST"])
def send_chat_message():
    """Send a message to a recipient"""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json()
    sender = session["user"]
    recipient = str(data.get("recipient", "")).strip()
    message_text = str(data.get("message", "")).strip()
    
    if not recipient or not message_text:
        return jsonify({"status": "error", "message": "Missing recipient or message"}), 400
    
    if recipient == sender:
        return jsonify({"status": "error", "message": "Cannot message yourself"}), 400
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("""
        INSERT INTO messages(sender, recipient, message, timestamp)
        VALUES(?, ?, ?, ?)
        """, (sender, recipient, message_text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        # Resolve recipient to stored username (case-insensitive) to avoid mismatches
        try:
            cur.execute("SELECT username FROM users WHERE lower(username)=lower(?) LIMIT 1", (recipient,))
            row = cur.fetchone()
            notif_username = row[0] if row else recipient
        except Exception:
            notif_username = recipient

        # Create a notification for the recipient
        try:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (notif_username, "New Message", f"{sender} sent you a message.", "message", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0)
            )
            logger.info(f"Notification created for {notif_username} from {sender}")
        except Exception:
            # If notifications table missing or insert fails, continue without breaking messaging
            logger.exception("Failed to create notification for message")

        if recipient.lower() == "agribot":

            question = message_text.lower()

            if not question:
                reply = "Hello! I am AgriBot. Ask me about uploads, crops or page features."
            elif "upload" in question or "harvest" in question:
                reply = "To upload harvest data, use the Upload page and submit a valid CSV. Each crop entry will be stored with your user name."
            elif "admin" in question or "manager" in question:
                reply = "Admin users can access the Admin page to manage inventory and users. Only admins have full modify rights."
            elif "hello" in question or "hi" in question:
                reply = "Hello! I am AgriBot. How can I assist you today?"
            elif "profile" in question:
                reply = "You can view your profile from the top-right menu. It shows your user role and account details."
            elif "about" in question:
                reply = "Visit the About page to learn more about Agri-Direct and how it helps buyers, farmers, and administrators."
            else:
                reply = "AgriBot here! I can help you with uploads, dashboards, profiles, and account roles."

            cur.execute("INSERT INTO messages(sender, recipient, message, timestamp) VALUES (?, ?, ?, ?)",
                                ("AgriBot", session["user"], reply, datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")))
            # Create a notification for the user receiving the AgriBot reply
            try:
                cur.execute(
                    "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                    (session["user"], "New Message", "AgriBot replied to your message.", "message", datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), 0)
                )
            except Exception:
                logger.exception("Failed to create notification for AgriBot reply")
        
        conn.commit()
        logger.info(f"Message sent from {sender} to {recipient}")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/current-user")
def api_current_user():
    """Get current user info"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    return jsonify({"username": session["user"]})

@app.route("/notifications")
def notifications():

    if "user" not in session:
        return jsonify([])

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""

        SELECT *

        FROM notifications

        WHERE username=?

        ORDER BY created_at DESC

        LIMIT 20

    """, (session["user"],))

    rows = cur.fetchall()
    data = [dict(r) for r in rows]

    conn.close()

    return jsonify(data)


@app.route('/notifications/mark-read', methods=['POST'])
def notifications_mark_read():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE notifications SET is_read=1 WHERE username=? AND is_read=0", (session['user'],))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Failed to mark notifications read: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()


@app.route("/logout")
@app.route("/logout/")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


# ---------------- ERROR HANDLERS ----------------

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template('500.html'), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True)

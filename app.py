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
        location TEXT
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
    cur.execute("SELECT username, role FROM users ORDER BY role, username")
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

@app.route("/market-intelligence")
def market_intelligence():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("market_intelligence.html")


@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM inventory ORDER BY date_received DESC")
    data = cur.fetchall()

    update_analytics()

    cur.execute("""SELECT crop_name, SUM(quantity) as total FROM inventory GROUP BY crop_name ORDER BY total DESC""")
    crops = cur.fetchall()

    cur.execute("SELECT location, SUM(quantity) as total FROM inventory WHERE location IS NOT NULL AND location != '' GROUP BY location ORDER BY total DESC")
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
        ORDER BY period_value DESC
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

        if role != 'admin' and not location:
            flash("You should set your location in profile for better location-based analytics")

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
    



# ============= REAL-TIME DATA ENDPOINTS =============

@app.route("/dashboard-data")
def dashboard_data():
    """Return only the inventory table HTML for real-time updates"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM inventory ORDER BY date_received DESC LIMIT 50")
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
    cur.execute("SELECT SUM(quantity) as total FROM inventory")
    total = cur.fetchone()["total"] or 0

    # Crop summary
    cur.execute("SELECT crop_name, SUM(quantity) as total FROM inventory GROUP BY crop_name ORDER BY total DESC")
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
def get_messages():
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
    cur.execute("""
    SELECT crop_name,
        SUM(quantity) as total
    FROM inventory
    GROUP BY crop_name
    ORDER BY total DESC
    LIMIT 1
    """)

    top_crop = cur.fetchone()

    if top_crop:
        crop_name = top_crop[0]
        crop_volume = top_crop[1]
    else:
        crop_name = None
        crop_volume = 0

    conn.close()
    return render_template("top_crop.html", top=top, top_crops=top_crops)

@app.route("/crop-types")
def crop_types():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT crop_name, SUM(quantity) AS total FROM inventory GROUP BY crop_name ORDER BY crop_name")
    crops = cur.fetchall()
    crop_types_count = len(crops)
    conn.close()
    return render_template("crop_types.html", crops=crops, crop_types_count=crop_types_count)

@app.route("/locations")
def locations():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    # Group by location instead of farmer
    cur.execute("""
    SELECT location,
        SUM(quantity) as total
    FROM inventory
    GROUP BY location
    ORDER BY total DESC
    LIMIT 1
    """)

    top_location = cur.fetchone()

    if top_location:
        location_name = top_location[0]
        location_volume = top_location[1]
    else:
        location_name = None
        location_volume = 0

    # Get user locations for map
    cur.execute("SELECT username, location FROM users WHERE location IS NOT NULL AND location != ''")
    user_locations_raw = cur.fetchall()

    # Geocode locations
    user_locations = []
    for user in user_locations_raw:
        lat, lng = geocode_location(user['location'])
        user_locations.append({
            'username': user['username'],
            'location': user['location'],
            'lat': lat,
            'lng': lng
        })

    conn.close()
    return render_template("locations.html", locations=locations_data, location_count=location_count, user_locations=user_locations)



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
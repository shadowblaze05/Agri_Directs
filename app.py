from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import csv
import os
import logging
from datetime import datetime, timedelta
#import requests
import jwt
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "agridirect_secret")

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

API_KEY = os.environ.get("API_KEY", "mysecurekey123")
JWT_SECRET = os.environ.get("JWT_SECRET", "jwt_secret_key_agridirect")

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(location_query)}&key={api_key}"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data.get('status') == 'OK' and data.get('results'):
            loc = data['results'][0]['geometry']['location']
            return loc['lat'], loc['lng']
    except Exception as e:
        logger.warning(f"Geocode lookup failed for '{location}': {e}")

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
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'buyer',
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
        role = request.form.get("role", "buyer").lower()

        if role not in ["farmer", "buyer"]:
            role = "buyer"

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

    conn.close()
    return render_template("profile.html", user=user)


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

    can_modify = session.get("role") == "admin" or (session.get("role") == "farmer" and item["farmer"] == session["user"])
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

    can_modify = session.get("role") == "admin" or (session.get("role") == "farmer" and item["farmer"] == session["user"])
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

@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM inventory")
    data = cur.fetchall()

    cur.execute("""SELECT crop_name, SUM(quantity) as total FROM inventory GROUP BY crop_name ORDER BY total DESC""")
    crops = cur.fetchall()

    cur.execute("SELECT location, SUM(quantity) as total FROM inventory WHERE location IS NOT NULL AND location != '' GROUP BY location ORDER BY total DESC")
    locations = cur.fetchall()
    location_count = len(locations)

    conn.close()

    total = sum(row['quantity'] for row in data)

    return render_template("dashboard.html",
                       inventory=data,
                       total=total,
                       crops=crops,
                       locations=locations,
                       location_count=location_count)


# ---------------- CSV UPLOAD ----------------

@app.route("/upload", methods=["GET","POST"])
def upload():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role, location FROM users WHERE username=?", (session["user"],))
    user = cur.fetchone()
    role = user[0] if user else 'buyer'
    location = user[1] if user else None

    if request.method == "POST":

        if role == 'farmer' and not location:
            flash("Farmers must set their location in profile before posting crops")
            conn.close()
            return redirect("/profile")

        file = request.files.get("file")
        manual_crop = request.form.get("manual_crop_name", "").strip()
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

                            cur.execute("""
                            INSERT INTO inventory(crop_name,quantity,farmer,date_received,location)
                            VALUES(?,?,?,?,?)
                            """, (
                                crop,
                                quantity,
                                session["user"],
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                location
                            ))
                            processed_any = True

                        except Exception as e:
                            logger.error(f"Error processing row: {row}, {e}")
                            flash(f"Error processing CSV row: {row}")

                if processed_any:
                    conn.commit()
                    flash("CSV upload successful!")
                    logger.info(f"User {session['user']} uploaded {filename}")
                else:
                    flash("CSV upload completed, but no valid records were added.")

            except Exception as e:
                flash(f"Error processing file: {str(e)}")
                logger.error(f"Upload error: {str(e)}")
                conn.close()
                return redirect(request.url)

        elif manual_crop:
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

            cur.execute("""
            INSERT INTO inventory(crop_name,quantity,farmer,date_received,location)
            VALUES(?,?,?,?,?)
            """, (
                manual_crop,
                quantity,
                session["user"],
                date_received,
                location
            ))
            conn.commit()
            processed_any = True
            flash("Manual harvest entry added successfully!")
            logger.info(f"User {session['user']} manually posted crop {manual_crop} x{quantity}")

        else:
            flash("Please upload a CSV file or enter harvest details manually.")
            conn.close()
            return redirect(request.url)

        conn.close()
        return redirect("/dashboard")

    conn.close()
    return render_template("upload.html")


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
        INSERT INTO inventory(crop_name,quantity,farmer,date_received)
        VALUES(?,?,?,?)
        """, (
            data["crop_name"].strip(),
            quantity,
            data.get("farmer", username),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        
        conn.commit()
        conn.close()
        
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


@app.route("/api/stats")
def api_stats():
    """Get inventory statistics"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
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

    # Monthly crop comparisons
    now = datetime.now()
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_end = current_month_start - timedelta(seconds=1)
    previous_month_start = previous_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    current_year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? GROUP BY crop_name ORDER BY total DESC LIMIT 10",
        (current_month_start.strftime("%Y-%m-%d %H:%M:%S"),)
    )
    top_monthly = [{"name": row["crop_name"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? GROUP BY crop_name ORDER BY total DESC LIMIT 10",
        (current_year_start.strftime("%Y-%m-%d %H:%M:%S"),)
    )
    top_yearly = [{"name": row["crop_name"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT crop_name, SUM(quantity) as total FROM inventory WHERE date_received >= ? GROUP BY crop_name",
        (current_month_start.strftime("%Y-%m-%d %H:%M:%S"),)
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
        "top_yearly": top_yearly
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
    cur.execute("SELECT crop_name, SUM(quantity) AS total FROM inventory GROUP BY crop_name ORDER BY total DESC")
    top_crops = cur.fetchall()
    top = top_crops[0] if top_crops else None

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
    cur.execute("SELECT location, SUM(quantity) AS total FROM inventory WHERE location IS NOT NULL AND location != '' GROUP BY location ORDER BY total DESC")
    locations_data = cur.fetchall()
    location_count = len(locations_data)

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
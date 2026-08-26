import calendar
from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from .. import legacy as core
from ..algorithms.market_analysis import build_market_analysis
from ..legacy import logger
from ..models.database import get_db, update_analytics
from ..services.geo_service import geocode_location

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})


def _market_intelligence_access():
    """Return a redirect response when the signed-in user is not an admin."""
    if "user" not in session:
        return redirect(url_for("login"))
    if session.get("role") != "admin":
        flash("Market Intelligence is available to administrators only.")
        return redirect(url_for("portal_home"))
    return None

def home():
    if "user" in session:
        return redirect(url_for("portal_home"))
    return redirect("/login")

def portal_home():
    """Signed-in landing page driven by published Knowledge Hub posts."""
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    updates = cur.execute("""
        SELECT kp.post_id, kp.title, kp.content, kp.image, kp.created_at, kp.author,
               kc.category_name
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kc.category_id = kp.category_id
        WHERE kp.status = 'Published'
        ORDER BY kp.created_at DESC LIMIT 6
    """).fetchall()
    featured_listings = cur.execute("""
        SELECT m.id, m.crop_name, m.amount, m.price, m.unit, m.location,
               u.username AS seller_name
        FROM marketplace m JOIN users u ON u.id = m.user_id
        WHERE m.status = 'available'
        ORDER BY m.listing_date DESC LIMIT 3
    """).fetchall()
    marketplace_summary = cur.execute("""
        SELECT COUNT(*) AS active_listings, COUNT(DISTINCT crop_name) AS crop_count
        FROM marketplace WHERE status = 'available'
    """).fetchone()
    my_listing_summary = cur.execute("""
        SELECT COUNT(*) AS active_listings FROM marketplace
        WHERE user_id = (SELECT id FROM users WHERE username = ?)
          AND status = 'available'
    """, (session["user"],)).fetchone()
    conn.close()
    return render_template("home.html", updates=updates, featured_listings=featured_listings,
                           marketplace_summary=marketplace_summary,
                           my_listing_summary=my_listing_summary)

def about():
    return render_template("about.html")

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

def market_intelligence():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

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

def market_intelligence_price_monitoring():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

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

def market_intelligence_crop_recommendations():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

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

def market_intelligence_demand_forecasting():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

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

def market_intelligence_supply_balance():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

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

def api_market_insights():
    """Return algorithm-driven market monitoring and recommendation insights."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Market Intelligence is available to administrators only."}), 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT crop_name, quantity, date_received FROM inventory ORDER BY date_received DESC")
    rows = cur.fetchall()
    conn.close()

    records = [{"crop_name": row["crop_name"], "quantity": row["quantity"], "date_received": row["date_received"]} for row in rows]
    return jsonify(build_market_analysis(records))

def api_forecast():
    """Return crop demand forecasting results."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Market Intelligence is available to administrators only."}), 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT crop_name, quantity, date_received FROM inventory ORDER BY date_received DESC")
    rows = cur.fetchall()
    conn.close()

    records = [{"crop_name": row["crop_name"], "quantity": row["quantity"], "date_received": row["date_received"]} for row in rows]
    analysis = build_market_analysis(records)
    return jsonify({"forecast": analysis.get("forecast", [])})

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

def messages_page():
    """Display the main messaging page"""
    if "user" not in session:
        return redirect("/login")
    
    return render_template("messages.html")

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
    
    # Return row values explicitly. ``CompatRow`` is dict-like, so ``list(msg)``
    # would return its keys ("sender", "message", "timestamp") instead.
    return jsonify([
        [message["sender"], message["message"], message["timestamp"]]
        for message in messages
    ])

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

def api_current_user():
    """Get current user info"""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    return jsonify({"username": session["user"]})

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


def notification_center():
    """Display the signed-in user's notification history."""
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT * FROM notifications
        WHERE username=?
        ORDER BY created_at DESC
        LIMIT 50
    """, (session["user"],)).fetchall()
    cur.execute("UPDATE notifications SET is_read=1 WHERE username=? AND is_read=0", (session["user"],))
    conn.commit()
    conn.close()
    return render_template("notifications.html", notifications=rows)

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

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/', endpoint='home', view_func=home)
    application.add_url_rule('/home', endpoint='portal_home', view_func=portal_home)
    application.add_url_rule('/about', endpoint='about', view_func=about)
    application.add_url_rule('/crop-types', endpoint='crop_types', view_func=crop_types)
    application.add_url_rule('/market-intelligence', endpoint='market_intelligence', view_func=market_intelligence)
    application.add_url_rule('/market-intelligence/price-monitoring', endpoint='market_intelligence_price_monitoring', view_func=market_intelligence_price_monitoring)
    application.add_url_rule('/market-intelligence/crop-recommendations', endpoint='market_intelligence_crop_recommendations', view_func=market_intelligence_crop_recommendations)
    application.add_url_rule('/market-intelligence/demand-forecasting', endpoint='market_intelligence_demand_forecasting', view_func=market_intelligence_demand_forecasting)
    application.add_url_rule('/market-intelligence/supply-balance', endpoint='market_intelligence_supply_balance', view_func=market_intelligence_supply_balance)
    application.add_url_rule('/dashboard', endpoint='dashboard', view_func=dashboard)
    application.add_url_rule('/dashboard-data', endpoint='dashboard_data', view_func=dashboard_data)
    application.add_url_rule('/api/market-insights', endpoint='api_market_insights', view_func=api_market_insights)
    application.add_url_rule('/api/forecast', endpoint='api_forecast', view_func=api_forecast)
    application.add_url_rule('/api/stats', endpoint='api_stats', view_func=api_stats)
    application.add_url_rule('/api/users', endpoint='get_users', view_func=get_users, methods=['GET'])
    application.add_url_rule('/api/bot', endpoint='bot_response', view_func=bot_response, methods=['POST'])
    application.add_url_rule('/api/messages', endpoint='get_messagess', view_func=get_messagess, methods=['GET'])
    application.add_url_rule('/api/messages', endpoint='send_message', view_func=send_message, methods=['POST'])
    application.add_url_rule('/total-harvest', endpoint='total_harvest', view_func=total_harvest)
    application.add_url_rule('/top-crop', endpoint='top_crop', view_func=top_crop)
    application.add_url_rule('/locations', endpoint='locations', view_func=locations)
    application.add_url_rule('/messages', endpoint='messages_page', view_func=messages_page)
    application.add_url_rule('/messages/conversations', endpoint='get_conversations', view_func=get_conversations)
    application.add_url_rule('/users/search', endpoint='users_search', view_func=users_search)
    application.add_url_rule('/messages/<person>', endpoint='get_messages', view_func=get_messages)
    application.add_url_rule('/messages/send', endpoint='send_chat_message', view_func=send_chat_message, methods=['POST'])
    application.add_url_rule('/api/current-user', endpoint='api_current_user', view_func=api_current_user)
    application.add_url_rule('/notifications', endpoint='notifications', view_func=notifications)
    application.add_url_rule('/notifications-center', endpoint='notification_center', view_func=notification_center)
    application.add_url_rule('/notifications/mark-read', endpoint='notifications_mark_read', view_func=notifications_mark_read, methods=['POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['home', 'portal_home', 'about', 'crop_types', 'market_intelligence', 'market_intelligence_price_monitoring', 'market_intelligence_crop_recommendations', 'market_intelligence_demand_forecasting', 'market_intelligence_supply_balance', 'dashboard', 'dashboard_data', 'api_market_insights', 'api_forecast', 'api_stats', 'get_users', 'bot_response', 'get_messagess', 'send_message', 'total_harvest', 'top_crop', 'locations', 'messages_page', 'get_conversations', 'users_search', 'get_messages', 'send_chat_message', 'api_current_user', 'notifications', 'notification_center', 'notifications_mark_read']

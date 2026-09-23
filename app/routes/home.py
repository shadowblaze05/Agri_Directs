import calendar
from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from .. import legacy as core
from ..algorithms.market_analysis import build_market_analysis
from ..legacy import logger
from ..models.database import get_db, update_analytics
from ..services.geo_service import geocode_location
from ..services.market_intelligence import analyze_market_intelligence

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

def _latest_updates(limit=3):
    """Fetch recent published Knowledge Hub posts for public or signed-in views."""
    conn = get_db()
    cur = conn.cursor()
    updates = cur.execute("""
        SELECT kp.post_id, kp.title, kp.content, kp.image, kp.created_at, kp.author,
               kc.category_name
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kc.category_id = kp.category_id
        WHERE kp.status = 'Published'
        ORDER BY kp.created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return updates


def home():
    """Public landing page for visitors before they sign in or register."""
    updates = _latest_updates(limit=3)
    return render_template("public_home.html", updates=updates)


def portal_home():
    """Signed-in home/dashboard view that keeps the authenticated dashboard available."""
    if "user" not in session:
        return home()

    conn = get_db()
    cur = conn.cursor()
    updates = _latest_updates(limit=3)
    featured_listings = cur.execute("""
        SELECT m.id, m.crop_name, m.amount, m.price, m.unit, m.location,
               u.username AS seller_name
        FROM marketplace m JOIN users u ON u.id = m.user_id
        WHERE m.status = 'available'
        ORDER BY m.listing_date DESC LIMIT 3
    """).fetchall()
    marketplace_summary = cur.execute("""
        SELECT COUNT(*) AS active_listings, COUNT(DISTINCT m.crop_name) AS crop_count
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.status = 'available'
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
    cur.execute("SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.source IS NULL OR i.source = 'harvest' GROUP BY i.crop_id, c.crops_name ORDER BY total DESC")
    crops = cur.fetchall()
    crop_types_count = len(crops)
    conn.close()

    return render_template("crop_types.html", crops=crops, crop_types_count=crop_types_count)

def _market_records_from_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT c.crops_name AS crop_name, i.quantity, i.date_received, i.location "
        "FROM inventory i JOIN crops c ON c.id = i.crop_id "
        "ORDER BY i.date_received DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "crop_name": row["crop_name"],
            "quantity": row["quantity"],
            "date_received": row["date_received"],
            "location": row["location"],
        }
        for row in rows
    ]


def _market_analysis_context():
    records = _market_records_from_db()
    try:
        analysis = analyze_market_intelligence(records)
    except Exception:
        analysis = build_market_analysis(records)

    return analysis


def market_intelligence():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

    analysis = _market_analysis_context()
    summary = analysis.get("summary", {})
    price_monitoring = analysis.get("price_monitoring", [])
    recommendations = analysis.get("recommendations", [])
    risk_alerts = analysis.get("risk_alerts", [])

    summary_cards = [
        {"label": "Market value", "badge": summary.get("market_pressure", "Balanced").title(), "value": f"₱{int(summary.get('total_quantity', 0)):,}", "detail": f"Current live harvest volume for {summary.get('current_month', 'this month')}."},
        {"label": "Average price index", "badge": f"{max(0, min(100, round(sum(item.get('price_index', 0) for item in price_monitoring) / max(len(price_monitoring), 1), 0)))}", "value": str(round(sum(item.get('price_index', 0) for item in price_monitoring) / max(len(price_monitoring), 1), 1)), "detail": "Derived from live crop prices and supply pressure."},
        {"label": "Active crops", "badge": "Live", "value": str(summary.get("active_crops", 0)), "detail": "Crops currently represented in inventory."},
        {"label": "Alert level", "badge": "Watch" if risk_alerts else "Stable", "value": "Moderate" if risk_alerts else "Stable", "detail": "Based on current dynamic supply thresholds."},
    ]

    pulse_items = [
        {"label": item.get("crop", "Crop"), "value": item.get("signal", "Balanced"), "progress": min(100, max(10, int(item.get("price_index", 50))))}
        for item in price_monitoring[:4]
    ]

    focus_items = [
        {"title": f"Top recommendation: {item.get('crop', 'Crop')}", "badge": "Priority", "detail": item.get("reason", "High-performing option."), "metric": f"{round(item.get('score', 0) * 100, 0)}%", "timeline": "Live signal"}
        for item in recommendations[:2]
    ]

    if not focus_items:
        focus_items = [{"title": "No active crop recommendation", "badge": "Stable", "detail": "Inventory data is insufficient to rank crops yet.", "metric": "0%", "timeline": "Waiting for data"}]

    insight_items = [
        {"title": alert.get("type", "Market alert").replace("_", " ").title(), "level": alert.get("severity", "Medium").title(), "desc": alert.get("message", "No supply warning.")}
        for alert in risk_alerts[:2]
    ]

    if not insight_items:
        insight_items = [{"title": "Demand resilience", "level": "Positive", "desc": "Current data suggests supply is balanced and stable."}]

    chart_points = [int(item.get("price_index", 0)) for item in price_monitoring[:6]]
    if not chart_points:
        chart_points = [0, 0, 0, 0, 0, 0]

    return render_template(
        "market_intelligence.html",
        active_page="summary",
        summary_cards=summary_cards,
        price_labels=["Current"] * max(1, len(chart_points)),
        price_series=chart_points,
        pulse_items=pulse_items,
        focus_items=focus_items,
        insight_items=insight_items,
    )


def market_intelligence_price_monitoring():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

    analysis = _market_analysis_context()
    price_monitoring = analysis.get("price_monitoring", [])
    price_items = [
        {
            "crop": item.get("crop", "Crop"),
            "current_price": f"₱{float(item.get('price_index', 0)):.0f}/index",
            "variance": f"{item.get('price_index', 0) - 100:+.1f}%",
            "trend": item.get("trend", "Stable"),
            "signal": item.get("signal", "Balanced"),
        }
        for item in price_monitoring[:6]
    ]

    if not price_items:
        price_items = [{"crop": "No data", "current_price": "₱0/index", "variance": "0.0%", "trend": "Stable", "signal": "Waiting for inventory"}]

    summary_total = analysis.get("summary", {}).get("total_quantity", 0)
    detail_items = [
        {"label": "Live harvest", "value": f"{summary_total}", "note": "Current combined inventory volume."},
        {"label": "Active crops", "value": str(analysis.get("summary", {}).get("active_crops", 0)), "note": "Crops represented in the live data."},
        {"label": "Market pressure", "value": analysis.get("summary", {}).get("market_pressure", "balanced").title(), "note": "Current supply condition."},
        {"label": "Coverage", "value": f"{len(price_monitoring)} crops", "note": "Based on current live inventory."},
    ]

    trend_labels = ["Live"] * max(len(price_monitoring), 1)
    trend_series = [int(item.get("price_index", 0)) for item in price_monitoring]
    if not trend_series:
        trend_series = [0]

    return render_template(
        "market_intelligence_price.html",
        active_page="price",
        price_items=price_items,
        detail_items=detail_items,
        trend_labels=trend_labels,
        trend_series=trend_series,
    )


def market_intelligence_crop_recommendations():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

    analysis = _market_analysis_context()
    recommendations = analysis.get("recommendations", [])
    recommendation_items = [
        {
            "crop": item.get("crop", "Crop"),
            "score": round(item.get("score", 0) * 100, 0),
            "reason": item.get("reason", "No recommendation available."),
            "demand": "High" if item.get("score", 0) > 0.6 else "Balanced",
            "seasonal": "Strong" if item.get("score", 0) > 0.6 else "Watch",
        }
        for item in recommendations[:5]
    ]

    if not recommendation_items:
        recommendation_items = [{"crop": "No data", "score": 0, "reason": "Inventory data is insufficient for ranking.", "demand": "N/A", "seasonal": "N/A"}]

    return render_template(
        "market_intelligence_recommendations.html",
        active_page="recommendations",
        recommendation_items=recommendation_items,
        recommendation_labels=[item["crop"] for item in recommendation_items],
        recommendation_scores=[item["score"] for item in recommendation_items],
    )


def market_intelligence_demand_forecasting():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

    analysis = _market_analysis_context()
    forecast_items = analysis.get("forecast", [])
    forecast_items = [
        {
            "crop": item.get("crop", "Crop"),
            "note": f"{item.get('method', 'trend')} forecast remains active for current trend.",
            "confidence": "High" if item.get("method") == "arima" else "Medium",
            "historical": str(round(float(item.get("latest_value", 0)), 1)),
            "projected": str(round(float(item.get("forecast_quantity", 0)), 1)),
        }
        for item in forecast_items[:5]
    ]

    if not forecast_items:
        forecast_items = [{"crop": "No data", "note": "No forecast available until inventory exists.", "confidence": "Low", "historical": "0", "projected": "0"}]

    return render_template(
        "market_intelligence_forecast.html",
        active_page="forecast",
        forecast_items=forecast_items,
        forecast_labels=[item["crop"] for item in forecast_items],
        historical_series=[float(item["historical"]) for item in forecast_items],
        projected_series=[float(item["projected"]) for item in forecast_items],
    )


def market_intelligence_supply_balance():
    access_denied = _market_intelligence_access()
    if access_denied:
        return access_denied

    analysis = _market_analysis_context()
    risk_alerts = analysis.get("risk_alerts", [])
    supply_items = [
        {
            "crop": alert.get("crop", "Crop"),
            "status": alert.get("type", "Balanced").replace("_", " ").title(),
            "note": alert.get("message", "Current supply is within the normal band."),
            "band": "Dynamic" if alert.get("severity") == "high" else "Live",
            "shift": "Active",
        }
        for alert in risk_alerts[:5]
    ]

    if not supply_items:
        supply_items = [{"crop": "No data", "status": "Balanced", "note": "There are no active supply alerts yet.", "band": "Safe", "shift": "0%"}]

    return render_template(
        "market_intelligence_supply.html",
        active_page="supply",
        supply_items=supply_items,
        supply_labels=[item["crop"] for item in supply_items],
        supply_series=[max(10, min(100, 50 + idx * 18)) for idx in range(len(supply_items))],
    )

def dashboard():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT i.*, c.crops_name AS crop_name FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.source IS NULL OR i.source = 'harvest' ORDER BY i.date_received DESC LIMIT 20")
    data = cur.fetchall()

    update_analytics()

    cur.execute("""SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.source IS NULL OR i.source = 'harvest' GROUP BY i.crop_id, c.crops_name ORDER BY total DESC""")
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
    
    cur.execute("SELECT i.*, c.crops_name AS crop_name FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.source IS NULL OR i.source = 'harvest' ORDER BY i.date_received DESC LIMIT 20")
    data = cur.fetchall()
    
    conn.close()
    
    return render_template("inventory_table.html", inventory=data)

def api_market_insights():
    """Return algorithm-driven market monitoring and recommendation insights."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT c.crops_name AS crop_name, i.quantity, i.date_received FROM inventory i JOIN crops c ON c.id=i.crop_id ORDER BY i.date_received DESC")
    rows = cur.fetchall()
    conn.close()

    records = [{"crop_name": row["crop_name"], "quantity": row["quantity"], "date_received": row["date_received"]} for row in rows]
    try:
        analysis = analyze_market_intelligence(records)
    except Exception:
        analysis = build_market_analysis(records)
    return jsonify(analysis)


def api_forecast():
    """Return crop demand forecasting results."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT c.crops_name AS crop_name, i.quantity, i.date_received FROM inventory i JOIN crops c ON c.id=i.crop_id ORDER BY i.date_received DESC")
    rows = cur.fetchall()
    conn.close()

    records = [{"crop_name": row["crop_name"], "quantity": row["quantity"], "date_received": row["date_received"]} for row in rows]
    try:
        analysis = analyze_market_intelligence(records)
    except Exception:
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
    cur.execute("SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.source IS NULL OR i.source = 'harvest' GROUP BY i.crop_id, c.crops_name ORDER BY total DESC")
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
        "SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.date_received >= ? AND i.date_received <= ? GROUP BY i.crop_id, c.crops_name ORDER BY total DESC LIMIT 10",
        (selected_month_start.strftime("%Y-%m-%d %H:%M:%S"), selected_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_monthly = [{"name": row["crop_name"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT location, SUM(quantity) as total FROM inventory WHERE location IS NOT NULL AND location != '' AND date_received >= ? AND date_received <= ? GROUP BY location ORDER BY total DESC LIMIT 10",
        (selected_month_start.strftime("%Y-%m-%d %H:%M:%S"), selected_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_monthly_locations = [{"name": row["location"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.date_received >= ? AND i.date_received <= ? GROUP BY i.crop_id, c.crops_name ORDER BY total DESC LIMIT 10",
        (selected_year_start.strftime("%Y-%m-%d %H:%M:%S"), selected_year_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_yearly = [{"name": row["crop_name"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT location, SUM(quantity) as total FROM inventory WHERE location IS NOT NULL AND location != '' AND date_received >= ? AND date_received <= ? GROUP BY location ORDER BY total DESC LIMIT 10",
        (selected_year_start.strftime("%Y-%m-%d %H:%M:%S"), selected_year_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    top_yearly_locations = [{"name": row["location"], "total": row["total"]} for row in cur.fetchall()]

    cur.execute(
        "SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.date_received >= ? AND i.date_received <= ? GROUP BY i.crop_id, c.crops_name",
        (selected_month_start.strftime("%Y-%m-%d %H:%M:%S"), selected_month_end.strftime("%Y-%m-%d %H:%M:%S"))
    )
    current_month = {row["crop_name"]: row["total"] for row in cur.fetchall()}

    cur.execute(
        "SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.date_received >= ? AND i.date_received <= ? GROUP BY i.crop_id, c.crops_name",
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

    cur.execute("SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id GROUP BY i.crop_id, c.crops_name ORDER BY total DESC")
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
        SELECT c.crops_name AS crop_name,
               SUM(i.quantity) AS total
        FROM inventory i
        JOIN crops c ON c.id=i.crop_id
        GROUP BY i.crop_id, c.crops_name
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

"""Auth HTTP routes.

Handlers retain the legacy SQL and template behavior while living in a domain module.
"""

from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .. import legacy as core
from ..legacy import logger
from ..models.database import get_db, update_analytics
from ..services.auth_service import generate_jwt_token, token_required, verify_jwt_token

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

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

def register_user():

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
        except IntegrityError:
            flash("Username already exists")
            logger.warning(f"Registration failed: username {username} already exists")
        finally:
            conn.close()

    return render_template("register.html")

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

def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# Preserve decorator ordering from the legacy module.
api_harvest = token_required(api_harvest)

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    application.add_url_rule('/register', endpoint='register', view_func=register_user, methods=['GET', 'POST'])
    application.add_url_rule('/token', endpoint='get_token', view_func=get_token, methods=['POST'])
    application.add_url_rule('/api/harvest', endpoint='api_harvest', view_func=api_harvest, methods=['POST'])
    application.add_url_rule('/logout', endpoint='logout', view_func=logout)
    application.add_url_rule('/logout/', endpoint='logout', view_func=logout)
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['login', 'register_user', 'get_token', 'api_harvest', 'logout']

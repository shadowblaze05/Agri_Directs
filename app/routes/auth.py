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

        # Accept the previous ``username`` field name for API and test-client
        # compatibility while the browser form uses the clearer identifier name.
        identifier = (request.form.get("identifier") or request.form.get("username") or "").strip()
        password = request.form.get("password", "")

        if not identifier or not password:
            flash("Enter your username or email and password")
            return render_template("login.html")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE username=? OR email=?",
            (identifier, identifier),
        )
        user = cur.fetchone()
        conn.close()

        if user:
            if check_password_hash(user["password"], password):
                session["user"] = user["username"]
                session["role"] = user["role"] if user["role"] else 'buyer'
                logger.info(f"User {user['username']} logged in")
                return redirect("/dashboard")
            else:
                logger.warning(f"Invalid password for {identifier}")
        else:
            logger.warning(f"User {identifier} not found")

        flash("Invalid username, email, or password")

    return render_template("login.html")

def register_user():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        first_name = (request.form.get("first_name", "") or username).strip()
        last_name = (request.form.get("last_name", "") or "User").strip()
        email = (request.form.get("email", "") or f"{username}@example.com").strip().lower()
        raw_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", raw_password)

        if not username or not raw_password:
            flash("Username and password are required")
            return render_template("register.html")
        if len(username) < 3:
            flash("Username must be at least 3 characters")
            return render_template("register.html")
        if " " in username:
            flash("Username cannot contain spaces")
            return render_template("register.html")
        if email and "@" not in email:
            flash("Enter a valid email address")
            return render_template("register.html")
        if len(raw_password) < 6:
            flash("Password must be at least 6 characters")
            return render_template("register.html")
        if raw_password != confirm_password:
            flash("Passwords do not match")
            return render_template("register.html")

        password = generate_password_hash(raw_password)
        # New registrations are simple users by default
        role = "user"

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                """INSERT INTO users(username, first_name, last_name, email, password, role)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (username, first_name, last_name, email, password, role),
            )
            conn.commit()
            logger.info(f"User {username} registered with role {role}")
            session["user"] = username
            session["role"] = role
            flash("Registration successful! Welcome to Agri-Direct.")
            return redirect("/dashboard")
        except IntegrityError:
            flash("That username or email address is already registered")
            logger.warning(f"Registration failed: username or email already exists for {username}")
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
        INSERT INTO inventory(crop_id,quantity,farmer,date_received,location)
        SELECT id, ?, ?, ?, ? FROM crops WHERE crops_name=?
        """, (
            quantity,
            data.get("farmer", username),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("location"),
            data["crop_name"].strip(),
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

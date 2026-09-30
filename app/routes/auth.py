from datetime import datetime, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .. import legacy as core
from ..legacy import logger
from ..models.database import get_db, update_analytics
from ..services.auth_service import generate_jwt_token, token_required, verify_jwt_token
from ..services.geotag_service import validate_coordinates, verify_crop_location
from ..services.profile_service import missing_harvest_profile_requirements

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

def login():

    if request.method == "POST":

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
                return redirect("/home")
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
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Submit harvest data as a JSON object"}), 400
        
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
        except (TypeError, ValueError):
            return jsonify({"error": "Quantity must be a number"}), 400
        
        token = request.headers.get("Authorization")
        username = verify_jwt_token(token)
        if not username:
            return jsonify({"error": "Invalid or expired token"}), 401

        latitude = longitude = capture_time = None
        latitude_value = data.get("latitude")
        longitude_value = data.get("longitude")
        if latitude_value not in (None, "") or longitude_value not in (None, ""):
            if latitude_value in (None, "") or longitude_value in (None, ""):
                return jsonify({"error": "Both latitude and longitude are required"}), 400
            try:
                latitude, longitude = validate_coordinates(latitude_value, longitude_value)
            except ValueError as error:
                return jsonify({"error": str(error)}), 400

            capture_time_value = data.get("gps_captured_at")
            if capture_time_value:
                try:
                    captured_at = datetime.fromisoformat(
                        str(capture_time_value).replace("Z", "+00:00")
                    )
                except ValueError:
                    return jsonify({"error": "The GPS capture timestamp is invalid"}), 400
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
                capture_time = captured_at.isoformat()
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT first_name, last_name, email, profile_picture, profile_photo_captured_at, "
            "location, psgc_location, geotag_location, location_latitude, location_longitude, location_verified "
            "FROM users WHERE username=?",
            (username,),
        )
        profile = cur.fetchone()
        if not profile:
            conn.close()
            return jsonify({"error": "The authenticated account could not be found"}), 404

        missing_requirements = missing_harvest_profile_requirements(profile)
        if missing_requirements:
            conn.close()
            return jsonify({
                "error": "Complete your profile before submitting harvest.",
                "missing_profile_requirements": missing_requirements,
            }), 403

        has_reference_location = bool(profile["location_verified"])
        proximity_status, distance = verify_crop_location(
            profile["location_latitude"] if has_reference_location else None,
            profile["location_longitude"] if has_reference_location else None,
            latitude,
            longitude,
            current_app.config["MAX_CROP_DISTANCE_METERS"],
        )
        notes = ["API submissions do not include crop photo evidence."]
        if not has_reference_location:
            notes.append("Farmer has no captured reference location.")
        if latitude is None or capture_time is None:
            notes.append("Harvest GPS capture is missing or incomplete.")
        verification_status = "manual_review"

        cur.execute("""
        INSERT INTO inventory(
            crop_id, quantity, farmer, date_received, location, latitude, longitude,
            capture_time, distance_from_user, verification_status, verification_notes
        )
        SELECT id, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM crops WHERE crops_name=?
        """, (
            quantity,
            username,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("location"),
            latitude,
            longitude,
            capture_time,
            distance,
            verification_status,
            " ".join(notes),
            data["crop_name"].strip(),
        ))
        if cur.rowcount == 0:
            conn.close()
            return jsonify({"error": "Crop was not found"}), 404
        
        conn.commit()
        conn.close()
        update_analytics()
        
        logger.info(f"Harvest recorded via API: {data['crop_name']} x{quantity} by {username}")
        return jsonify({
            "status": "harvest recorded",
            "crop": data["crop_name"],
            "quantity": quantity,
            "verification_status": verification_status,
            "proximity_status": proximity_status,
            "distance_meters": distance,
            "distance_km": distance / 1000 if distance is not None else None,
            "max_distance_km": current_app.config["MAX_CROP_DISTANCE_KM"],
        }), 201
    
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

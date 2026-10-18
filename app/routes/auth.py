import hashlib
import hmac
import secrets
import smtplib
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_mail import Message
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, limiter, mail
from .. import legacy as core
from ..password_policy import password_policy_error
from ..legacy import logger
from ..models.database import get_db, update_analytics
from ..services.auth_service import generate_jwt_token, token_required, verify_jwt_token
from ..services.geotag_service import validate_coordinates, verify_crop_location
from ..services.profile_service import missing_harvest_profile_requirements

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})


def _ensure_password_reset_table():
    """Create or upgrade the password-reset table when startup migrations are absent."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            token TEXT UNIQUE,
            expires_at TEXT,
            created_at TEXT,
            used_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            purpose TEXT NOT NULL DEFAULT 'password_reset'
        )
        """
    )
    conn.commit()
    conn.close()
    columns = {column["name"] for column in inspect(db.engine).get_columns("password_reset_tokens")}
    if "attempt_count" not in columns:
        db.session.execute(
            text(
                "ALTER TABLE password_reset_tokens "
                "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        )
        db.session.commit()
    if "purpose" not in columns:
        db.session.execute(text(
            "ALTER TABLE password_reset_tokens ADD COLUMN purpose "
            "VARCHAR(32) NOT NULL DEFAULT 'password_reset'"
        ))
        db.session.commit()


@limiter.limit("5 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"])
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
            "SELECT username, password, role, is_active, is_verified FROM users WHERE username=? OR email=?",
            (identifier, identifier),
        )
        user = cur.fetchone()
        conn.close()

        if user:
            if check_password_hash(user["password"], password):
                # Existing accounts predate email challenges. Only accounts with
                # an explicit pending verification challenge are held at login.
                if not user["is_verified"]:
                    _ensure_password_reset_table()
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT username, email FROM users WHERE username=? OR email=?",
                        (identifier, identifier),
                    )
                    pending_user = cur.fetchone()
                    conn.close()
                    if not pending_user:
                        flash("Your registration expired before email verification. Please register again.")
                        return render_template("login.html")
                    if _has_pending_email_verification(identifier):
                        session["email_verification_email"] = pending_user["email"]
                        flash("Verify your email address before logging in.")
                        return redirect(url_for("verify_email"))
                if not user["is_active"]:
                    flash("This account is inactive. Contact an administrator.")
                    return render_template("login.html")
                session.clear()
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

@limiter.limit("10 per hour", methods=["POST"])
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
        password_error = password_policy_error(raw_password, (username, email.split("@", 1)[0]))
        if password_error:
            flash(password_error)
            return render_template("register.html")
        if raw_password != confirm_password:
            flash("Passwords do not match")
            return render_template("register.html")

        _ensure_password_reset_table()
        password = generate_password_hash(raw_password)
        # New registrations are simple users by default
        role = "user"

        conn = get_db()
        cur = conn.cursor()

        try:
            # Keep pending accounts so a user can retry verification later.
            # If the same credentials are submitted again, issue a fresh code
            # instead of treating the pending account as a permanent duplicate.
            cur.execute(
                "SELECT id, username, email, password, is_verified FROM users "
                "WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)",
                (username, email),
            )
            existing_user = cur.fetchone()
            if existing_user:
                same_account = (
                    existing_user["username"].lower() == username.lower()
                    and (existing_user["email"] or "").lower() == email.lower()
                )
                if (
                    same_account
                    and not existing_user["is_verified"]
                    and check_password_hash(existing_user["password"], raw_password)
                ):
                    session.clear()
                    session["email_verification_email"] = existing_user["email"]
                    sent = _issue_email_verification_code(existing_user["id"], existing_user["email"])
                    if sent:
                        flash("A new verification code has been sent. Enter it to finish registration.")
                    else:
                        flash("Your account is still pending verification. Try sending a new code.")
                    return redirect(url_for("verify_email"))
                flash("That username or email address is already registered")
                return render_template("register.html")

            cur.execute(
                """INSERT INTO users(
                    username, first_name, last_name, email, password, role, is_verified, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, first_name, last_name, email, password, role, False, False),
            )
            conn.commit()
            cur.execute("SELECT id FROM users WHERE username=?", (username,))
            user_id = cur.fetchone()["id"]
            session.clear()
            session["email_verification_email"] = email
            sent = _issue_email_verification_code(user_id, email)
            logger.info("Registration verification issued for account %s", username)
            if sent:
                flash("Enter the code sent to your email to finish registration.")
            else:
                flash("Your account is pending verification, but we could not send the email. Try sending a new code.")
            return redirect(url_for("verify_email"))
        except IntegrityError:
            flash("That username or email address is already registered(1 attempt per 10min)")
            logger.warning(f"Registration failed: username or email already exists for {username}")
        finally:
            conn.close()

    return render_template("register.html")

def _reset_code_digest(code):
    """Return a keyed digest so short numeric codes are not stored in plaintext."""
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(secret, code.encode("ascii"), hashlib.sha256).hexdigest()


def _has_pending_email_verification(identifier):
    _ensure_password_reset_table()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM users u JOIN password_reset_tokens t ON t.user_id=u.id "
        "WHERE (LOWER(u.email)=LOWER(?) OR LOWER(u.username)=LOWER(?)) "
        "AND t.purpose='email_verification' AND t.used_at IS NULL LIMIT 1",
        (identifier, identifier),
    )
    result = cur.fetchone() is not None
    conn.close()
    return result


def _email_verification_digest(code, user_id):
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    payload = f"email_verification:{user_id}:{code}".encode("ascii")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _issue_email_verification_code(user_id, email):
    """Store only a keyed digest for a short-lived, one-time email code."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM password_reset_tokens WHERE user_id=? AND purpose='email_verification'",
        (user_id,),
    )
    cur.execute(
        "INSERT INTO password_reset_tokens(user_id, token, expires_at, created_at, attempt_count, purpose) "
        "VALUES (?, ?, ?, ?, 0, 'email_verification')",
        (user_id, _email_verification_digest(code, user_id),
         (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
         now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    return _send_verification_email(email, code)


def _send_verification_email(email, code):
    return _send_auth_code_email(
        email,
        "Verify your Agri-Direct email",
        f"Your Agri-Direct email verification code is: {code}\n\n"
        "It expires in 10 minutes and can only be used once.",
    )


def _send_auth_code_email(email, subject, body):
    app = current_app._get_current_object()
    if app.config.get("MAIL_SUPPRESS_SEND", True):
        logger.warning("Authentication email delivery is suppressed; configure SMTP to deliver codes.")
        return False
    message = Message(
        subject=subject,
        recipients=[email],
        body=body,
        sender=app.config.get("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME", "noreply@agridirect.local"),
    )
    try:
        mail.send(message)
        return True
    except smtplib.SMTPAuthenticationError as error:
        logger.error("Authentication email rejected by SMTP authentication (code %s).", error.smtp_code)
        return False
    except smtplib.SMTPRecipientsRefused:
        # Do not log the exception: it contains the recipient address.
        logger.error("Authentication email recipient was rejected by the SMTP provider.")
        return False
    except smtplib.SMTPResponseException as error:
        # Provider response text may contain account or address details; log only its code.
        logger.error("Authentication email rejected by SMTP (code %s).", error.smtp_code)
        return False
    except (smtplib.SMTPException, OSError) as error:
        logger.error("Authentication email delivery failed (%s).", type(error).__name__)
        return False
    except Exception as error:
        logger.error("Authentication email delivery failed (%s).", type(error).__name__)
        return False


@limiter.limit("5 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"])
def verify_email():
    """Accept a verification code or resend one for the pending registration."""
    email = session.get("email_verification_email")
    if not email:
        flash("Register an account before verifying an email address.")
        return redirect(url_for("register"))
    _ensure_password_reset_table()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?)", (email,))
    user = cur.fetchone()
    conn.close()
    if not user:
        session.pop("email_verification_email", None)
        flash("Your registration expired before verification. Please register again.")
        return redirect(url_for("register"))
    if request.method == "POST":
        if request.form.get("action") == "resend":
            if user:
                sent = _issue_email_verification_code(user["id"], email)
            else:
                sent = False
            if sent:
                flash("A new verification code has been sent.")
            else:
                flash("We could not send the code. Check your email settings or try again later.")
            return redirect(url_for("verify_email"))

        code = (request.form.get("code") or "").strip()
        conn = get_db()
        cur = conn.cursor()
        digest = _email_verification_digest(code, user["id"]) if (
            user and len(code) == 6 and code.isdigit()
        ) else ""
        cur.execute(
            "SELECT t.id, t.user_id, t.expires_at, t.attempt_count FROM password_reset_tokens t "
            "JOIN users u ON u.id=t.user_id WHERE LOWER(u.email)=LOWER(?) AND t.token=? "
            "AND t.purpose='email_verification' AND t.used_at IS NULL",
            (email, digest),
        )
        challenge = cur.fetchone()
        if challenge and challenge["attempt_count"] < 5 and challenge["expires_at"]:
            expires = datetime.strptime(str(challenge["expires_at"]), "%Y-%m-%d %H:%M:%S")
            if expires.replace(tzinfo=timezone.utc) >= datetime.now(timezone.utc):
                cur.execute("UPDATE password_reset_tokens SET used_at=? WHERE id=? AND used_at IS NULL",
                            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), challenge["id"]))
                cur.execute(
                    "UPDATE users SET is_verified=?, is_active=? WHERE id=?",
                    (True, True, challenge["user_id"]),
                )
                conn.commit()
                conn.close()
                session.clear()
                flash("Email verified. You can now log in.")
                return redirect(url_for("login"))
        cur.execute(
            "UPDATE password_reset_tokens SET attempt_count=attempt_count+1 "
            "WHERE purpose='email_verification' AND used_at IS NULL "
            "AND user_id=?",
            (user["id"],),
        )
        conn.commit()
        conn.close()
        flash("That code is invalid, expired, or has reached its attempt limit.")
    return render_template("verify_email.html")


def _create_reset_code_for_user(user_id):
    """Create a one-time six-digit recovery code that expires after ten minutes."""
    _ensure_password_reset_table()
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM password_reset_tokens WHERE user_id = ? AND purpose='password_reset'", (user_id,))
    cur.execute(
        "INSERT INTO password_reset_tokens(user_id, token, expires_at, created_at, attempt_count, purpose) "
        "VALUES (?, ?, ?, ?, 0, 'password_reset')",
        (user_id, _reset_code_digest(code), expires_at, now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    return code


def _send_reset_email(email, code):
    """Email the recovery code without including a password-reset link."""
    return _send_auth_code_email(
        email,
        "Your Agri-Direct password reset code",
        "You requested a password reset for your Agri-Direct account.\n\n"
        f"Your verification code is: {code}\n\n"
        "Enter this code in the Agri-Direct app to continue. It expires in 10 minutes. "
        "If you did not request this, you can ignore this message.",
    )


@limiter.limit("3 per hour", methods=["POST"])
def forgot_password():
    """Request a password reset code for an existing account."""
    _ensure_password_reset_table()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            flash("Enter the email associated with your account")
            return render_template("forgot_password.html")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, email FROM users WHERE LOWER(email)=?", (email,))
        user = cur.fetchone()
        conn.close()

        session.pop("password_reset_user_id", None)
        session.pop("password_reset_expires_at", None)
        session.pop("password_reset_email", None)

        if user:
            code = _create_reset_code_for_user(user["id"])
            _send_reset_email(email, code)

        session["password_reset_email"] = email
        flash("If an account exists for that email address, a verification code has been sent.")
        return redirect(url_for("verify_reset_code"))

    return render_template("forgot_password.html")


@limiter.limit("5 per minute", methods=["POST"])
def verify_reset_code():
    """Verify the emailed code and authorize an in-app password change."""
    _ensure_password_reset_table()
    email = session.get("password_reset_email")
    if not email:
        flash("Enter your email address to request a verification code.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        if len(code) != 6 or not code.isdigit():
            flash("Enter the six-digit verification code from your email.")
            return render_template("verify_reset_code.html")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT t.id, t.user_id, t.expires_at, t.attempt_count "
            "FROM password_reset_tokens t JOIN users u ON u.id = t.user_id "
            "WHERE LOWER(u.email) = ? AND t.token = ? AND t.used_at IS NULL "
            "AND t.purpose='password_reset'",
            (email, _reset_code_digest(code)),
        )
        reset_record = cur.fetchone()
        if reset_record and reset_record["attempt_count"] < 5 and reset_record["expires_at"]:
            expires_at = datetime.strptime(str(reset_record["expires_at"]), "%Y-%m-%d %H:%M:%S")
            if expires_at.replace(tzinfo=timezone.utc) >= datetime.now(timezone.utc):
                cur.execute(
                    "UPDATE password_reset_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL "
                    "AND purpose='password_reset'",
                    (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), reset_record["id"]),
                )
                conn.commit()
                user_id = reset_record["user_id"]
                conn.close()
                session.pop("password_reset_email", None)
                session["password_reset_user_id"] = user_id
                session["password_reset_expires_at"] = (
                    datetime.now(timezone.utc) + timedelta(minutes=10)
                ).timestamp()
                return redirect(url_for("reset_password"))

        cur.execute(
            "UPDATE password_reset_tokens SET attempt_count = attempt_count + 1 "
            "WHERE purpose='password_reset' AND "
            "user_id = (SELECT id FROM users WHERE LOWER(email) = ?) "
            "AND used_at IS NULL",
            (email,),
        )
        conn.commit()
        conn.close()
        flash("That verification code is invalid, expired, or has already been used.")
        return render_template("verify_reset_code.html")

    return render_template("verify_reset_code.html")


@limiter.limit("5 per hour", methods=["POST"])
def reset_password():
    """Set a new password after successful in-app code verification."""
    user_id = session.get("password_reset_user_id")
    expires_at = session.get("password_reset_expires_at")
    if not user_id or not expires_at or expires_at < datetime.now(timezone.utc).timestamp():
        session.pop("password_reset_user_id", None)
        session.pop("password_reset_expires_at", None)
        flash("Verify a current email code before choosing a new password.")
        return redirect(url_for("forgot_password"))

    if request.method == "GET":
        return render_template("reset_password.html")

    new_password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if new_password != confirm_password:
        flash("Passwords do not match")
        return render_template("reset_password.html")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        session.pop("password_reset_user_id", None)
        session.pop("password_reset_expires_at", None)
        flash("The account could not be verified. Please request a new code.")
        return redirect(url_for("forgot_password"))

    password_error = password_policy_error(
        new_password,
        (user["username"], (user["email"] or "").split("@", 1)[0]),
    )
    if password_error:
        conn.close()
        flash(password_error)
        return render_template("reset_password.html")

    hashed_password = generate_password_hash(new_password)
    cur.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_password, user_id))
    conn.commit()
    conn.close()
    session.clear()
    flash("Password reset successful. Please log in with your new password.")
    return redirect(url_for("login"))


@limiter.limit("5 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"])
def get_token():
    """Generate JWT token for authenticated users"""
    username = request.form.get("username")
    password = request.form.get("password")
    
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, password, role, is_active, is_verified FROM users WHERE username=?",
        (username,),
    )
    user = cur.fetchone()
    conn.close()
    
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid credentials"}), 401
    if not user["is_verified"]:
        _ensure_password_reset_table()
        if _has_pending_email_verification(username):
            return jsonify({"error": "Email verification is required"}), 403
    if not user["is_active"]:
        return jsonify({"error": "Account is inactive"}), 403
    g.audit_actor = user["username"]
    g.audit_role = user["role"] or "user"
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
            "location, psgc_location, geotag_location, location_latitude, location_longitude, "
            "location_verified, is_active "
            "FROM users WHERE username=?",
            (username,),
        )
        profile = cur.fetchone()
        if not profile:
            conn.close()
            return jsonify({"error": "The authenticated account could not be found"}), 404
        if not profile["is_active"]:
            conn.close()
            return jsonify({"error": "The authenticated account is inactive"}), 403

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
    
    except Exception as error:
        logger.error("Harvest API request failed (%s)", type(error).__name__)
        return jsonify({"error": "Unable to record harvest. Please try again."}), 500

def logout():
    session.clear()
    return redirect(url_for("login"))

# Preserve decorator ordering from the legacy module.
api_harvest = token_required(api_harvest)

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    application.add_url_rule('/register', endpoint='register', view_func=register_user, methods=['GET', 'POST'])
    application.add_url_rule('/verify-email', endpoint='verify_email', view_func=verify_email, methods=['GET', 'POST'])
    application.add_url_rule('/forgot-password', endpoint='forgot_password', view_func=forgot_password, methods=['GET', 'POST'])
    application.add_url_rule('/verify-reset-code', endpoint='verify_reset_code', view_func=verify_reset_code, methods=['GET', 'POST'])
    application.add_url_rule('/reset-password', endpoint='reset_password', view_func=reset_password, methods=['GET', 'POST'])
    application.add_url_rule('/token', endpoint='get_token', view_func=get_token, methods=['POST'])
    application.add_url_rule('/api/harvest', endpoint='api_harvest', view_func=api_harvest, methods=['POST'])
    application.add_url_rule('/logout', endpoint='logout', view_func=logout)
    application.add_url_rule('/logout/', endpoint='logout', view_func=logout)
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['login', 'register_user', 'verify_email', 'forgot_password', 'verify_reset_code', 'reset_password', 'get_token', 'api_harvest', 'logout']

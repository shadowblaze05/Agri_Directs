"""Profile and account-management routes."""

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image, UnidentifiedImageError
import requests
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from .. import legacy as core
from ..algorithms.reliability_score import seller_reliability_status
from ..extensions import limiter
from ..models.database import get_db
from ..services.auth_service import get_active_user_role
from ..services.admin_notification_service import notify_superadmin
from ..services.face_scanning import (
    FaceScannerUnavailable,
    MAX_FRAME_SIZE_BYTES,
    ensure_face_scanner_ready,
    validate_face_frame,
)
from ..services.geotag_service import (
    resolve_psgc_location,
    reverse_geocode_coordinates,
    validate_coordinates,
)
from ..services.upload_service import save_sanitized_public_image

globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

ALLOWED_PROFILE_IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
PROFILE_PHOTO_CHALLENGE_TTL = 5 * 60
PROFILE_PHOTO_SCAN_MAX_ATTEMPTS = 5
PROFILE_PHOTO_SCAN_MIN_STAGE_SECONDS = 0.5


def _profile_photo_url(user, is_public_profile=False):
    if not user or not user.get("profile_picture"):
        return None

    username = user["username"]
    viewer = session.get("user")
    can_view = (
        bool(user.get("profile_picture_public"))
        or viewer == username
        or (
            viewer
            and get_active_user_role(viewer, get_db) == "admin"
        )
    )
    if is_public_profile and not can_view:
        return None
    return url_for("profile_photo", username=username)


def _profile_photo_file(profile_picture):
    """Resolve a database photo reference to an allowlisted managed file."""
    if not isinstance(profile_picture, str) or not profile_picture:
        return None

    legacy_prefix = "/static/uploads/profiles/"
    if profile_picture.startswith(legacy_prefix):
        filename = profile_picture[len(legacy_prefix):]
        directory = os.path.join(current_app.static_folder, "uploads", "profiles")
    else:
        filename = profile_picture
        directory = os.path.join(current_app.config["UPLOAD_FOLDER"], "profile_photos")

    safe_filename = secure_filename(filename)
    if (
        not safe_filename
        or safe_filename != filename
        or "." not in safe_filename
        or safe_filename.rsplit(".", 1)[-1].lower() not in ALLOWED_PROFILE_IMAGE_FORMATS
    ):
        return None
    return directory, safe_filename


def _remove_generated_photo(path):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            current_app.logger.exception("Unable to remove uncommitted profile photo")


def _clear_profile_photo_after_failed_scan(username):
    conn = get_db()
    try:
        cur = conn.cursor()
        old_photo = cur.execute(
            "SELECT profile_picture FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not old_photo:
            return False
        cur.execute(
            "UPDATE users SET profile_picture=NULL, profile_picture_public=FALSE, "
            "profile_photo_captured_at=NULL, profile_photo_scan_verified_at=NULL "
            "WHERE username=?",
            (username,),
        )
        if cur.rowcount != 1:
            return False
        conn.commit()
    finally:
        conn.close()

    managed_photo = _profile_photo_file(old_photo["profile_picture"])
    if managed_photo:
        old_photo_path = os.path.join(*managed_photo)
        try:
            os.remove(old_photo_path)
        except FileNotFoundError:
            pass
        except OSError:
            current_app.logger.exception(
                "Unable to remove profile photo after a failed scan"
            )
    return True


def _profile_data(cursor, username):
    cursor.execute(
        """SELECT username, first_name, last_name, email, phone_number,
                  profile_picture, bio, role, is_verified, location_latitude,
                  location_longitude, profile_photo_captured_at,
                  profile_photo_scan_verified_at, psgc_location, geotag_location,
                  profile_picture_public
           FROM users WHERE username=?""",
        (username,),
    )
    return cursor.fetchone()


def _seller_reliability(cursor, username):
    cursor.execute(
        "SELECT AVG(buyer_rating) AS average_rating, COUNT(buyer_rating) AS rating_count "
        "FROM marketplace WHERE username=? AND buyer_rating IS NOT NULL",
        (username,),
    )
    summary = cursor.fetchone() or {}
    if not isinstance(summary, dict):
        summary = {}
    average_rating = summary.get("average_rating")
    rating_count = summary.get("rating_count") or 0
    return {
        "score": round(average_rating, 2) if average_rating is not None else None,
        "rating_count": rating_count,
        "status": seller_reliability_status(average_rating),
    }


def _is_valid_photo_movement_sequence(sequence):
    return (
        isinstance(sequence, list)
        and len(sequence) == 5
        and all(isinstance(movement, str) for movement in sequence)
        and sequence[0] == "center"
        and sequence[2] == "center"
        and sequence[4] == "center"
        and {sequence[1], sequence[3]} == {"screen_left", "screen_right"}
    )


def profile():
    """Show the signed-in user's account overview."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    user = _profile_data(cur, session["user"])
    reliability_summary = _seller_reliability(cur, session["user"])
    cur.execute(
        "SELECT COUNT(DISTINCT commodity_id) AS crop_count, COALESCE(SUM(quantity), 0) AS total_quantity "
        "FROM inventory WHERE farmer=?", (session["user"],)
    )
    inventory_summary = cur.fetchone()
    cur.execute(
        "SELECT c.commodity_name AS commodity_name, SUM(i.quantity) AS total_quantity, MAX(i.date_received) AS last_received "
        "FROM inventory i JOIN commodities c ON c.id=i.commodity_id WHERE i.farmer=? GROUP BY i.commodity_id, c.commodity_name ORDER BY last_received DESC LIMIT 4",
        (session["user"],)
    )
    recent_inventory = cur.fetchall()
    conn.close()
    from ..services.profile_service import missing_harvest_profile_requirements
    missing_requirements = missing_harvest_profile_requirements(user)
    return render_template(
        "profile.html",
        user=user,
        reliability_summary=reliability_summary,
        inventory_summary=inventory_summary,
        recent_inventory=recent_inventory,
        missing_profile_requirements=missing_requirements,
        profile_photo_url=_profile_photo_url(user),
        is_public_profile=False,
    )


def seller_profile(username):
    """Show public marketplace contact details without account controls."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    user = _profile_data(cur, username)
    reliability_summary = _seller_reliability(cur, username) if user else None
    conn.close()
    if not user:
        abort(404)

    profile_photo_url = _profile_photo_url(user, is_public_profile=True)
    return render_template(
        "profile.html",
        user=user,
        reliability_summary=reliability_summary,
        is_public_profile=True,
        profile_photo_url=profile_photo_url,
    )


def report_profile(username):
    """Submit a report about a publicly viewable profile."""
    if "user" not in session:
        return redirect(url_for("login"))
    if username == session["user"]:
        flash("You cannot report your own profile.")
        return redirect(url_for("profile"))

    description = request.form.get("description", "").strip()
    if len(description) < 10 or len(description) > 2000:
        flash("Report details must be between 10 and 2,000 characters.")
        return redirect(url_for("seller_profile", username=username))

    evidence = request.files.get("evidence")
    evidence_filename = None
    evidence_original_name = None
    evidence_path = None
    if evidence and evidence.filename:
        evidence_original_name = secure_filename(evidence.filename)[:255]
        if not evidence_original_name:
            flash("Choose an evidence file with a valid filename.", "danger")
            return redirect(url_for("seller_profile", username=username))
        evidence.stream.seek(0, os.SEEK_END)
        evidence_size = evidence.stream.tell()
        evidence.stream.seek(0)
        maximum_size = current_app.config["MAX_PROFILE_REPORT_EVIDENCE_SIZE_BYTES"]
        if not evidence_size or evidence_size > maximum_size:
            maximum_size_mb = maximum_size / (1024 * 1024)
            flash(
                f"Evidence files must be non-empty and no larger than {maximum_size_mb:g} MB.",
                "danger",
            )
            return redirect(url_for("seller_profile", username=username))

    conn = get_db()
    cur = conn.cursor()
    target = cur.execute(
        "SELECT username FROM users WHERE username=?",
        (username,),
    ).fetchone()
    if not target:
        conn.close()
        abort(404)
    if evidence_original_name:
        evidence_filename = uuid.uuid4().hex
        evidence_dir = os.path.join(
            current_app.config["UPLOAD_FOLDER"],
            "profile_report_evidence",
        )
        try:
            os.makedirs(evidence_dir, exist_ok=True)
            evidence_path = os.path.join(evidence_dir, evidence_filename)
            evidence.save(evidence_path)
        except OSError:
            conn.close()
            if evidence_path and os.path.exists(evidence_path):
                os.remove(evidence_path)
            flash("The evidence file could not be saved. Please try again.", "danger")
            return redirect(url_for("seller_profile", username=username))

    committed = False
    try:
        cur.execute(
            """INSERT INTO profile_reports
               (reporter_username, reported_username, description,
                evidence_filename, evidence_original_name)
               VALUES (?, ?, ?, ?, ?)""",
            (
                session["user"], username, description,
                evidence_filename, evidence_original_name,
            ),
        )
        conn.commit()
        committed = True
    finally:
        conn.close()
        if not committed and evidence_path and os.path.exists(evidence_path):
            os.remove(evidence_path)

    notification_sent = notify_superadmin(
        "New Agri-Direct user profile report",
        (
            "A user profile has been reported on Agri-Direct.\n\n"
            f"Reported profile: {username}\n"
            f"Reported by: {session['user']}\n"
            f"Report details: {description}\n\n"
            "Sign in to the Agri-Direct admin console to review the report and any attached evidence:\n"
            f"{url_for('admin_profile_reports', _external=True)}"
        ),
    )
    if notification_sent:
        flash("Your report has been sent to the Agri-Direct super admin.")
    else:
        flash(
            "Your report was submitted and is available in the admin console, "
            "but its email notification could not be sent. Please contact Agri-Direct support.",
            "warning",
        )
    return redirect(url_for("seller_profile", username=username))


def update_profile():
    """Edit all user-maintained fields in the users table."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    user = _profile_data(cur, session["user"])
    if not user:
        conn.close()
        flash("Your account could not be found.")
        return redirect("/login")

    if request.method == "POST":
        if (
            not user["profile_picture"]
            or not user["profile_photo_captured_at"]
            or not user["profile_photo_scan_verified_at"]
        ):
            conn.close()
            flash(
                "Complete the required face scan and save your profile photo "
                "before updating account details.",
                "warning",
            )
            return redirect(url_for("update_profile"))

        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone_number = request.form.get("phone_number", "").strip()
        bio = request.form.get("bio", "").strip()
        current_role = user["role"] or "seller"
        account_role = (
            current_role
            if current_role == "admin"
            else request.form.get("role", "seller" if current_role == "user" else current_role)
        )
        if not first_name or not last_name or not email:
            flash("First name, last name, and email address are required.")
            conn.close()
            return redirect(url_for("update_profile"))
        if "@" not in email:
            flash("Enter a valid email address.")
            conn.close()
            return redirect(url_for("update_profile"))
        if current_role != "admin" and account_role not in {"buyer", "seller"}:
            flash("Choose either Buyer or Seller as your account role.", "danger")
            conn.close()
            return redirect(url_for("update_profile"))

        cur.execute("SELECT username FROM users WHERE email=? AND username<>?", (email, session["user"]))
        if cur.fetchone():
            flash("That email address is already in use.")
            conn.close()
            return redirect(url_for("update_profile"))

        cur.execute(
            "UPDATE users SET first_name=?, last_name=?, email=?, phone_number=?, bio=?, role=?, updated_at=? "
            "WHERE username=?",
            (
                first_name, last_name, email, phone_number or None, bio or None, account_role,
                datetime.now(timezone.utc).isoformat(), session["user"],
            ),
        )
        conn.commit()
        conn.close()
        session["role"] = account_role
        flash("Your profile has been updated successfully.")
        return redirect(url_for("profile"))

    conn.close()
    return render_template(
        "update_profile.html",
        user=user,
        account_role="seller" if user["role"] in (None, "", "user") else user["role"],
        profile_photo_url=_profile_photo_url(user),
    )


def issue_profile_photo_challenge():
    """Create a short-lived, single-use challenge bound to the signed-in user."""
    username = session.get("user")
    if not username:
        return jsonify({"error": "Sign in before capturing a profile photo."}), 401

    try:
        ensure_face_scanner_ready()
    except FaceScannerUnavailable:
        current_app.logger.exception("Profile face scanner is unavailable")
        return jsonify({"error": "Face scanning is temporarily unavailable. Please try again later."}), 503

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    token = secrets.token_urlsafe(32)
    first_turn = secrets.choice(("screen_left", "screen_right"))
    other_turn = "screen_right" if first_turn == "screen_left" else "screen_left"
    movement_sequence = ["center", first_turn, "center", other_turn, "center"]
    expires_iso = (now + timedelta(seconds=PROFILE_PHOTO_CHALLENGE_TTL)).isoformat()
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM profile_photo_challenges WHERE expires_at<=?",
            (now_iso,),
        )
        cur.execute(
            "INSERT INTO profile_photo_challenges "
            "(challenge_hash, username, expires_at, created_at, movement_sequence) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
                username,
                expires_iso,
                now_iso,
                json.dumps(movement_sequence),
            ),
        )
        conn.commit()
    except SQLAlchemyError:
        current_app.logger.exception("Unable to create profile-photo challenge")
        return jsonify({"error": "Unable to prepare a secure photo capture. Please try again."}), 500
    finally:
        conn.close()

    return jsonify({
        "challenge": token,
        "expires_at": expires_iso,
        "movement_sequence": movement_sequence,
    }), 201


def submit_profile_photo_scan_stage():
    """Validate one frame for the next server-selected scan movement."""
    username = session.get("user")
    if not username:
        return jsonify({"error": "Sign in before scanning your profile photo."}), 401

    request.max_content_length = MAX_FRAME_SIZE_BYTES + 32 * 1024
    if request.content_length and request.content_length > MAX_FRAME_SIZE_BYTES + 32 * 1024:
        return jsonify({"error": "The scan frame exceeds the allowed request size."}), 413

    challenge = request.form.get("challenge", "")
    frame = request.files.get("frame")
    if not challenge or len(challenge) > 256 or not frame:
        return jsonify({"error": "A valid challenge and camera frame are required."}), 400

    image_bytes = frame.stream.read(MAX_FRAME_SIZE_BYTES + 1)
    if len(image_bytes) > MAX_FRAME_SIZE_BYTES:
        return jsonify({"error": "The scan frame is too large. Try again."}), 413

    challenge_hash = hashlib.sha256(challenge.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    conn = get_db()
    try:
        challenge_row = conn.cursor().execute(
            "SELECT movement_sequence, current_stage, last_stage_at, created_at, "
            "failed_attempts FROM profile_photo_challenges "
            "WHERE challenge_hash=? AND username=? AND expires_at>? AND consumed_at IS NULL",
            (challenge_hash, username, now_iso),
        ).fetchone()
    except SQLAlchemyError:
        current_app.logger.exception("Unable to read profile-photo scan challenge")
        return jsonify({"error": "Unable to validate the scan. Please try again."}), 500
    finally:
        conn.close()

    if not challenge_row:
        return jsonify({"error": "This scan challenge is invalid, expired, or already used. Request a new one."}), 409

    try:
        movement_sequence = json.loads(challenge_row["movement_sequence"])
        stage_index = int(challenge_row["current_stage"])
        if (
            not _is_valid_photo_movement_sequence(movement_sequence)
            or stage_index < 0
            or stage_index >= len(movement_sequence)
        ):
            return jsonify({"error": "This scan challenge is complete or invalid. Request a new one."}), 409
        last_stage_at = challenge_row["last_stage_at"] or challenge_row["created_at"]
        previous_stage_time = datetime.fromisoformat(last_stage_at)
    except (TypeError, ValueError, json.JSONDecodeError):
        current_app.logger.error("Invalid profile-photo scan challenge state")
        return jsonify({"error": "This scan challenge is invalid. Request a new one."}), 409

    elapsed = (now - previous_stage_time).total_seconds()
    if elapsed < PROFILE_PHOTO_SCAN_MIN_STAGE_SECONDS:
        wait_seconds = PROFILE_PHOTO_SCAN_MIN_STAGE_SECONDS - elapsed
        return jsonify({
            "error": "Wait briefly before capturing the next scan step.",
            "retry_after_seconds": round(wait_seconds, 2),
        }), 409

    expected_movement = movement_sequence[stage_index]
    try:
        validate_face_frame(image_bytes, expected_movement)
    except ValueError as error:
        retry_conn = get_db()
        try:
            retry_cur = retry_conn.cursor()
            retry_cur.execute(
                "UPDATE profile_photo_challenges "
                "SET failed_attempts=failed_attempts+1, "
                "consumed_at=CASE WHEN failed_attempts+1>=? THEN ? ELSE consumed_at END "
                "WHERE challenge_hash=? AND username=? AND current_stage=? "
                "AND expires_at>? AND consumed_at IS NULL",
                (
                    PROFILE_PHOTO_SCAN_MAX_ATTEMPTS,
                    now_iso,
                    challenge_hash,
                    username,
                    stage_index,
                    now_iso,
                ),
            )
            retry_conn.commit()
        except SQLAlchemyError:
            current_app.logger.exception("Unable to record failed profile-photo scan attempt")
            return jsonify({"error": "Unable to validate the scan. Please try again."}), 500
        finally:
            retry_conn.close()
        if retry_cur.rowcount != 1:
            return jsonify({"error": "This scan challenge is invalid or expired. Request a new one."}), 409
        remaining_attempts = max(
            PROFILE_PHOTO_SCAN_MAX_ATTEMPTS - int(challenge_row["failed_attempts"]) - 1,
            0,
        )
        profile_photo_cleared = False
        if remaining_attempts == 0:
            try:
                profile_photo_cleared = _clear_profile_photo_after_failed_scan(username)
            except SQLAlchemyError:
                current_app.logger.exception(
                    "Unable to clear profile photo after a failed scan"
                )
                return jsonify({
                    "error": (
                        "The scan failed, but the current profile photo could not "
                        "be cleared. Please try again or contact support."
                    )
                }), 500
        return jsonify({
            "error": str(error),
            "remaining_attempts": remaining_attempts,
            "challenge_expired": remaining_attempts == 0,
            "profile_photo_cleared": profile_photo_cleared,
        }), 400
    except FaceScannerUnavailable:
        current_app.logger.exception("Profile face scanner became unavailable")
        return jsonify({"error": "Face scanning is temporarily unavailable. Please try again later."}), 503

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE profile_photo_challenges "
            "SET current_stage=current_stage+1, last_stage_at=?, failed_attempts=0 "
            "WHERE challenge_hash=? AND username=? AND current_stage=? "
            "AND expires_at>? AND consumed_at IS NULL",
            (now_iso, challenge_hash, username, stage_index, now_iso),
        )
        if cur.rowcount != 1:
            return jsonify({"error": "This scan step is stale or the challenge has expired. Request a new one."}), 409
        conn.commit()
    except SQLAlchemyError:
        current_app.logger.exception("Unable to advance profile-photo scan challenge")
        return jsonify({"error": "Unable to save scan progress. Please try again."}), 500
    finally:
        conn.close()

    next_stage = stage_index + 1
    complete = next_stage == len(movement_sequence)
    return jsonify({
        "complete": complete,
        "stage": next_stage,
        "total_stages": len(movement_sequence),
        "next_movement": None if complete else movement_sequence[next_stage],
        "message": "Face scan complete." if complete else "Scan step accepted.",
    })


def profile_photo(username):
    """Serve public photos and restrict legacy private photos to their owner/admin."""
    conn = get_db()
    try:
        photo = conn.cursor().execute(
            "SELECT profile_picture, profile_picture_public, is_active "
            "FROM users WHERE username=?",
            (username,),
        ).fetchone()
    finally:
        conn.close()

    if not photo or not photo["is_active"] or not photo["profile_picture"]:
        abort(404)
    viewer = session.get("user")
    is_owner = viewer == username
    is_public = bool(photo["profile_picture_public"])
    if not is_public and not is_owner:
        if not viewer or get_active_user_role(viewer, get_db) != "admin":
            abort(404)

    photo_file = _profile_photo_file(photo["profile_picture"])
    if not photo_file:
        abort(404)
    directory, filename = photo_file
    response = send_from_directory(directory, filename, as_attachment=False)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@limiter.limit("10 per minute")
@limiter.limit("30 per hour")
def issue_profile_photo_challenge_limited():
    return issue_profile_photo_challenge()


@limiter.limit("30 per minute")
@limiter.limit("150 per hour")
def submit_profile_photo_scan_stage_limited():
    return submit_profile_photo_scan_stage()


@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def capture_profile_location():
    """Save a profile image and browser GPS-derived location as self-reported data."""
    username = session.get("user")
    if not username:
        return jsonify({"error": "Sign in before capturing your profile photo."}), 401

    if request.form.get("public_photo_consent") != "yes":
        return jsonify({
            "error": "Consent to displaying the scanned photo on your public profile."
        }), 400

    maximum_size = current_app.config["MAX_PROFILE_PHOTO_SIZE_BYTES"]
    request.max_content_length = maximum_size + 64 * 1024
    if request.content_length and request.content_length > maximum_size + 64 * 1024:
        return jsonify({"error": "Profile photo upload exceeds the allowed request size."}), 413

    challenge = request.form.get("challenge", "")
    if not challenge or len(challenge) > 256:
        return jsonify({"error": "Request a fresh photo-capture challenge and try again."}), 409

    now = datetime.now(timezone.utc)
    conn = get_db()
    try:
        cur = conn.cursor()
        challenge_row = cur.execute(
            "SELECT movement_sequence, current_stage FROM profile_photo_challenges "
            "WHERE challenge_hash=? AND username=? AND expires_at>? AND consumed_at IS NULL",
            (
                hashlib.sha256(challenge.encode("utf-8")).hexdigest(),
                username,
                now.isoformat(),
            ),
        ).fetchone()
        if not challenge_row:
            return jsonify({"error": "This photo-capture challenge is invalid, expired, or already used. Request a new one."}), 409
        try:
            movement_sequence = json.loads(challenge_row["movement_sequence"])
            completed_stages = int(challenge_row["current_stage"])
        except (TypeError, ValueError, json.JSONDecodeError):
            current_app.logger.error("Invalid profile-photo scan completion state")
            return jsonify({"error": "Complete a valid face scan before saving your photo."}), 409
        if (
            not _is_valid_photo_movement_sequence(movement_sequence)
            or completed_stages != len(movement_sequence)
        ):
            return jsonify({"error": "Complete all face-scan steps before saving your photo."}), 409

        cur.execute(
            "UPDATE profile_photo_challenges SET consumed_at=? "
            "WHERE challenge_hash=? AND username=? AND expires_at>? "
            "AND consumed_at IS NULL AND current_stage=?",
            (
                now.isoformat(),
                hashlib.sha256(challenge.encode("utf-8")).hexdigest(),
                username,
                now.isoformat(),
                completed_stages,
            ),
        )
        if cur.rowcount != 1:
            return jsonify({"error": "This photo-capture challenge is invalid, expired, or already used. Request a new one."}), 409
        conn.commit()
    except SQLAlchemyError:
        current_app.logger.exception("Unable to validate profile-photo challenge")
        return jsonify({"error": "Unable to validate the photo capture. Please try again."}), 500
    finally:
        conn.close()

    image = request.files.get("profile_photo")
    if not image or not image.filename:
        return jsonify({"error": "Take a profile photo with the camera before saving your location."}), 400

    safe_original_name = secure_filename(image.filename)
    extension = safe_original_name.rsplit(".", 1)[-1].lower() if "." in safe_original_name else ""
    expected_format = ALLOWED_PROFILE_IMAGE_FORMATS.get(extension)
    if not expected_format:
        return jsonify({"error": "Use a camera-captured PNG, JPG, or WEBP photo."}), 400
    image.stream.seek(0, os.SEEK_END)
    file_size = image.stream.tell()
    image.stream.seek(0)
    if not file_size or file_size > maximum_size:
        maximum_size_mb = maximum_size / (1024 * 1024)
        return jsonify({"error": f"Profile photos must be non-empty and no larger than {maximum_size_mb:g} MB."}), 400
    try:
        with Image.open(image.stream) as opened_image:
            if opened_image.format != expected_format:
                return jsonify({"error": "Photo content does not match its image type."}), 400
            if opened_image.width * opened_image.height > Image.MAX_IMAGE_PIXELS:
                return jsonify({"error": "The photo dimensions exceed the allowed limit."}), 400
            opened_image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return jsonify({"error": "The camera did not provide a valid supported image."}), 400
    finally:
        image.stream.seek(0)
    try:
        validate_face_frame(image.stream.read(MAX_FRAME_SIZE_BYTES + 1), "center")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except FaceScannerUnavailable:
        current_app.logger.exception("Profile face scanner became unavailable")
        return jsonify({"error": "Face scanning is temporarily unavailable. Please try again later."}), 503
    finally:
        image.stream.seek(0)

    latitude_value = request.form.get("latitude")
    longitude_value = request.form.get("longitude")
    captured_at_value = request.form.get("captured_at", "")
    try:
        latitude, longitude = validate_coordinates(latitude_value, longitude_value)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not captured_at_value:
        return jsonify({"error": "Capture GPS at the same time as your profile photo."}), 400
    try:
        captured_at = datetime.fromisoformat(captured_at_value.replace("Z", "+00:00"))
    except ValueError:
        return jsonify({"error": "The GPS capture timestamp is invalid."}), 400
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    if (now - captured_at).total_seconds() > 600 or (captured_at - now).total_seconds() > 300:
        return jsonify({"error": "Capture a new photo and GPS location before saving."}), 400

    try:
        geotag_location = reverse_geocode_coordinates(latitude, longitude)
    except requests.RequestException:
        return jsonify({
            "error": "Could not resolve your GPS location right now. Check your connection and try again."
        }), 502
    except ValueError as error:
        return jsonify({"error": str(error)}), 422

    try:
        psgc_location = resolve_psgc_location(geotag_location)
    except (requests.RequestException, ValueError):
        psgc_location = None

    existing_conn = get_db()
    try:
        old_photo = existing_conn.cursor().execute(
            "SELECT profile_picture FROM users WHERE username=?",
            (username,),
        ).fetchone()
    finally:
        existing_conn.close()
    if not old_photo:
        return jsonify({"error": "Your account could not be found."}), 404

    filename = f"{secrets.token_hex(16)}.{extension}"
    profile_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "profile_photos")
    temporary_path = os.path.join(profile_dir, f".{secrets.token_hex(16)}.tmp")
    image_path = os.path.join(profile_dir, filename)
    try:
        os.makedirs(profile_dir, exist_ok=True)
        save_sanitized_public_image(image, temporary_path, expected_format, maximum_size)
        os.replace(temporary_path, image_path)
    except (OSError, ValueError):
        current_app.logger.exception("Unable to save sanitized profile photo")
        _remove_generated_photo(temporary_path)
        _remove_generated_photo(image_path)
        return jsonify({"error": "The profile photo could not be saved safely. Please try again."}), 500

    captured_at_iso = captured_at.astimezone(timezone.utc).isoformat()
    conn = None
    committed = False
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET profile_picture=?, profile_picture_public=TRUE, "
            "profile_photo_captured_at=?, profile_photo_scan_verified_at=?, "
            "location=?, psgc_location=?, geotag_location=?, "
            "location_latitude=?, location_longitude=?, location_verified=FALSE, "
            "location_verified_at=NULL, updated_at=? WHERE username=?",
            (
                filename, captured_at_iso, now.isoformat(), psgc_location,
                psgc_location, geotag_location, latitude, longitude,
                now.isoformat(), username,
            ),
        )
        if cur.rowcount:
            conn.commit()
            committed = True
    except SQLAlchemyError:
        current_app.logger.exception("Unable to update profile photo and location")
        return jsonify({"error": "The profile update failed. Your previous photo and location were kept."}), 500
    finally:
        try:
            if conn:
                conn.close()
        finally:
            if not committed:
                _remove_generated_photo(image_path)

    if not committed:
        return jsonify({"error": "Your account could not be found."}), 404

    old_photo_file = _profile_photo_file(old_photo["profile_picture"])
    if old_photo_file:
        old_directory, old_filename = old_photo_file
        old_path = os.path.join(old_directory, old_filename)
        if old_path != image_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                current_app.logger.exception("Unable to remove superseded profile photo")

    return jsonify({
        "status": "captured",
        "captured_at": captured_at_iso,
        "location": psgc_location,
        "geotag_location": geotag_location,
        "psgc_location": psgc_location,
        "profile_photo_url": url_for("profile_photo", username=username),
        "message": (
            "Profile photo was saved and is publicly visible. Self-reported GPS location was saved. "
            + (
                "A matching PSGC location was found."
                if psgc_location
                else "No PSGC match was found; the submitted place is still saved."
            )
            + " Coordinates and capture time are not independently verified."
        ),
    })


def register(application):
    application.add_url_rule('/profile', endpoint='profile', view_func=profile)
    application.add_url_rule('/profile/<username>', endpoint='seller_profile', view_func=seller_profile)
    application.add_url_rule('/profile/<username>/report', endpoint='report_profile', view_func=report_profile, methods=['POST'])
    application.add_url_rule('/profile/update', endpoint='update_profile', view_func=update_profile, methods=['GET', 'POST'])
    application.add_url_rule('/profile/photo/challenge', endpoint='issue_profile_photo_challenge', view_func=issue_profile_photo_challenge_limited, methods=['POST'])
    application.add_url_rule('/profile/photo/scan-stage', endpoint='submit_profile_photo_scan_stage', view_func=submit_profile_photo_scan_stage_limited, methods=['POST'])
    application.add_url_rule('/profile/photo/<username>', endpoint='profile_photo', view_func=profile_photo)
    application.add_url_rule('/profile/location', endpoint='capture_profile_location', view_func=capture_profile_location, methods=['POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['profile', 'seller_profile', 'report_profile', 'update_profile', 'issue_profile_photo_challenge', 'submit_profile_photo_scan_stage', 'profile_photo', 'capture_profile_location']

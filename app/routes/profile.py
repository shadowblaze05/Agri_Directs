"""Profile and account-management routes."""

import os
import uuid
from datetime import datetime, timezone

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from PIL import Image, UnidentifiedImageError
import requests

from .. import legacy as core
from ..algorithms.reliability_score import seller_reliability_status
from ..models.database import get_db
from ..services.geotag_service import (
    resolve_psgc_location,
    reverse_geocode_coordinates,
    validate_coordinates,
)

globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

ALLOWED_PROFILE_IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}


def _profile_data(cursor, username):
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    return cursor.fetchone()


def _seller_reliability(cursor, username):
    cursor.execute(
        "SELECT AVG(buyer_rating) AS average_rating, COUNT(buyer_rating) AS rating_count "
        "FROM marketplace WHERE username=? AND buyer_rating IS NOT NULL",
        (username,),
    )
    summary = cursor.fetchone()
    average_rating = summary["average_rating"] if summary else None
    return {
        "score": round(average_rating, 2) if average_rating is not None else None,
        "rating_count": summary["rating_count"] if summary else 0,
        "status": seller_reliability_status(average_rating),
    }


def profile():
    """Show the signed-in user's account overview."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    user = _profile_data(cur, session["user"])
    reliability_summary = _seller_reliability(cur, session["user"])
    cur.execute(
        "SELECT COUNT(DISTINCT crop_id) AS crop_count, COALESCE(SUM(quantity), 0) AS total_quantity "
        "FROM inventory WHERE farmer=?", (session["user"],)
    )
    inventory_summary = cur.fetchone()
    cur.execute(
        "SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total_quantity, MAX(i.date_received) AS last_received "
        "FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.farmer=? GROUP BY i.crop_id, c.crops_name ORDER BY last_received DESC LIMIT 4",
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
    )


def seller_profile(username):
    """Show marketplace contact details for a seller without account controls."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    user = _profile_data(cur, username)
    reliability_summary = _seller_reliability(cur, username) if user else None
    conn.close()
    if not user:
        abort(404)

    return render_template(
        "profile.html",
        user=user,
        reliability_summary=reliability_summary,
        is_public_profile=True,
    )


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
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone_number = request.form.get("phone_number", "").strip()
        bio = request.form.get("bio", "").strip()
        if not first_name or not last_name or not email:
            flash("First name, last name, and email address are required.")
            conn.close()
            return redirect(url_for("update_profile"))
        if "@" not in email:
            flash("Enter a valid email address.")
            conn.close()
            return redirect(url_for("update_profile"))

        cur.execute("SELECT username FROM users WHERE email=? AND username<>?", (email, session["user"]))
        if cur.fetchone():
            flash("That email address is already in use.")
            conn.close()
            return redirect(url_for("update_profile"))

        cur.execute(
            "UPDATE users SET first_name=?, last_name=?, email=?, phone_number=?, bio=?, updated_at=? "
            "WHERE username=?",
            (
                first_name, last_name, email, phone_number or None, bio or None,
                datetime.now(timezone.utc).isoformat(), session["user"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Your profile has been updated successfully.")
        return redirect(url_for("profile"))

    conn.close()
    return render_template("update_profile.html", user=user)


def capture_profile_location():
    """Save a camera-captured profile photo and its browser GPS-derived location."""
    if "user" not in session:
        return jsonify({"error": "Sign in before capturing your profile photo."}), 401

    image = request.files.get("profile_photo")
    if not image or not image.filename:
        return jsonify({"error": "Take a profile photo with the camera before saving your location."}), 400

    extension = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else ""
    expected_format = ALLOWED_PROFILE_IMAGE_FORMATS.get(extension)
    if not expected_format:
        return jsonify({"error": "Use a camera-captured PNG, JPG, or WEBP photo."}), 400
    image.stream.seek(0, os.SEEK_END)
    file_size = image.stream.tell()
    image.stream.seek(0)
    if not file_size or file_size > core.app.config["MAX_PROFILE_PHOTO_SIZE_BYTES"]:
        maximum_size_mb = core.app.config["MAX_PROFILE_PHOTO_SIZE_BYTES"] / (1024 * 1024)
        return jsonify({"error": f"Profile photos must be non-empty and no larger than {maximum_size_mb:g} MB."}), 400
    try:
        with Image.open(image.stream) as opened_image:
            if opened_image.format != expected_format:
                return jsonify({"error": "Photo content does not match its image type."}), 400
            opened_image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return jsonify({"error": "The camera did not provide a valid supported image."}), 400
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
    now = datetime.now(timezone.utc)
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

    filename = f"{uuid.uuid4().hex}.{extension}"
    profile_dir = os.path.join(core.app.static_folder, "uploads", "profiles")
    os.makedirs(profile_dir, exist_ok=True)
    image.save(os.path.join(profile_dir, filename))
    captured_at_iso = captured_at.astimezone(timezone.utc).isoformat()
    verified_at = now.isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET profile_picture=?, profile_photo_captured_at=?, location=?, "
        "psgc_location=?, geotag_location=?, "
        "location_latitude=?, location_longitude=?, location_verified=1, "
        "location_verified_at=?, updated_at=? WHERE username=?",
        (
            f"/static/uploads/profiles/{filename}", captured_at_iso, psgc_location,
            psgc_location, geotag_location, latitude, longitude, verified_at, verified_at,
            session["user"],
        ),
    )
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"error": "Your account could not be found."}), 404
    conn.commit()
    conn.close()
    return jsonify({
        "status": "captured",
        "captured_at": captured_at_iso,
        "location": psgc_location,
        "geotag_location": geotag_location,
        "psgc_location": psgc_location,
        "message": (
            "Profile photo and GPS-derived location saved. "
            + (
                "A matching PSGC location was found."
                if psgc_location
                else "No PSGC match was found; the GPS-derived place is still saved."
            )
            + " This does not verify land ownership."
        ),
    })


def register(application):
    application.add_url_rule('/profile', endpoint='profile', view_func=profile)
    application.add_url_rule('/profile/<username>', endpoint='seller_profile', view_func=seller_profile)
    application.add_url_rule('/profile/update', endpoint='update_profile', view_func=update_profile, methods=['GET', 'POST'])
    application.add_url_rule('/profile/location', endpoint='capture_profile_location', view_func=capture_profile_location, methods=['POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['profile', 'seller_profile', 'update_profile', 'capture_profile_location']

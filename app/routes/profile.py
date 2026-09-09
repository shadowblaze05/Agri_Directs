"""Profile and account-management routes."""

import os
import uuid
from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from .. import legacy as core
from ..models.database import get_db

globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

ALLOWED_PROFILE_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def _profile_data(cursor, username):
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    return cursor.fetchone()


def profile():
    """Show the signed-in user's account overview."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    user = _profile_data(cur, session["user"])
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
    return render_template("profile.html", user=user, inventory_summary=inventory_summary, recent_inventory=recent_inventory)


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
        location = request.form.get("location", "").strip()

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

        profile_picture = user.get("profile_picture")
        image = request.files.get("profile_picture")
        if image and image.filename:
            extension = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else ""
            if extension not in ALLOWED_PROFILE_IMAGE_EXTENSIONS:
                flash("Use a PNG, JPG, JPEG, WEBP, or GIF image for your profile photo.")
                conn.close()
                return redirect(url_for("update_profile"))
            filename = secure_filename(f"{session['user']}-{uuid.uuid4().hex[:12]}.{extension}")
            profile_dir = os.path.join(core.app.static_folder, "uploads", "profiles")
            os.makedirs(profile_dir, exist_ok=True)
            image.save(os.path.join(profile_dir, filename))
            profile_picture = f"/static/uploads/profiles/{filename}"

        cur.execute(
            "UPDATE users SET first_name=?, last_name=?, email=?, phone_number=?, bio=?, location=?, profile_picture=?, updated_at=? "
            "WHERE username=?",
            (first_name, last_name, email, phone_number or None, bio or None, location or None,
             profile_picture, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session["user"]),
        )
        conn.commit()
        conn.close()
        flash("Your profile has been updated successfully.")
        return redirect(url_for("profile"))

    conn.close()
    return render_template("update_profile.html", user=user)


def register(application):
    application.add_url_rule('/profile', endpoint='profile', view_func=profile)
    application.add_url_rule('/profile/update', endpoint='update_profile', view_func=update_profile, methods=['GET', 'POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['profile', 'update_profile']

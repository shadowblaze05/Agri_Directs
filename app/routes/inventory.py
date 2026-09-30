"""Inventory HTTP routes.

Handlers retain the legacy SQL and template behavior while living in a domain module.
"""

import csv
import os
import uuid
from datetime import datetime, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, send_from_directory, session
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from .. import legacy as core
from ..legacy import app, get_db, logger, update_analytics
from ..services.geotag_service import validate_coordinates, verify_crop_location
from ..services.profile_service import missing_harvest_profile_requirements

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})


ALLOWED_CROP_PHOTO_FORMATS = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "webp": "WEBP",
}


def _save_crop_photo(uploaded_file):
    """Validate and privately store one crop evidence image."""
    extension = (
        uploaded_file.filename.rsplit(".", 1)[-1].lower()
        if uploaded_file.filename and "." in uploaded_file.filename
        else ""
    )
    expected_format = ALLOWED_CROP_PHOTO_FORMATS.get(extension)
    if not expected_format:
        raise ValueError("Choose a PNG, JPG, JPEG, or WEBP crop photo.")

    uploaded_file.stream.seek(0, os.SEEK_END)
    file_size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    if file_size > current_app.config["MAX_CROP_PHOTO_SIZE_BYTES"]:
        maximum_size_mb = current_app.config["MAX_CROP_PHOTO_SIZE_BYTES"] / (1024 * 1024)
        raise ValueError(f"Crop photos must be {maximum_size_mb:g} MB or smaller.")
    if file_size == 0:
        raise ValueError("The selected crop photo is empty.")

    try:
        with Image.open(uploaded_file.stream) as image:
            if image.format != expected_format:
                raise ValueError("The selected file content does not match its image type.")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("The selected file is not a valid supported image.") from error
    finally:
        uploaded_file.stream.seek(0)

    filename = f"{uuid.uuid4().hex}.{extension}"
    evidence_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "crop_evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    uploaded_file.save(os.path.join(evidence_dir, filename))
    return filename


def _parse_gps_capture(form):
    latitude_text = form.get("latitude", "").strip()
    longitude_text = form.get("longitude", "").strip()
    captured_at_text = form.get("gps_captured_at", "").strip()

    if not latitude_text and not longitude_text:
        return None, None, None
    if not latitude_text or not longitude_text:
        raise ValueError("Both latitude and longitude are required for a GPS capture.")

    latitude, longitude = validate_coordinates(latitude_text, longitude_text)
    if not captured_at_text:
        return latitude, longitude, None
    try:
        captured_at = datetime.fromisoformat(captured_at_text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("The GPS capture timestamp is invalid.") from None
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return latitude, longitude, captured_at.isoformat()


def inventory():
    """Display the signed-in user's harvest inventory as a dedicated workspace."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total_quantity, MAX(i.date_received) AS last_received, MAX(i.location) AS location "
        "FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.farmer=? GROUP BY i.crop_id, c.crops_name ORDER BY last_received DESC",
        (session["user"],),
    )
    items = cur.fetchall()
    cur.execute(
        "SELECT COUNT(DISTINCT crop_id) AS crop_count, COALESCE(SUM(quantity), 0) AS total_quantity "
        "FROM inventory WHERE farmer=?", (session["user"],)
    )
    summary = cur.fetchone()
    conn.close()
    return render_template("inventory.html", items=items, summary=summary)

def inventory_buy():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    # Allow any logged-in user to manage their own posted inventory

    data = request.get_json() or {}
    crop_name = str(data.get("crop_name", "")).strip()
    quantity = data.get("quantity")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a valid number"}), 400

    if not crop_name:
        return jsonify({"error": "Crop name is required"}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than zero"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.farmer=? AND c.crops_name=?", (session["user"], crop_name))
    row = cur.fetchone()
    total = row["total"] or 0

    if quantity > total:
        conn.close()
        return jsonify({"error": "Buy quantity exceeds available inventory"}), 400

    needed = quantity
    cur.execute(
        "SELECT i.id, i.quantity FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.farmer=? AND c.crops_name=? ORDER BY i.date_received DESC",
        (session["user"], crop_name)
    )
    rows = cur.fetchall()

    for item in rows:
        if needed <= 0:
            break
        item_qty = item["quantity"]
        if item_qty <= needed:
            cur.execute("DELETE FROM inventory WHERE id=?", (item["id"],))
            needed -= item_qty
        else:
            cur.execute("UPDATE inventory SET quantity=? WHERE id=?", (item_qty - needed, item["id"]))
            needed = 0

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Inventory updated after purchase"})

def inventory_edit_crop():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    # Allow any logged-in user to edit their own posted inventory

    data = request.get_json() or {}
    crop_name = str(data.get("crop_name", "")).strip()
    quantity = data.get("quantity")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a valid number"}), 400

    if not crop_name:
        return jsonify({"error": "Crop name is required"}), 400
    if quantity < 0:
        return jsonify({"error": "Quantity cannot be negative"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(i.quantity) AS total FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.farmer=? AND c.crops_name=?", (session["user"], crop_name))
    row = cur.fetchone()
    current_total = row["total"] or 0

    if quantity == current_total:
        conn.close()
        return jsonify({"status": "success", "message": "Inventory unchanged"})

    if quantity > current_total:
        add_amount = quantity - current_total
        cur.execute("SELECT location FROM users WHERE username=?", (session["user"],))
        user_loc = cur.fetchone()["location"]
        cur.execute(
            "INSERT INTO inventory(crop_id,quantity,farmer,date_received,location) SELECT id, ?, ?, ?, ? FROM crops WHERE crops_name=?",
            (add_amount, session["user"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_loc, crop_name)
        )
    else:
        remove_amount = current_total - quantity
        cur.execute(
            "SELECT i.id, i.quantity FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.farmer=? AND c.crops_name=? ORDER BY i.date_received DESC",
            (session["user"], crop_name)
        )
        rows = cur.fetchall()
        needed = remove_amount
        for item in rows:
            if needed <= 0:
                break
            item_qty = item["quantity"]
            if item_qty <= needed:
                cur.execute("DELETE FROM inventory WHERE id=?", (item["id"],))
                needed -= item_qty
            else:
                cur.execute("UPDATE inventory SET quantity=? WHERE id=?", (item_qty - needed, item["id"]))
                needed = 0

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Inventory adjusted successfully"})

def inventory_delete_crop():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    # Allow any logged-in user to delete their own posted inventory

    data = request.get_json() or {}
    crop_name = str(data.get("crop_name", "")).strip()

    if not crop_name:
        return jsonify({"error": "Crop name is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM inventory WHERE farmer=? AND crop_id=(SELECT id FROM crops WHERE crops_name=?)", (session["user"], crop_name))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Crop inventory deleted"})

def edit_inventory(item_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT i.*, c.crops_name AS crop_name FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.id=?", (item_id,))
    item = cur.fetchone()

    if not item:
        conn.close()
        flash("Inventory item not found")
        return redirect("/dashboard")

    can_modify = session.get("role") == "admin" or (item["farmer"] == session["user"])
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

        cur.execute("UPDATE inventory SET crop_id=(SELECT id FROM crops WHERE crops_name=?), quantity=? WHERE id=?",
                    (cropped_name, quantity, item_id))
        conn.commit()
        conn.close()
        flash("Inventory item updated successfully")
        return redirect("/dashboard")

    conn.close()
    return render_template("edit_inventory.html", item=item)

def delete_inventory(item_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT i.*, c.crops_name AS crop_name FROM inventory i JOIN crops c ON c.id=i.crop_id WHERE i.id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        conn.close()
        flash("Inventory item not found")
        return redirect("/dashboard")

    can_modify = session.get("role") == "admin" or (item["farmer"] == session["user"])
    if not can_modify:
        conn.close()
        flash("You are not allowed to delete this item")
        return redirect("/dashboard")

    cur.execute("DELETE FROM inventory WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    flash("Inventory item deleted")
    return redirect("/dashboard")

def upload():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT first_name, last_name, email, profile_picture, profile_photo_captured_at, "
        "location, psgc_location, geotag_location, location_latitude, location_longitude, location_verified "
        "FROM users WHERE username=?",
        (session["user"],),
    )
    user = cur.fetchone()
    missing_requirements = missing_harvest_profile_requirements(user)
    if missing_requirements:
        conn.close()
        flash(
            "Complete your profile before uploading harvest: "
            + ", ".join(missing_requirements)
            + ".",
            "warning",
        )
        return redirect("/profile/update")
    location = user["location"] if user else None

    if request.method == "POST":
        file = request.files.get("file")
        crop_id = request.form.get("crop_id")
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
                            
                            cur.execute(
                                "SELECT id FROM crops WHERE crops_name=?",
                                (crop,)
                            )

                            crop_record = cur.fetchone()

                            if not crop_record:
                                flash(f"Crop '{crop}' not found.")
                                continue

                            crop_id = crop_record[0]
                            
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

                            try:
                                row_date = cleaned_row.get("date_received", "").strip()
                                if row_date:
                                    date_received = datetime.strptime(row_date, "%Y-%m-%d").strftime("%Y-%m-%d %H:%M:%S")
                                else:
                                    date_received = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                date_received = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            cur.execute("""
                            INSERT INTO inventory(
                                crop_id,
                                quantity,
                                farmer,
                                date_received,
                                location,
                                verification_status,
                                verification_notes
                            )
                            VALUES(?,?,?,?,?,?,?)
                            """, (
                                crop_id,
                                quantity,
                                session["user"],
                                date_received,
                                location,
                                "manual_review",
                                "CSV import does not include browser GPS capture or crop photo evidence.",
                            ))
                            processed_any = True

                        except Exception as e:
                            logger.error(f"Error processing row: {row}, {e}")
                            flash(f"Error processing CSV row: {row}")

                if processed_any:
                    conn.commit()
                    update_analytics()
                    flash("CSV upload successful!")
                    logger.info(f"User {session['user']} uploaded {filename}")
                else:
                    flash("CSV upload completed, but no valid records were added.")

            except Exception as e:
                flash(f"Error processing file: {str(e)}")
                logger.error(f"Upload error: {str(e)}")
                conn.close()
                return redirect(request.url)

        elif crop_id:
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

            try:
                latitude, longitude, capture_time = _parse_gps_capture(request.form)
            except ValueError as error:
                flash(str(error))
                conn.close()
                return redirect(request.url)

            photo_path = None
            profile_is_verified = bool(user and user["location_verified"])
            verification_status, distance = verify_crop_location(
                user["location_latitude"] if profile_is_verified else None,
                user["location_longitude"] if profile_is_verified else None,
                latitude,
                longitude,
                current_app.config["MAX_CROP_DISTANCE_METERS"],
            )
            notes = []
            if not profile_is_verified:
                notes.append("Farmer has no captured reference location.")
            if latitude is None or capture_time is None:
                notes.append("Harvest GPS capture is missing or incomplete.")
            if notes:
                verification_status = "manual_review"

            cur.execute("""
            INSERT INTO inventory(
                crop_id,
                quantity,
                farmer,
                date_received,
                location,
                photo_path,
                latitude,
                longitude,
                capture_time,
                distance_from_user,
                verification_status,
                verification_notes
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                crop_id,
                quantity,
                session["user"],
                date_received,
                location,
                photo_path,
                latitude,
                longitude,
                capture_time,
                distance,
                verification_status,
                " ".join(notes) or None,
            ))
            conn.commit()
            update_analytics()
            processed_any = True
            distance_message = (
                f" Distance from your captured reference location: {distance / 1000:.2f} km."
                if distance is not None else ""
            )
            flash(
                f"Harvest entry added. Location status: {verification_status.replace('_', ' ')}."
                f"{distance_message} Allowed distance: "
                f"{current_app.config['MAX_CROP_DISTANCE_KM']:g} km. "
                "Geographic proximity is not proof of crop ownership."
            )
            logger.info(f"User {session['user']} manually posted crop {crop_id} x{quantity}")

        else:
            flash("Please upload a CSV file or enter harvest details manually.")
            conn.close()
            return redirect(request.url)

        if processed_any:
            return redirect("/upload")
    
    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    crops = cur.fetchall()

    conn.close()
    return render_template(
        "upload.html",
        crops=crops,
        max_distance_km=current_app.config["MAX_CROP_DISTANCE_KM"],
    )


def crop_evidence(filename):
    """Serve an evidence photo only to its owner or an administrator."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    row = conn.cursor().execute(
        "SELECT farmer FROM inventory WHERE photo_path=?",
        (filename,),
    ).fetchone()
    conn.close()
    if not row or (
        row["farmer"] != session["user"] and session.get("role") != "admin"
    ):
        return jsonify({"error": "Evidence photo not found"}), 404

    return send_from_directory(
        os.path.join(current_app.config["UPLOAD_FOLDER"], "crop_evidence"),
        filename,
        as_attachment=False,
    )


def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/inventory', endpoint='inventory', view_func=inventory)
    application.add_url_rule('/inventory/buy', endpoint='inventory_buy', view_func=inventory_buy, methods=['POST'])
    application.add_url_rule('/inventory/edit_crop', endpoint='inventory_edit_crop', view_func=inventory_edit_crop, methods=['POST'])
    application.add_url_rule('/inventory/delete_crop', endpoint='inventory_delete_crop', view_func=inventory_delete_crop, methods=['POST'])
    application.add_url_rule('/inventory/edit/<int:item_id>', endpoint='edit_inventory', view_func=edit_inventory, methods=['GET', 'POST'])
    application.add_url_rule('/inventory/delete/<int:item_id>', endpoint='delete_inventory', view_func=delete_inventory)
    application.add_url_rule('/upload', endpoint='upload', view_func=upload, methods=['GET', 'POST'])
    application.add_url_rule('/harvest-evidence/<filename>', endpoint='crop_evidence', view_func=crop_evidence)
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['inventory', 'inventory_buy', 'inventory_edit_crop', 'inventory_delete_crop', 'edit_inventory', 'delete_inventory', 'upload', 'crop_evidence']

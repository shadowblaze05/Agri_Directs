"""Inventory HTTP routes.

Handlers retain the legacy SQL and template behavior while living in a domain module.
"""

import csv
import os
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, session
from werkzeug.utils import secure_filename

from .. import legacy as core
from ..legacy import app, get_db, logger, update_analytics

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

def inventory():
    """Display the signed-in user's harvest inventory as a dedicated workspace."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT crop_name, SUM(quantity) AS total_quantity, MAX(date_received) AS last_received, MAX(location) AS location "
        "FROM inventory WHERE farmer=? GROUP BY crop_name ORDER BY last_received DESC",
        (session["user"],),
    )
    items = cur.fetchall()
    cur.execute(
        "SELECT COUNT(DISTINCT crop_name) AS crop_count, COALESCE(SUM(quantity), 0) AS total_quantity "
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
    cur.execute("SELECT SUM(quantity) AS total FROM inventory WHERE farmer=? AND crop_name=?", (session["user"], crop_name))
    row = cur.fetchone()
    total = row["total"] or 0

    if quantity > total:
        conn.close()
        return jsonify({"error": "Buy quantity exceeds available inventory"}), 400

    needed = quantity
    cur.execute(
        "SELECT id, quantity FROM inventory WHERE farmer=? AND crop_name=? ORDER BY date_received DESC",
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
    cur.execute("SELECT SUM(quantity) AS total FROM inventory WHERE farmer=? AND crop_name=?", (session["user"], crop_name))
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
            "INSERT INTO inventory(crop_name,quantity,farmer,date_received,location) VALUES(?,?,?,?,?)",
            (crop_name, add_amount, session["user"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_loc)
        )
    else:
        remove_amount = current_total - quantity
        cur.execute(
            "SELECT id, quantity FROM inventory WHERE farmer=? AND crop_name=? ORDER BY date_received DESC",
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
    cur.execute("DELETE FROM inventory WHERE farmer=? AND crop_name=?", (session["user"], crop_name))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Crop inventory deleted"})

def edit_inventory(item_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory WHERE id=?", (item_id,))
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

        cur.execute("UPDATE inventory SET crop_name=?, quantity=? WHERE id=?",
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
    cur.execute("SELECT * FROM inventory WHERE id=?", (item_id,))
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
    cur.execute("SELECT role, location FROM users WHERE username=?", (session["user"],))
    user = cur.fetchone()
    role = user[0] if user else 'user'
    location = user[1] if user else None

    if request.method == "POST":
        # Require that the user has a profile location before accepting harvest uploads
        if not location:
            flash("You must set your location in your profile before uploading harvest data.")
            conn.close()
            return redirect(request.url)

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

                            crop_name = cur.execute("SELECT crops_name FROM crops WHERE id=?", (crop_id,)).fetchone()["crops_name"] if cur.execute("SELECT crops_name FROM crops WHERE id=?", (crop_id,)).fetchone() else None
                            if not crop_name:
                                flash(f"Crop '{crop}' could not be resolved for upload")
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
                                crop_name,
                                quantity,
                                farmer,
                                date_received,
                                location
                            )
                            VALUES(?,?,?,?,?)
                            """, (
                                crop_name,
                                quantity,
                                session["user"],
                                date_received,
                                location
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

            crop_name_row = cur.execute("SELECT crops_name FROM crops WHERE id=?", (crop_id,)).fetchone()
            crop_name = crop_name_row["crops_name"] if crop_name_row else None
            if not crop_name:
                flash("Selected crop could not be found")
                conn.close()
                return redirect(request.url)

            cur.execute("""
            INSERT INTO inventory(
                crop_name,
                quantity,
                farmer,
                date_received,
                location
            )
            VALUES(?,?,?,?,?)
            """, (
                crop_name,
                quantity,
                session["user"],
                date_received,
                location
            ))
            conn.commit()
            update_analytics()
            processed_any = True
            flash("Manual harvest entry added successfully!")
            logger.info(f"User {session['user']} manually posted crop {crop_id} x{quantity}")

        else:
            flash("Please upload a CSV file or enter harvest details manually.")
            conn.close()
            return redirect(request.url)

        ##return redirect("/dashboard")
    
    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    crops = cur.fetchall()

    conn.close()
    return render_template("upload.html", crops=crops)

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/inventory', endpoint='inventory', view_func=inventory)
    application.add_url_rule('/inventory/buy', endpoint='inventory_buy', view_func=inventory_buy, methods=['POST'])
    application.add_url_rule('/inventory/edit_crop', endpoint='inventory_edit_crop', view_func=inventory_edit_crop, methods=['POST'])
    application.add_url_rule('/inventory/delete_crop', endpoint='inventory_delete_crop', view_func=inventory_delete_crop, methods=['POST'])
    application.add_url_rule('/inventory/edit/<int:item_id>', endpoint='edit_inventory', view_func=edit_inventory, methods=['GET', 'POST'])
    application.add_url_rule('/inventory/delete/<int:item_id>', endpoint='delete_inventory', view_func=delete_inventory)
    application.add_url_rule('/upload', endpoint='upload', view_func=upload, methods=['GET', 'POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['inventory', 'inventory_buy', 'inventory_edit_crop', 'inventory_delete_crop', 'edit_inventory', 'delete_inventory', 'upload']

from datetime import datetime, timedelta
from flask import flash, jsonify, redirect, render_template, request, session, url_for
from .. import legacy as core
from ..legacy import logger
from ..models.database import _save_upload_file, get_db

import os
import uuid
from werkzeug.utils import secure_filename

globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_IMAGES = 5


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_cart_count(username):
    if not username:
        return 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    cart_count = 0
    if user:
        cur.execute("SELECT COALESCE(SUM(quantity), 0) as total FROM cart WHERE user_id = ?", (user["id"],))
        result = cur.fetchone()
        cart_count = result["total"] if result else 0
    conn.close()
    return cart_count


def marketplace():
    if "user" not in session:
        return redirect("/login")

    promote_due_preorders()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.*, u.username as seller_name, u.location as seller_location,
               u.reliability_score, u.reliability_status,
               u.completed_transactions, u.cancelled_transactions, u.total_transactions
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.status = 'available'
        ORDER BY m.listing_date DESC
    """)
    listings = cur.fetchall()

    cur.execute("""
        SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total_quantity
        FROM inventory i JOIN crops c ON c.id=i.crop_id
        WHERE i.farmer = ?
        GROUP BY i.crop_id, c.crops_name
        HAVING SUM(quantity) > 0
    """, (session["user"],))
    user_inventory = cur.fetchall()

    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    crops = cur.fetchall()

    cur.execute("""
        SELECT m.id, m.crop_name, m.delivery_date, u.username AS seller_name
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.buyer_username = ?
          AND m.status IN ('sold', 'delivered', 'completed')
          AND m.buyer_rating IS NULL
          AND m.delivery_confirmed = 1
          AND m.buyer_confirmed = 1
        ORDER BY COALESCE(m.delivery_date, m.order_date) DESC
    """, (session["user"],))
    pending_ratings = cur.fetchall()

    cart_count = get_cart_count(session["user"])

    listing_ids = [listing['id'] for listing in listings]
    image_counts = {}
    if listing_ids:
        placeholders = ','.join(['?'] * len(listing_ids))
        cur.execute(f"""
            SELECT listing_id, COUNT(*) as count
            FROM marketplace_images
            WHERE listing_id IN ({placeholders})
            GROUP BY listing_id
        """, listing_ids)
        for row in cur.fetchall():
            image_counts[row['listing_id']] = row['count']

    conn.close()

    return render_template("marketplace.html",
                         listings=listings,
                         user_inventory=user_inventory,
                         crops=crops,
                         pending_ratings=pending_ratings,
                         cart_count=cart_count,
                         image_counts=image_counts)


def add_marketplace_listing():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        crop_id = request.form.get("crop_id")
        amount = request.form.get("amount")
        price = request.form.get("price")
        unit = request.form.get("unit", "kg")
        description = request.form.get("description", "").strip()
        expiry_days = request.form.get("expiry_days", 30)
        listing_type = request.form.get("listing_type", "standard")
        available_date = request.form.get("available_date", "").strip()

        if not crop_id or not amount or not price:
            flash("All fields are required")
            return redirect(request.url)

        try:
            amount = int(amount)
            price = float(price)
            expiry_days = int(expiry_days)
        except ValueError:
            flash("Invalid number format")
            return redirect(request.url)

        if amount <= 0 or price <= 0:
            flash("Amount and price must be positive")
            return redirect(request.url)

        if listing_type not in ("standard", "preorder", "looking_for"):
            listing_type = "standard"

        # Pre-order date validation
        if listing_type == "preorder":
            if not available_date:
                flash("Please set the date/time when the crop will be ready.")
                return redirect(request.url)
            try:
                from datetime import datetime as _dt
                try:
                    _dt.strptime(available_date, "%Y-%m-%dT%H:%M")
                except ValueError:
                    _dt.strptime(available_date, "%Y-%m-%dT%H:%M:%S")
                available_date = available_date.replace("T", " ")
            except ValueError:
                flash("Invalid date/time format for availability.")
                return redirect(request.url)
        else:
            available_date = None

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT crops_name FROM crops WHERE id = ?", (crop_id,))
        crop = cur.fetchone()
        if not crop:
            flash("Invalid crop selected")
            conn.close()
            return redirect(request.url)

        crop_name = crop["crops_name"]

        # Inventory check: only for standard listings
        if listing_type == "standard":
            cur.execute("""
                SELECT SUM(quantity) as total
                FROM inventory
                WHERE farmer = ? AND crop_id = ?
            """, (session["user"], crop_id))
            inventory = cur.fetchone()

            if not inventory or inventory["total"] < amount:
                flash(f"You don't have enough {crop_name} in your inventory. Available: {inventory['total'] if inventory else 0}")
                conn.close()
                return redirect(request.url)

        cur.execute("SELECT id, location FROM users WHERE username = ?", (session["user"],))
        user = cur.fetchone()
        if not user:
            flash("User not found")
            conn.close()
            return redirect(request.url)

        expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d %H:%M:%S")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute("""
            INSERT INTO marketplace(
                user_id, username, crop_id, crop_name, amount, price,
                unit, status, listing_date, expiry_date, description, location,
                listing_type, available_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (
            user["id"], session["user"], crop_id, crop_name, amount, price,
            unit, "available", now, expiry_date, description, user["location"],
            listing_type, available_date
        ))

        result = cur.fetchone()
        listing_id = result[0] if result else None

        if not listing_id:
            conn.close()
            flash("Failed to create listing")
            return redirect(request.url)

        # Images: only for standard/preorder (looking_for doesn't need images)
        saved_images = []
        if listing_type != "looking_for" and 'images' in request.files:
            files = request.files.getlist('images')
            upload_folder = os.path.join('app', 'static', 'uploads', 'marketplace')
            os.makedirs(upload_folder, exist_ok=True)

            for idx, file in enumerate(files):
                if file and file.filename and allowed_file(file.filename):
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    image_filename = f"{uuid.uuid4().hex}.{ext}"
                    file_path = os.path.join(upload_folder, image_filename)
                    file.save(file_path)

                    cur.execute("""
                        INSERT INTO marketplace_images (listing_id, image_filename, display_order, created_at)
                        VALUES (?, ?, ?, ?)
                    """, (listing_id, image_filename, idx, now))

                    saved_images.append(image_filename)
                elif file and file.filename:
                    flash(f"Invalid file type for {file.filename}. Allowed: png, jpg, jpeg, gif, webp")
                    conn.close()
                    return redirect(request.url)

        try:
            thumbnail_index = int(request.form.get("thumbnail_index", 0))
        except (TypeError, ValueError):
            thumbnail_index = 0
        if thumbnail_index < 0 or thumbnail_index >= len(saved_images):
            thumbnail_index = 0
        if saved_images:
            main_image = saved_images[thumbnail_index]
            cur.execute("UPDATE marketplace SET main_image = ? WHERE id = ?", (main_image, listing_id))

        conn.commit()
        conn.close()

        # Image requirement only for standard/preorder
        if listing_type != "looking_for" and not saved_images:
            flash("Please upload at least one image")
            return redirect("/marketplace/add")

        flash(f"{listing_type.replace('_', ' ').title()} listing for {crop_name} created successfully!")
        return redirect("/marketplace")

    # GET request
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.crops_name AS crop_name, i.crop_id
        FROM inventory i JOIN crops c ON c.id=i.crop_id
        WHERE i.farmer = ?
        GROUP BY i.crop_id, c.crops_name
        HAVING SUM(quantity) > 0
        ORDER BY c.crops_name
    """, (session["user"],))
    user_crops = cur.fetchall()

    user_crops_with_ids = []
    for crop in user_crops:
        if crop["crop_id"]:
            cur.execute("""
                SELECT SUM(quantity) as total_quantity
                FROM inventory
                WHERE farmer = ? AND crop_id = ?
            """, (session["user"], crop["crop_id"]))
            total = cur.fetchone()
            user_crops_with_ids.append({
                "id": crop["crop_id"],
                "crops_name": crop["crop_name"],
                "total_quantity": total["total_quantity"] if total else 0
            })

    cur.execute("""
        SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total_quantity
        FROM inventory i JOIN crops c ON c.id=i.crop_id
        WHERE i.farmer = ?
        GROUP BY i.crop_id, c.crops_name
        HAVING SUM(quantity) > 0
        ORDER BY c.crops_name
    """, (session["user"],))
    user_inventory = cur.fetchall()

    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    all_crops = cur.fetchall()

    cart_count = get_cart_count(session["user"])
    conn.close()

    return render_template("add_listing.html",
                         crops=user_crops_with_ids,
                         all_crops=all_crops,
                         user_inventory=user_inventory,
                         cart_count=cart_count)

def buy_marketplace_item(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    quantity = data.get("quantity", 1)

    try:
        quantity = int(quantity)
    except ValueError:
        return jsonify({"error": "Invalid quantity"}), 400

    if quantity <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    current_user_id = current_user["id"]

    cur.execute("""
        SELECT m.*, u.username as seller_name
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.id = ? AND m.status = 'available'
    """, (listing_id,))
    listing = cur.fetchone()

    if not listing:
        conn.close()
        return jsonify({"error": "Listing not found or no longer available"}), 404

    if listing["user_id"] == current_user_id:
        conn.close()
        return jsonify({"error": "You cannot buy your own listing"}), 400

    if quantity > listing["amount"]:
        conn.close()
        return jsonify({"error": f"Only {listing['amount']} units available"}), 400

    seller_username = None
    try:
        seller_username = listing["seller_name"]
    except Exception:
        try:
            seller_username = listing["username"]
        except Exception:
            cur.execute("SELECT username FROM users WHERE id = ?", (listing["user_id"],))
            rr = cur.fetchone()
            seller_username = rr["username"] if rr else None

    total_price = quantity * listing["price"]
    order_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if quantity == listing["amount"]:
        cur.execute("UPDATE marketplace SET status = 'sold', buyer_username = ?, order_status = 'sold', order_date = ?, delivery_confirmed = 0 WHERE id = ?", (
            session["user"], order_timestamp, listing_id
        ))
    else:
        cur.execute("""
            INSERT INTO marketplace (
                user_id, username, buyer_username, crop_id, crop_name, amount, price, unit,
                status, order_status, listing_date, order_date, expiry_date, description, location, delivery_confirmed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            listing["user_id"], listing["username"], session["user"],
            listing["crop_id"], listing["crop_name"], quantity, listing["price"],
            listing["unit"], "sold", "sold", listing["listing_date"],
            order_timestamp, listing["expiry_date"], listing["description"],
            listing["location"], 0
        ))
        cur.execute("UPDATE marketplace SET amount = amount - ? WHERE id = ?", (quantity, listing_id))

    cur.execute("""
        INSERT INTO inventory(crop_id, quantity, farmer, date_received, location, source)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        listing["crop_id"], quantity, session["user"],
        order_timestamp, listing["location"], "purchase"
    ))

    cur.execute("""
        SELECT id, quantity FROM inventory 
        WHERE farmer = ? AND crop_id = ? 
        ORDER BY date_received ASC
    """, (seller_username, listing["crop_id"]))
    seller_inventory = cur.fetchall()

    remaining = quantity
    for item in seller_inventory:
        if remaining <= 0:
            break
        if item["quantity"] <= remaining:
            cur.execute("DELETE FROM inventory WHERE id = ?", (item["id"],))
            remaining -= item["quantity"]
        else:
            cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?",
                       (item["quantity"] - remaining, item["id"]))
            remaining = 0

    conn.commit()

    try:
        if seller_username:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (seller_username, "Item Sold",
                 f"{session['user']} purchased {quantity} {listing['crop_name']} from your listing.",
                 "marketplace", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0)
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to create marketplace purchase notification")

    conn.close()

    return jsonify({
        "status": "success",
        "message": f"Purchased {quantity} {listing['crop_name']} for ₱{total_price:.2f}"
    })


def complete_marketplace_order(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("SELECT * FROM marketplace WHERE id = ? AND user_id = ? AND status = 'sold'", (listing_id, current_user["id"]))
    listing = cur.fetchone()

    if not listing:
        conn.close()
        return jsonify({"error": "Order not found or not eligible for completion"}), 404

    cur.execute(
        "UPDATE marketplace SET status = 'delivered', order_status = 'delivered', delivery_date = ?, delivery_confirmed = 1 WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing_id)
    )

    cur.execute("""
        UPDATE users
        SET completed_transactions = COALESCE(completed_transactions, 0) + 1,
            total_transactions = COALESCE(total_transactions, 0) + 1
        WHERE username = ?
    """, (session["user"],))

    if listing["buyer_username"]:
        try:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (listing["buyer_username"], "Order Delivered",
                 f"Your order for {listing['crop_name']} has been marked delivered by {session['user']}. Please confirm receipt and then rate the seller.",
                 "marketplace", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0)
            )
        except Exception:
            logger.exception("Failed to create delivery notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Order marked as delivered."})


def confirm_marketplace_receipt(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM marketplace WHERE id = ? AND buyer_username = ?", (listing_id, session["user"]))
    listing = cur.fetchone()
    if not listing:
        conn.close()
        return jsonify({"error": "Order not found or you are not the buyer"}), 404

    try:
        delivery_confirmed = listing['delivery_confirmed']
    except Exception:
        delivery_confirmed = 0

    if not delivery_confirmed:
        conn.close()
        return jsonify({"error": "Seller has not confirmed delivery yet"}), 400

    try:
        buyer_confirmed = listing['buyer_confirmed']
    except Exception:
        buyer_confirmed = 0

    if buyer_confirmed:
        conn.close()
        return jsonify({"status": "already_confirmed", "message": "You have already confirmed receipt."})

    cur.execute(
        "UPDATE marketplace SET buyer_confirmed = 1, buyer_confirm_date = ?, order_status = 'completed' WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing_id)
    )

    try:
        cur.execute("""
            UPDATE users
            SET completed_transactions = COALESCE(completed_transactions, 0) + 1,
                total_transactions = COALESCE(total_transactions, 0) + 1
            WHERE username = ?
        """, (session["user"],))
    except Exception:
        logger.exception("Failed to update buyer transaction counts")

    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (listing['username'], "Buyer Confirmed Receipt",
             f"{session['user']} has confirmed receipt for {listing['crop_name']}.",
             "marketplace", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0)
        )
    except Exception:
        logger.exception("Failed to create buyer confirmation notification")

    conn.commit()
    conn.close()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"status": "success", "message": "Receipt confirmed. Please rate the seller."})
    else:
        flash("Receipt confirmed. Please rate the seller.")
        return redirect(url_for('my_marketplace_purchases'))


def my_marketplace_purchases():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.*, u.username AS seller_name, u.location AS seller_location
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.buyer_username = ? AND m.status IN ('sold', 'delivered')
        ORDER BY COALESCE(m.delivery_date, m.order_date) DESC
    """, (session["user"],))
    purchases = cur.fetchall()
    conn.close()
    return render_template("my_purchases.html", purchases=purchases)


def rate_marketplace_seller(listing_id):
    if "user" not in session:
        return redirect("/login")

    try:
        rating = int(request.form.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0
    if rating not in (1, 2, 3, 4, 5):
        flash("Please choose a rating from 1 to 5 stars.")
        return redirect("/marketplace/my-purchases")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username FROM marketplace
        WHERE id = ? AND buyer_username = ? AND status IN ('sold', 'delivered', 'completed') AND buyer_rating IS NULL
          AND delivery_confirmed = 1 AND buyer_confirmed = 1
    """, (listing_id, session["user"]))
    order = cur.fetchone()
    if not order:
        conn.close()
        flash("This order cannot be rated, or it has already been rated.")
        return redirect("/marketplace/my-purchases")

    cur.execute("UPDATE marketplace SET buyer_rating = ?, buyer_rating_date = ? WHERE id = ?", (
        rating, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing_id))
    cur.execute("SELECT AVG(buyer_rating) AS average_rating, COUNT(buyer_rating) AS rating_count FROM marketplace WHERE username = ? AND buyer_rating IS NOT NULL", (order["username"],))
    rating_summary = cur.fetchone()
    rating_count = rating_summary["rating_count"] or 0
    average_rating = rating_summary["average_rating"]
    if rating_count > 0 and average_rating is not None:
        status = "High Reliability" if average_rating >= 4 else "Medium Reliability" if average_rating >= 3 else "Low Reliability"
        cur.execute("UPDATE users SET reliability_score = ?, reliability_status = ? WHERE username = ?", (round(average_rating, 2), status, order["username"]))
    else:
        cur.execute("UPDATE users SET reliability_score = NULL, reliability_status = 'Not Yet Rated' WHERE username = ?", (order["username"],))
    conn.commit()
    conn.close()
    flash("Thank you. Your rating has been submitted.")
    return redirect("/marketplace/my-purchases")


def my_marketplace_listings():
    if "user" not in session:
        return redirect("/login")

    promote_due_preorders()
    cart_count = get_cart_count(session["user"])

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        flash("User not found")
        return redirect("/marketplace")
    current_user_id = current_user["id"]

    cur.execute("""
        SELECT m.*
        FROM marketplace m
        WHERE m.user_id = ?
        ORDER BY m.listing_date DESC
    """, (current_user_id,))
    all_listings = cur.fetchall()

    active_listings = []
    preorder_requests = []
    looking_for_listings = []
    sold_listings = []
    traded_listings = []

    for listing in all_listings:
        status = listing['status']
        listing_type = listing['listing_type'] if 'listing_type' in listing.keys() else 'standard'
        preorder_status = listing['preorder_status'] if 'preorder_status' in listing.keys() else None

        if listing_type == 'looking_for':
            looking_for_listings.append(listing)
        elif listing_type == 'preorder' and preorder_status in ('pending', 'confirmed', 'cancel_requested'):
            preorder_requests.append(listing)
        elif status == 'available':
            active_listings.append(listing)
        elif status == 'sold':
            sold_listings.append(listing)
        elif status == 'traded':
            traded_listings.append(listing)

    return render_template("my_listings.html",
                        active_listings=active_listings,
                        preorder_requests=preorder_requests,
                        looking_for_listings=looking_for_listings,
                        sold_listings=sold_listings,
                        traded_listings=traded_listings,
                        cart_count=cart_count)


def delete_marketplace_listing(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    current_user_id = current_user["id"]

    cur.execute("SELECT * FROM marketplace WHERE id = ? AND user_id = ?",
                (listing_id, current_user_id))
    listing = cur.fetchone()

    if not listing:
        conn.close()
        return jsonify({"error": "Listing not found or you don't have permission"}), 404

    cur.execute("DELETE FROM marketplace WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Listing deleted"})


def trade_marketplace_item(listing_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        flash("User not found")
        conn.close()
        return redirect("/marketplace")

    current_user_id = current_user["id"]

    cur.execute("""
        SELECT m.*, u.username as seller_name, u.reliability_score, u.reliability_status, u.location AS seller_location
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.id = ? AND m.status = 'available'
    """, (listing_id,))
    listing = cur.fetchone()

    if not listing:
        flash("Listing not found or no longer available")
        conn.close()
        return redirect("/marketplace")

    if listing["user_id"] == current_user_id:
        flash("You cannot trade with yourself")
        conn.close()
        return redirect("/marketplace")

    if request.method == "POST":
        trade_crop = request.form.get("trade_crop")
        trade_amount = request.form.get("trade_amount")

        if not trade_crop or not trade_amount:
            flash("Please select a crop and enter amount")
            conn.close()
            return redirect(request.url)

        try:
            trade_amount = int(trade_amount)
        except ValueError:
            flash("Invalid trade amount")
            conn.close()
            return redirect(request.url)

        if trade_amount <= 0:
            flash("Trade amount must be positive")
            conn.close()
            return redirect(request.url)

        cur.execute("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE farmer = ? AND crop_id = (SELECT id FROM crops WHERE crops_name = ?)
        """, (session["user"], trade_crop))
        inventory = cur.fetchone()

        if not inventory or inventory["total"] < trade_amount:
            flash(f"You don't have enough {trade_crop} to trade. Available: {inventory['total'] if inventory else 0}")
            conn.close()
            return redirect(request.url)

        cur.execute("""
            SELECT id, quantity FROM inventory
            WHERE farmer = ? AND crop_id = (SELECT id FROM crops WHERE crops_name = ?)
            ORDER BY date_received ASC
        """, (session["user"], trade_crop))
        buyer_items = cur.fetchall()

        remaining = trade_amount
        for item in buyer_items:
            if remaining <= 0:
                break
            if item["quantity"] <= remaining:
                cur.execute("DELETE FROM inventory WHERE id = ?", (item["id"],))
                remaining -= item["quantity"]
            else:
                cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?",
                           (item["quantity"] - remaining, item["id"]))
                remaining = 0

        seller_username = None
        try:
            seller_username = listing["seller_name"]
        except Exception:
            try:
                seller_username = listing["username"]
            except Exception:
                cur.execute("SELECT username FROM users WHERE id = ?", (listing["user_id"],))
                rr = cur.fetchone()
                seller_username = rr["username"] if rr else None

        cur.execute("""
            INSERT INTO inventory(crop_id, quantity, farmer, date_received, location, source)
            SELECT id, ?, ?, ?, ?, ? FROM crops WHERE crops_name = ?
        """, (
            trade_amount, seller_username,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            listing["location"], "trade", trade_crop
        ))

        cur.execute("""
            INSERT INTO inventory(crop_id, quantity, farmer, date_received, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            listing["crop_id"], listing["amount"], session["user"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            session.get("location", ""), "trade"
        ))

        cur.execute("UPDATE marketplace SET status = 'traded' WHERE id = ?", (listing_id,))

        conn.commit()

        try:
            if seller_username:
                cur.execute(
                    "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                    (seller_username, "Item Traded",
                     f"{session['user']} completed a trade: gave {trade_amount} {trade_crop} and received your {listing['amount']} {listing['crop_name']}.",
                     "marketplace", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0)
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to create marketplace trade notification")

        conn.close()

        flash(f"Trade successful! You received {listing['amount']} {listing['crop_name']} and gave {trade_amount} {trade_crop}")
        return redirect("/marketplace")

    cur.execute("""
        SELECT c.crops_name AS crop_name, SUM(i.quantity) AS total_quantity
        FROM inventory i JOIN crops c ON c.id=i.crop_id
        WHERE i.farmer = ?
        GROUP BY i.crop_id, c.crops_name
        HAVING SUM(quantity) > 0
    """, (session["user"],))
    user_inventory = cur.fetchall()

    conn.close()

    return render_template("trade_listing.html", listing=listing, user_inventory=user_inventory)


def get_listing_api(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marketplace WHERE id = ?", (listing_id,))
    listing = cur.fetchone()
    conn.close()

    if not listing:
        return jsonify({"error": "Listing not found"}), 404

    return jsonify({
        "crop_name": listing["crop_name"],
        "amount": listing["amount"],
        "unit": listing["unit"]
    })


def save_images_to_db(listing_id, files):
    upload_folder = os.path.join('static', 'uploads', 'marketplace')
    os.makedirs(upload_folder, exist_ok=True)

    saved_images = []
    for idx, file in enumerate(files):
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(upload_folder, image_filename)
            file.save(file_path)

            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO marketplace_images (listing_id, image_filename, display_order, created_at)
                VALUES (?, ?, ?, ?)
            """, (listing_id, image_filename, idx, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()

            saved_images.append(image_filename)

    return saved_images


def delete_listing_image(image_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("""
        SELECT mi.*, m.user_id, m.id as listing_id
        FROM marketplace_images mi
        JOIN marketplace m ON mi.listing_id = m.id
        WHERE mi.id = ?
    """, (image_id,))
    image = cur.fetchone()

    if not image or image["user_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Image not found or no permission"}), 404

    cur.execute("SELECT COUNT(*) as count FROM marketplace_images WHERE listing_id = ?", (image["listing_id"],))
    count = cur.fetchone()["count"]

    if count <= 1:
        conn.close()
        return jsonify({"error": "Cannot delete the last image"}), 400

    from flask import current_app
    file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'marketplace', image["image_filename"])
    if os.path.exists(file_path):
        os.remove(file_path)

    cur.execute("DELETE FROM marketplace_images WHERE id = ?", (image_id,))

    cur.execute("SELECT main_image FROM marketplace WHERE id = ?", (image["listing_id"],))
    listing = cur.fetchone()
    if listing and listing["main_image"] == image["image_filename"]:
        cur.execute("SELECT image_filename FROM marketplace_images WHERE listing_id = ? ORDER BY display_order ASC LIMIT 1", (image["listing_id"],))
        new_main = cur.fetchone()
        cur.execute("UPDATE marketplace SET main_image = ? WHERE id = ?",
                   (new_main["image_filename"] if new_main else None, image["listing_id"]))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Image deleted"})


def set_listing_thumbnail(image_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("""
        SELECT mi.image_filename, mi.listing_id, m.user_id
        FROM marketplace_images mi
        JOIN marketplace m ON mi.listing_id = m.id
        WHERE mi.id = ?
    """, (image_id,))
    image = cur.fetchone()

    if not image or image["user_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Image not found or no permission"}), 404

    cur.execute(
        "UPDATE marketplace SET main_image = ? WHERE id = ?",
        (image["image_filename"], image["listing_id"])
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Thumbnail updated"})


def view_cart():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return redirect("/login")

    cur.execute("""
        SELECT c.*, m.crop_name, m.price, m.unit, m.main_image, m.username as seller_name,
               m.amount as available_amount, m.id as listing_id
        FROM cart c
        JOIN marketplace m ON c.listing_id = m.id
        WHERE c.user_id = ?
        ORDER BY c.added_date DESC
    """, (user["id"],))
    cart_items = cur.fetchall()

    total = 0
    for item in cart_items:
        total += item["quantity"] * item["price"]

    cart_count = get_cart_count(session["user"])

    conn.close()

    return render_template("cart.html",
                         cart_items=cart_items,
                         total=total,
                         cart_count=cart_count)


def add_to_cart(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    quantity = data.get("quantity", 1)

    try:
        quantity = int(quantity)
    except ValueError:
        return jsonify({"error": "Invalid quantity"}), 400

    if quantity <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    user_id = user["id"]

    cur.execute("SELECT id, amount, user_id FROM marketplace WHERE id = ? AND status = 'available'", (listing_id,))
    listing = cur.fetchone()
    if not listing:
        conn.close()
        return jsonify({"error": "Listing not available"}), 404

    if listing["user_id"] == user_id:
        conn.close()
        return jsonify({"error": "You cannot buy your own listing"}), 400

    if quantity > listing["amount"]:
        conn.close()
        return jsonify({"error": f"Only {listing['amount']} units available"}), 400

    cur.execute("SELECT id, quantity FROM cart WHERE user_id = ? AND listing_id = ?", (user_id, listing_id))
    cart_item = cur.fetchone()

    if cart_item:
        new_quantity = cart_item["quantity"] + quantity
        if new_quantity > listing["amount"]:
            conn.close()
            return jsonify({"error": f"Only {listing['amount']} units available"}), 400
        cur.execute("UPDATE cart SET quantity = ? WHERE id = ?", (new_quantity, cart_item["id"]))
    else:
        cur.execute("""
            INSERT INTO cart (user_id, listing_id, quantity, added_date)
            VALUES (?, ?, ?, ?)
        """, (user_id, listing_id, quantity, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Added to cart"})


def update_cart_item(cart_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    quantity = data.get("quantity", 1)

    try:
        quantity = int(quantity)
    except ValueError:
        return jsonify({"error": "Invalid quantity"}), 400

    if quantity <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("""
        SELECT c.*, m.amount as available_amount
        FROM cart c
        JOIN marketplace m ON c.listing_id = m.id
        WHERE c.id = ? AND c.user_id = ?
    """, (cart_id, user["id"]))
    cart_item = cur.fetchone()

    if not cart_item:
        conn.close()
        return jsonify({"error": "Cart item not found"}), 404

    if quantity > cart_item["available_amount"]:
        conn.close()
        return jsonify({"error": f"Only {cart_item['available_amount']} units available"}), 400

    cur.execute("UPDATE cart SET quantity = ? WHERE id = ?", (quantity, cart_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Cart updated"})


def remove_from_cart(cart_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("DELETE FROM cart WHERE id = ? AND user_id = ?", (cart_id, user["id"]))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Item removed from cart"})


def checkout_cart():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    user_id = user["id"]

    cur.execute("""
        SELECT c.*, m.user_id as seller_id, m.crop_name, m.price, m.amount as available_amount,
               m.username as seller_name, m.location, m.crop_id, m.unit
        FROM cart c
        JOIN marketplace m ON c.listing_id = m.id
        WHERE c.user_id = ? AND m.status = 'available'
    """, (user_id,))
    cart_items = cur.fetchall()

    if not cart_items:
        conn.close()
        return jsonify({"error": "Cart is empty"}), 400

    order_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in cart_items:
        cur.execute("SELECT amount, status FROM marketplace WHERE id = ?", (item["listing_id"],))
        listing = cur.fetchone()
        if not listing or listing["status"] != "available":
            continue

        if item["quantity"] > listing["amount"]:
            continue

        if item["quantity"] == listing["amount"]:
            cur.execute("""
                UPDATE marketplace 
                SET status = 'sold', buyer_username = ?, order_status = 'sold', order_date = ?, delivery_confirmed = 0 
                WHERE id = ?
            """, (session["user"], order_timestamp, item["listing_id"]))
        else:
            cur.execute("""
                INSERT INTO marketplace (
                    user_id, username, buyer_username, crop_id, crop_name, amount, price, unit,
                    status, order_status, listing_date, order_date, expiry_date, description, location, delivery_confirmed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item["seller_id"], item["seller_name"], session["user"],
                item["crop_id"], item["crop_name"], item["quantity"], item["price"],
                item["unit"] or "kg", "sold", "sold",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_timestamp,
                None, None, item["location"], 0
            ))
            cur.execute("UPDATE marketplace SET amount = amount - ? WHERE id = ?",
                       (item["quantity"], item["listing_id"]))

        cur.execute("""
            INSERT INTO inventory(crop_id, quantity, farmer, date_received, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item["crop_id"], item["quantity"], session["user"],
            order_timestamp, item["location"], "purchase"
        ))

        cur.execute("""
            SELECT id, quantity FROM inventory 
            WHERE farmer = ? AND crop_id = ? 
            ORDER BY date_received ASC
        """, (item["seller_name"], item["crop_id"]))
        seller_inventory = cur.fetchall()

        remaining = item["quantity"]
        for inv_item in seller_inventory:
            if remaining <= 0:
                break
            if inv_item["quantity"] <= remaining:
                cur.execute("DELETE FROM inventory WHERE id = ?", (inv_item["id"],))
                remaining -= inv_item["quantity"]
            else:
                cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?",
                           (inv_item["quantity"] - remaining, inv_item["id"]))
                remaining = 0

    cur.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Order placed successfully!"})


def product_detail(listing_id):
    if "user" not in session:
        return redirect("/login")

    promote_due_preorders()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.*, u.username as seller_name, u.location as seller_location,
               u.reliability_score, u.reliability_status,
               u.completed_transactions, u.cancelled_transactions, u.total_transactions
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.id = ? AND m.status = 'available'
    """, (listing_id,))
    listing = cur.fetchone()

    if not listing:
        flash("Product not found")
        conn.close()
        return redirect("/marketplace")

    cur.execute("""
        SELECT image_filename, display_order
        FROM marketplace_images
        WHERE listing_id = ?
        ORDER BY display_order ASC
    """, (listing_id,))
    images = cur.fetchall()

    if not images and listing["main_image"]:
        images = [{"image_filename": listing["main_image"], "display_order": 0}]

    cur.execute("""
        SELECT * FROM marketplace
        WHERE user_id = ? AND status = 'available' AND id != ?
        ORDER BY listing_date DESC LIMIT 4
    """, (listing["user_id"], listing_id))
    seller_other_listings = cur.fetchall()

    cart_count = get_cart_count(session["user"])

    conn.close()

    return render_template("product_detail.html",
                         listing=listing,
                         images=images,
                         seller_other_listings=seller_other_listings,
                         cart_count=cart_count)


def edit_marketplace_listing(listing_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, location FROM users WHERE username = ?", (session["user"],))
    user = cur.fetchone()
    if not user:
        flash("User not found")
        conn.close()
        return redirect("/marketplace")

    user_id = user["id"]

    cur.execute("SELECT * FROM marketplace WHERE id = ? AND user_id = ?", (listing_id, user_id))
    listing = cur.fetchone()

    if not listing:
        flash("Listing not found or you don't have permission")
        conn.close()
        return redirect("/marketplace/my-listings")

    if listing["status"] != "available":
        flash("You can only edit active listings")
        conn.close()
        return redirect("/marketplace/my-listings")

    if request.method == "POST":
        amount = request.form.get("amount")
        price = request.form.get("price")
        unit = request.form.get("unit", "kg")
        description = request.form.get("description", "").strip()

        try:
            amount = int(amount)
            price = float(price)
        except (TypeError, ValueError):
            flash("Invalid amount or price")
            conn.close()
            return redirect(request.url)

        if amount <= 0 or price <= 0:
            flash("Amount and price must be positive")
            conn.close()
            return redirect(request.url)

        cur.execute("""
            UPDATE marketplace
            SET amount = ?, price = ?, unit = ?, description = ?
            WHERE id = ?
        """, (amount, price, unit, description, listing_id))

        if 'images' in request.files:
            files = request.files.getlist('images')
            new_images = [f for f in files if f and f.filename]

            if new_images:
                cur.execute("SELECT COUNT(*) as count FROM marketplace_images WHERE listing_id = ?", (listing_id,))
                existing_count = cur.fetchone()["count"]

                cur.execute("SELECT COALESCE(MAX(display_order), -1) as max_order FROM marketplace_images WHERE listing_id = ?", (listing_id,))
                max_order = cur.fetchone()["max_order"]

                from flask import current_app
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'marketplace')
                os.makedirs(upload_folder, exist_ok=True)

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                for file in new_images:
                    if existing_count >= 5:
                        flash("Maximum 5 images per listing. Some images were not added.")
                        break

                    if allowed_file(file.filename):
                        ext = file.filename.rsplit('.', 1)[1].lower()
                        image_filename = f"{uuid.uuid4().hex}.{ext}"
                        file_path = os.path.join(upload_folder, image_filename)
                        file.save(file_path)

                        max_order += 1
                        cur.execute("""
                            INSERT INTO marketplace_images (listing_id, image_filename, display_order, created_at)
                            VALUES (?, ?, ?, ?)
                        """, (listing_id, image_filename, max_order, now))

                        existing_count += 1

                if not listing["main_image"]:
                    cur.execute("SELECT image_filename FROM marketplace_images WHERE listing_id = ? ORDER BY display_order ASC LIMIT 1", (listing_id,))
                    first_image = cur.fetchone()
                    if first_image:
                        cur.execute("UPDATE marketplace SET main_image = ? WHERE id = ?", (first_image["image_filename"], listing_id))

        conn.commit()
        conn.close()

        flash("Listing updated successfully!")
        return redirect("/marketplace/my-listings")

    cur.execute("""
        SELECT id, image_filename, display_order
        FROM marketplace_images
        WHERE listing_id = ?
        ORDER BY display_order ASC
    """, (listing_id,))
    images = cur.fetchall()

    cart_count = get_cart_count(session["user"])

    conn.close()

    return render_template("add_listing.html",
                         listing=listing,
                         images=images,
                         cart_count=cart_count)


def create_preorder(listing_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    quantity = data.get("quantity", 1)

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid quantity"}), 400

    if quantity <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    buyer = cur.fetchone()
    if not buyer:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cur.execute("""
        SELECT * FROM marketplace
        WHERE id = ? AND listing_type = 'preorder' AND status = 'available'
    """, (listing_id,))
    listing = cur.fetchone()

    if not listing:
        conn.close()
        return jsonify({"error": "Pre-order listing not found"}), 404

    if listing["user_id"] == buyer["id"]:
        conn.close()
        return jsonify({"error": "You cannot pre-order your own listing"}), 400

    if quantity > listing["amount"]:
        conn.close()
        return jsonify({"error": f"Only {listing['amount']} units available"}), 400

    new_amount = listing["amount"] - quantity
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if new_amount <= 0:
        cur.execute("""
            UPDATE marketplace
            SET status = 'sold', buyer_username = ?, order_status = 'preorder_pending',
                preorder_status = 'pending', preorder_quantity = ?, order_date = ?
            WHERE id = ?
        """, (session["user"], quantity, now, listing_id))
    else:
        cur.execute("UPDATE marketplace SET amount = ? WHERE id = ?", (new_amount, listing_id))

        cur.execute("""
            INSERT INTO marketplace (
                user_id, username, buyer_username, crop_id, crop_name,
                amount, price, unit, status, order_status,
                listing_date, order_date, expiry_date, description, location,
                listing_type, available_date, preorder_status, preorder_quantity,
                main_image
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            listing["user_id"], listing["username"], session["user"],
            listing["crop_id"], listing["crop_name"], quantity, listing["price"],
            listing["unit"], "sold", "preorder_pending",
            listing["listing_date"], now, listing["expiry_date"],
            listing["description"], listing["location"],
            "preorder", listing["available_date"], "pending", quantity,
            listing["main_image"],
        ))

    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (listing["username"], "New Pre-order Request",
             f"{session['user']} wants to pre-order {quantity} {listing['unit']} of {listing['crop_name']}.",
             "preorder", now, 0)
        )
    except Exception:
        logger.exception("Failed to create preorder notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Pre-order sent! Waiting for seller confirmation."})


def accept_preorder(order_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM marketplace
        WHERE id = ? AND username = ? AND listing_type = 'preorder'
          AND preorder_status = 'pending'
    """, (order_id, session["user"]))
    order = cur.fetchone()

    if not order:
        conn.close()
        return jsonify({"error": "Pre-order not found or not pending"}), 404

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE marketplace
        SET preorder_status = 'confirmed', order_status = 'preorder_confirmed'
        WHERE id = ?
    """, (order_id,))

    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (order["buyer_username"], "Pre-order Confirmed",
             f"{session['user']} confirmed your pre-order for {order['amount']} {order['unit']} of {order['crop_name']}.",
             "preorder", now, 0)
        )
    except Exception:
        logger.exception("Failed to create accept notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Pre-order confirmed."})


def reject_preorder(order_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM marketplace
        WHERE id = ? AND username = ? AND listing_type = 'preorder'
          AND preorder_status = 'pending'
    """, (order_id, session["user"]))
    order = cur.fetchone()

    if not order:
        conn.close()
        return jsonify({"error": "Pre-order not found or not pending"}), 404

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE marketplace
        SET preorder_status = 'cancelled',
            order_status = 'preorder_rejected',
            cancel_reason = ?,
            cancel_requested_by = ?,
            cancel_requested_date = ?
        WHERE id = ?
    """, (reason or None, session["user"], now, order_id))

    msg = f"{session['user']} declined your pre-order for {order['crop_name']}."
    if reason:
        msg += f" Reason: {reason}"

    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (order["buyer_username"], "Pre-order Declined", msg, "preorder", now, 0)
        )
    except Exception:
        logger.exception("Failed to create reject notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Pre-order rejected."})


def request_preorder_cancel(order_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "Please provide a reason for cancellation."}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM marketplace
        WHERE id = ? AND listing_type = 'preorder'
          AND preorder_status IN ('pending', 'confirmed')
          AND (username = ? OR buyer_username = ?)
    """, (order_id, session["user"], session["user"]))
    order = cur.fetchone()

    if not order:
        conn.close()
        return jsonify({"error": "Pre-order not found or cannot be cancelled"}), 404

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    other_party = order["buyer_username"] if session["user"] == order["username"] else order["username"]

    cur.execute("""
        UPDATE marketplace
        SET preorder_status = 'cancel_requested',
            cancel_requested_by = ?,
            cancel_reason = ?,
            cancel_requested_date = ?
        WHERE id = ?
    """, (session["user"], reason, now, order_id))

    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (other_party, "Cancellation Requested",
             f"{session['user']} requested to cancel the pre-order for {order['crop_name']}. Reason: {reason}",
             "preorder", now, 0)
        )
    except Exception:
        logger.exception("Failed to create cancel request notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Cancellation request sent."})


def approve_preorder_cancel(order_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM marketplace
        WHERE id = ? AND listing_type = 'preorder'
          AND preorder_status = 'cancel_requested'
          AND (username = ? OR buyer_username = ?)
          AND cancel_requested_by != ?
    """, (order_id, session["user"], session["user"], session["user"]))
    order = cur.fetchone()

    if not order:
        conn.close()
        return jsonify({"error": "No pending cancellation to approve"}), 404

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE marketplace
        SET preorder_status = 'cancelled', order_status = 'preorder_cancelled'
        WHERE id = ?
    """, (order_id,))

    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (order["cancel_requested_by"], "Cancellation Approved",
             f"{session['user']} approved your cancellation request for {order['crop_name']}.",
             "preorder", now, 0)
        )
    except Exception:
        logger.exception("Failed to create approval notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Cancellation approved."})


def my_preorders():
    if "user" not in session:
        return redirect("/login")

    promote_due_preorders()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.*, u.username AS seller_name, u.location AS seller_location
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.buyer_username = ? AND m.listing_type = 'preorder'
        ORDER BY COALESCE(m.available_date, m.order_date) ASC
    """, (session["user"],))
    preorders = cur.fetchall()

    cart_count = get_cart_count(session["user"])
    conn.close()

    return render_template("my_preorders.html",
                         preorders=preorders,
                         cart_count=cart_count)


def my_preorder_requests():
    if "user" not in session:
        return redirect("/login")

    promote_due_preorders()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM marketplace
        WHERE username = ? AND listing_type = 'preorder'
        ORDER BY CASE preorder_status
            WHEN 'pending' THEN 1
            WHEN 'confirmed' THEN 2
            WHEN 'cancel_requested' THEN 3
            ELSE 4
        END, COALESCE(available_date, order_date) ASC
    """, (session["user"],))
    requests_list = cur.fetchall()

    cart_count = get_cart_count(session["user"])
    conn.close()

    return render_template("my_preorder_requests.html",
                         requests=requests_list,
                         cart_count=cart_count)

def promote_due_preorders():
    """Flip pre-order listings to 'standard' when their available_date has passed.
    
    Called lazily on page loads. Also notifies seller and buyer(s).
    """
    conn = get_db()
    cur = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Find all available pre-order listings whose ready date has arrived
    cur.execute("""
        SELECT id, username, crop_name, available_date
        FROM marketplace
        WHERE listing_type = 'preorder'
          AND status = 'available'
          AND available_date IS NOT NULL
          AND available_date <= ?
    """, (now_str,))
    due_listings = cur.fetchall()
    
    if not due_listings:
        conn.close()
        return
    
    for listing in due_listings:
        listing_id = listing["id"]
        
        # Flip this listing to standard
        cur.execute("""
            UPDATE marketplace
            SET listing_type = 'standard'
            WHERE id = ?
        """, (listing_id,))
        
        # Notify the seller
        try:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (listing["username"], "Pre-order Now Available",
                 f"Your pre-order listing for {listing['crop_name']} is now live for standard purchase.",
                 "marketplace", now_str, 0)
            )
        except Exception:
            logger.exception("Failed to notify seller of preorder promotion")
        
        # Notify all buyers with pending/confirmed pre-orders on this listing
        cur.execute("""
            SELECT buyer_username
            FROM marketplace
            WHERE id != ?
              AND username = ?
              AND crop_name = ?
              AND listing_type = 'preorder'
              AND buyer_username IS NOT NULL
              AND preorder_status IN ('pending', 'confirmed')
        """, (listing_id, listing["username"], listing["crop_name"]))
        buyers = cur.fetchall()
        
        for buyer in buyers:
            try:
                cur.execute(
                    "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                    (buyer["buyer_username"], "Pre-order Ready",
                     f"The {listing['crop_name']} you pre-ordered from {listing['username']} is now ready.",
                     "preorder", now_str, 0)
                )
            except Exception:
                logger.exception("Failed to notify buyer of preorder promotion")
    
    conn.commit()
    conn.close()

def looking_for_listings():
    """View all looking-for listings posted by buyers."""
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT m.*, u.username as seller_name, u.location as seller_location
        FROM marketplace m
        JOIN users u ON m.user_id = u.id
        WHERE m.listing_type = 'looking_for'
          AND m.status = 'available'
        ORDER BY m.listing_date DESC
    """)
    listings = cur.fetchall()

    cart_count = get_cart_count(session["user"])
    conn.close()

    return render_template("looking_for.html",
                         listings=listings,
                         cart_count=cart_count)

def register(application):
    application.add_url_rule('/marketplace', endpoint='marketplace', view_func=marketplace)
    application.add_url_rule('/marketplace/add', endpoint='add_marketplace_listing', view_func=add_marketplace_listing, methods=['GET', 'POST'])
    application.add_url_rule('/marketplace/buy/<int:listing_id>', endpoint='buy_marketplace_item', view_func=buy_marketplace_item, methods=['POST'])
    application.add_url_rule('/marketplace/complete-order/<int:listing_id>', endpoint='complete_marketplace_order', view_func=complete_marketplace_order, methods=['POST'])
    application.add_url_rule('/marketplace/confirm-receipt/<int:listing_id>', endpoint='confirm_marketplace_receipt', view_func=confirm_marketplace_receipt, methods=['POST'])
    application.add_url_rule('/marketplace/my-purchases', endpoint='my_marketplace_purchases', view_func=my_marketplace_purchases)
    application.add_url_rule('/marketplace/rate/<int:listing_id>', endpoint='rate_marketplace_seller', view_func=rate_marketplace_seller, methods=['POST'])
    application.add_url_rule('/marketplace/my-listings', endpoint='my_marketplace_listings', view_func=my_marketplace_listings)
    application.add_url_rule('/marketplace/delete/<int:listing_id>', endpoint='delete_marketplace_listing', view_func=delete_marketplace_listing, methods=['POST'])
    application.add_url_rule('/marketplace/trade/<int:listing_id>', endpoint='trade_marketplace_item', view_func=trade_marketplace_item, methods=['GET', 'POST'])
    application.add_url_rule('/api/listing/<int:listing_id>', endpoint='get_listing_api', view_func=get_listing_api)

    application.add_url_rule('/marketplace/product/<int:listing_id>', endpoint='product_detail', view_func=product_detail)

    application.add_url_rule('/marketplace/cart', endpoint='view_cart', view_func=view_cart)
    application.add_url_rule('/marketplace/cart/add/<int:listing_id>', endpoint='add_to_cart', view_func=add_to_cart, methods=['POST'])
    application.add_url_rule('/marketplace/cart/update/<int:cart_id>', endpoint='update_cart_item', view_func=update_cart_item, methods=['POST'])
    application.add_url_rule('/marketplace/cart/remove/<int:cart_id>', endpoint='remove_from_cart', view_func=remove_from_cart, methods=['POST'])
    application.add_url_rule('/marketplace/cart/checkout', endpoint='checkout_cart', view_func=checkout_cart, methods=['POST'])

    application.add_url_rule('/marketplace/edit/<int:listing_id>',
                        endpoint='edit_marketplace_listing',
                        view_func=edit_marketplace_listing,
                        methods=['GET', 'POST'])
    application.add_url_rule('/marketplace/delete-image/<int:image_id>',
                            endpoint='delete_listing_image',
                            view_func=delete_listing_image,
                            methods=['POST'])
    application.add_url_rule('/marketplace/set-thumbnail/<int:image_id>',
                        endpoint='set_listing_thumbnail',
                        view_func=set_listing_thumbnail,
                        methods=['POST'])

    application.add_url_rule('/marketplace/preorder/<int:listing_id>',
                        endpoint='create_preorder',
                        view_func=create_preorder,
                        methods=['POST'])
    application.add_url_rule('/marketplace/preorder/<int:order_id>/accept',
                            endpoint='accept_preorder',
                            view_func=accept_preorder,
                            methods=['POST'])
    application.add_url_rule('/marketplace/preorder/<int:order_id>/reject',
                            endpoint='reject_preorder',
                            view_func=reject_preorder,
                            methods=['POST'])
    application.add_url_rule('/marketplace/preorder/<int:order_id>/request-cancel',
                            endpoint='request_preorder_cancel',
                            view_func=request_preorder_cancel,
                            methods=['POST'])
    application.add_url_rule('/marketplace/preorder/<int:order_id>/approve-cancel',
                            endpoint='approve_preorder_cancel',
                            view_func=approve_preorder_cancel,
                            methods=['POST'])
    application.add_url_rule('/marketplace/my-preorders',
                            endpoint='my_preorders',
                            view_func=my_preorders)
    application.add_url_rule('/marketplace/my-preorder-requests',
                            endpoint='my_preorder_requests',
                            view_func=my_preorder_requests)

    application.add_url_rule('/marketplace/looking-for',
                            endpoint='looking_for_listings',
                            view_func=looking_for_listings)

    for _name in __all__:
        try:
            setattr(core, _name, globals()[_name])
        except Exception:
            pass


__all__ = [
    'marketplace',
    'add_marketplace_listing',
    'buy_marketplace_item',
    'complete_marketplace_order',
    'confirm_marketplace_receipt',
    'my_marketplace_purchases',
    'rate_marketplace_seller',
    'my_marketplace_listings',
    'delete_marketplace_listing',
    'trade_marketplace_item',
    'get_listing_api',
    'product_detail',
    'view_cart',
    'add_to_cart',
    'update_cart_item',
    'remove_from_cart',
    'checkout_cart',
    'get_cart_count',
    'create_preorder',
    'accept_preorder',
    'reject_preorder',
    'request_preorder_cancel',
    'approve_preorder_cancel',
    'my_preorders',
    'my_preorder_requests',
    'edit_marketplace_listing',
    'delete_listing_image',
    'set_listing_thumbnail',
    'allowed_file',
    'save_images_to_db',
]
from datetime import datetime, timedelta
from flask import flash, jsonify, redirect, render_template, request, session, url_for
from .. import legacy as core
from ..legacy import logger
from ..models.database import _save_upload_file, get_db

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

def marketplace():
    """View all marketplace listings"""
    if "user" not in session:
        return redirect("/login")
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get all available listings with user info
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
    
    # Get user's inventory for selling
    cur.execute("""
        SELECT crop_name, SUM(quantity) AS total_quantity
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING SUM(quantity) > 0
    """, (session["user"],))
    user_inventory = cur.fetchall()
    
    # Get all crops for the add listing form
    cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name")
    crops = cur.fetchall()

    # Delivered orders belonging to this buyer that still need a rating.
    # Only show pending ratings when seller has marked delivered AND buyer has confirmed receipt.
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
    
    conn.close()
    
    return render_template("marketplace.html", 
                         listings=listings, 
                         user_inventory=user_inventory,
                         crops=crops,
                         pending_ratings=pending_ratings)

def add_marketplace_listing():
    """Add a new listing to the marketplace"""
    if "user" not in session:
        return redirect("/login")
    
    if request.method == "POST":
        crop_id = request.form.get("crop_id")
        amount = request.form.get("amount")
        price = request.form.get("price")
        unit = request.form.get("unit", "kg")
        description = request.form.get("description", "").strip()
        expiry_days = request.form.get("expiry_days", 30)
        
        # Validate inputs
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
        
        conn = get_db()
        cur = conn.cursor()
        
        # Get crop name
        cur.execute("SELECT crops_name FROM crops WHERE id = ?", (crop_id,))
        crop = cur.fetchone()
        if not crop:
            flash("Invalid crop selected")
            conn.close()
            return redirect(request.url)
        
        crop_name = crop["crops_name"]
        
        # Check if user has enough inventory
        cur.execute("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE farmer = ? AND crop_name = ?
        """, (session["user"], crop_name))
        inventory = cur.fetchone()
        
        if not inventory or inventory["total"] < amount:
            flash(f"You don't have enough {crop_name} in your inventory. Available: {inventory['total'] if inventory else 0}")
            conn.close()
            return redirect(request.url)
        
        # Get user ID
        cur.execute("SELECT id, location FROM users WHERE username = ?", (session["user"],))
        user = cur.fetchone()
        
        if not user:
            flash("User not found")
            conn.close()
            return redirect(request.url)
        
        # Calculate expiry date
        expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert listing
        cur.execute("""
            INSERT INTO marketplace(
                user_id, username, crop_id, crop_name, amount, price,
                unit, status, listing_date, expiry_date, description, location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user["id"],
            session["user"],
            crop_id,
            crop_name,
            amount,
            price,
            unit,
            "available",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            expiry_date,
            description,
            user["location"]
        ))
        
        conn.commit()
        conn.close()
        
        flash(f"Listing for {crop_name} added successfully!")
        return redirect("/marketplace")
    
    # GET request - show form
    conn = get_db()
    cur = conn.cursor()
    
    # Get ONLY the crops that the user has in their inventory (unique crop names)
    cur.execute("""
        SELECT DISTINCT crop_name
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING SUM(quantity) > 0
        ORDER BY crop_name
    """, (session["user"],))
    user_crops = cur.fetchall()
    
    # Get the crop IDs for these crop names
    user_crops_with_ids = []
    for crop in user_crops:
        cur.execute("SELECT id FROM crops WHERE crops_name = ?", (crop["crop_name"],))
        crop_id = cur.fetchone()
        if crop_id:
            # Get total quantity available
            cur.execute("""
                SELECT SUM(quantity) as total_quantity
                FROM inventory
                WHERE farmer = ? AND crop_name = ?
            """, (session["user"], crop["crop_name"]))
            total = cur.fetchone()
            user_crops_with_ids.append({
                "id": crop_id["id"],
                "crops_name": crop["crop_name"],
                "total_quantity": total["total_quantity"] if total else 0
            })
    
    # Get user's inventory for display
    cur.execute("""
        SELECT crop_name, SUM(quantity) as total_quantity
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING SUM(quantity) > 0
        ORDER BY crop_name
    """, (session["user"],))
    user_inventory = cur.fetchall()
    
    conn.close()
    
    # If user has no crops in inventory, show a message
    if not user_crops_with_ids:
        flash("You don't have any crops in your inventory. Please upload harvest data first.", "warning")
    
    return render_template("add_listing.html", 
                         crops=user_crops_with_ids, 
                         user_inventory=user_inventory)

def buy_marketplace_item(listing_id):
    """Purchase an item from the marketplace"""
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
    
    # Get current user's ID
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    
    current_user_id = current_user["id"]
    
    # Get the listing
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
    
    # Determine seller username reliably
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

    # Calculate total price
    total_price = quantity * listing["price"]
    order_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Update the listing and create an order record for partial purchases
    if quantity == listing["amount"]:
        cur.execute("UPDATE marketplace SET status = 'sold', buyer_username = ?, order_status = 'sold', order_date = ?, delivery_confirmed = 0 WHERE id = ?", (
            session["user"],
            order_timestamp,
            listing_id
        ))
    else:
        cur.execute("""
            INSERT INTO marketplace (
                user_id, username, buyer_username, crop_id, crop_name, amount, price, unit,
                status, order_status, listing_date, order_date, expiry_date, description, location, delivery_confirmed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            listing["user_id"],
            listing["username"],
            session["user"],
            listing["crop_id"],
            listing["crop_name"],
            quantity,
            listing["price"],
            listing["unit"],
            "sold",
            "sold",
            listing["listing_date"],
            order_timestamp,
            listing["expiry_date"],
            listing["description"],
            listing["location"],
            0
        ))
        cur.execute("""
            UPDATE marketplace 
            SET amount = amount - ? 
            WHERE id = ?
        """, (quantity, listing_id))
    
    # Add to buyer's inventory (purchase source does not appear on harvest dashboard)
    cur.execute("""
        INSERT INTO inventory(crop_name, quantity, farmer, date_received, location, source)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        listing["crop_name"],
        quantity,
        session["user"],
        order_timestamp,
        listing["location"],
        "purchase"
    ))
    
    # Remove from seller's inventory
    cur.execute("""
        SELECT id, quantity FROM inventory 
        WHERE farmer = ? AND crop_name = ? 
        ORDER BY date_received ASC
    """, (seller_username, listing["crop_name"]))
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

    # Create notification for the seller about the purchase
    try:
        if seller_username:
            cur.execute(
                "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                (
                    seller_username,
                    "Item Sold",
                    f"{session['user']} purchased {quantity} {listing['crop_name']} from your listing.",
                    "marketplace",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    0
                )
            )
            conn.commit()
            logger.info(f"Marketplace purchase notification created for {seller_username}")
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
                (
                    listing["buyer_username"],
                    "Order Delivered",
                    f"Your order for {listing['crop_name']} has been marked delivered by {session['user']}. Please confirm receipt and then rate the seller.",
                    "marketplace",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    0
                )
            )
        except Exception:
            logger.exception("Failed to create delivery notification")

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Order marked as delivered."})

def confirm_marketplace_receipt(listing_id):
    """Buyer confirms receipt of delivered order. Seller must have marked delivered first."""
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cur = conn.cursor()

    # Ensure current user is the buyer for this listing
    cur.execute("SELECT * FROM marketplace WHERE id = ? AND buyer_username = ?", (listing_id, session["user"]))
    listing = cur.fetchone()
    if not listing:
        conn.close()
        return jsonify({"error": "Order not found or you are not the buyer"}), 404

    # Seller must have confirmed/delivered first
    try:
        delivery_confirmed = listing['delivery_confirmed']
    except Exception:
        delivery_confirmed = 0

    if not delivery_confirmed:
        conn.close()
        return jsonify({"error": "Seller has not confirmed delivery yet"}), 400

    # Buyer must not have already confirmed
    try:
        buyer_confirmed = listing['buyer_confirmed']
    except Exception:
        buyer_confirmed = 0

    if buyer_confirmed:
        conn.close()
        return jsonify({"status": "already_confirmed", "message": "You have already confirmed receipt."})

    # Mark buyer confirmation and optionally set order_status to completed
    cur.execute(
        "UPDATE marketplace SET buyer_confirmed = 1, buyer_confirm_date = ?, order_status = 'completed' WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing_id)
    )

    # Optionally update buyer completed_transactions/total_transactions
    try:
        cur.execute("""
            UPDATE users
            SET completed_transactions = COALESCE(completed_transactions, 0) + 1,
                total_transactions = COALESCE(total_transactions, 0) + 1
            WHERE username = ?
        """, (session["user"],))
    except Exception:
        # Non-critical if user columns missing
        logger.exception("Failed to update buyer transaction counts")

    # Notify seller that buyer confirmed and prompt for any follow-up
    try:
        cur.execute(
            "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
            (
                listing['username'],
                "Buyer Confirmed Receipt",
                f"{session['user']} has confirmed receipt for {listing['crop_name']}.",
                "marketplace",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                0
            )
        )
    except Exception:
        logger.exception("Failed to create buyer confirmation notification")

    conn.commit()
    conn.close()

    # After confirming receipt, buyer is expected to rate the seller.
    # Respond with JSON for AJAX clients, otherwise redirect back with a flash message for normal form submits.
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
    """View user's own marketplace listings"""
    if "user" not in session:
        return redirect("/login")
    
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
        WHERE m.user_id = ? AND m.status = 'available'
        ORDER BY m.listing_date DESC
    """, (current_user_id,))
    active_listings = cur.fetchall()

    cur.execute("""
        SELECT m.*
        FROM marketplace m
        WHERE m.user_id = ? AND m.status = 'sold'
        ORDER BY order_date DESC
    """, (current_user_id,))
    sold_orders = cur.fetchall()

    cur.execute("""
        SELECT m.*
        FROM marketplace m
        WHERE m.user_id = ? AND m.status = 'delivered'
        ORDER BY delivery_date DESC
    """, (current_user_id,))
    delivered_orders = cur.fetchall()
    
    conn.close()
    
    return render_template("my_listings.html", 
                         active_listings=active_listings, 
                         sold_orders=sold_orders,
                         delivered_orders=delivered_orders)

def delete_marketplace_listing(listing_id):
    """Delete a marketplace listing"""
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
    """Trade an item from the marketplace"""
    if "user" not in session:
        return redirect("/login")
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get current user's ID
    cur.execute("SELECT id FROM users WHERE username = ?", (session["user"],))
    current_user = cur.fetchone()
    if not current_user:
        flash("User not found")
        conn.close()
        return redirect("/marketplace")
    
    current_user_id = current_user["id"]
    
    # Get the listing
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
        
        # Check if user has the crop to trade
        cur.execute("""
            SELECT SUM(quantity) as total
            FROM inventory
            WHERE farmer = ? AND crop_name = ?
        """, (session["user"], trade_crop))
        inventory = cur.fetchone()
        
        if not inventory or inventory["total"] < trade_amount:
            flash(f"You don't have enough {trade_crop} to trade. Available: {inventory['total'] if inventory else 0}")
            conn.close()
            return redirect(request.url)
        
        # Process trade - Remove from buyer's inventory
        cur.execute("""
            SELECT id, quantity FROM inventory
            WHERE farmer = ? AND crop_name = ?
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
        
        # Add traded crop to seller's inventory
        # Resolve seller username reliably
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
            INSERT INTO inventory(crop_name, quantity, farmer, date_received, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            trade_crop,
            trade_amount,
            seller_username,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            listing["location"],
            "trade"
        ))
        
        # Add seller's crop to buyer's inventory
        cur.execute("""
            INSERT INTO inventory(crop_name, quantity, farmer, date_received, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            listing["crop_name"],
            listing["amount"],
            session["user"],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            session.get("location", ""),
            "trade"
        ))
        
        # Update listing status
        cur.execute("UPDATE marketplace SET status = 'traded' WHERE id = ?", (listing_id,))
        
        conn.commit()
        # Notify seller that a trade occurred
        try:
            if seller_username:
                cur.execute(
                    "INSERT INTO notifications(username,title,message,type,created_at,is_read) VALUES (?,?,?,?,?,?)",
                    (
                        seller_username,
                        "Item Traded",
                        f"{session['user']} completed a trade: gave {trade_amount} {trade_crop} and received your {listing['amount']} {listing['crop_name']}.",
                        "marketplace",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        0
                    )
                )
                conn.commit()
                logger.info(f"Marketplace trade notification created for {seller_username}")
        except Exception:
            logger.exception("Failed to create marketplace trade notification")

        conn.close()

        flash(f"Trade successful! You received {listing['amount']} {listing['crop_name']} and gave {trade_amount} {trade_crop}")
        return redirect("/marketplace")
    
    # GET request - show trade form
    cur.execute("""
        SELECT crop_name, SUM(quantity) AS total_quantity
        FROM inventory
        WHERE farmer = ?
        GROUP BY crop_name
        HAVING SUM(quantity) > 0
    """, (session["user"],))
    user_inventory = cur.fetchall()
    
    conn.close()
    
    return render_template("trade_listing.html", listing=listing, user_inventory=user_inventory)

def get_listing_api(listing_id):
    """Get listing details for the trade modal"""
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

def register(application):
    """Register this domain's routes on the existing Flask app."""
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
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['marketplace', 'add_marketplace_listing', 'buy_marketplace_item', 'complete_marketplace_order', 'confirm_marketplace_receipt', 'my_marketplace_purchases', 'rate_marketplace_seller', 'my_marketplace_listings', 'delete_marketplace_listing', 'trade_marketplace_item', 'get_listing_api']

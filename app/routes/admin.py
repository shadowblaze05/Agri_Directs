from datetime import datetime, timedelta, timezone
from functools import wraps
import csv
import io
import math

from flask import Response, abort, flash, redirect, render_template, request, session, stream_with_context, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .. import legacy as core
from ..extensions import db
from ..models.audit import AuditEvent
from ..models.database import _save_upload_file, get_db
from ..services.notification_service import notify_published_announcement

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

ADMIN_EDITABLE_MARKETPLACE_STATUSES = {"available", "expired", "cancelled"}


def _admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Admin access required", "warning")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped


def _redirect_admin(endpoint="admin"):
    return redirect(url_for(endpoint))


def _form_value(name):
    return request.form.get(name, "").strip()


@_admin_required
def create_admin_user():
    username = _form_value("username")
    email = _form_value("email").lower()
    password = request.form.get("password", "")
    role = _form_value("role") or "user"
    if not username or not password:
        flash("Username and password are required", "danger")
        return _redirect_admin("admin_users")
    if len(password) < 6:
        flash("Password must be at least 6 characters", "danger")
        return _redirect_admin("admin_users")
    if role not in {"user", "admin"}:
        flash("Invalid account role", "danger")
        return _redirect_admin("admin_users")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO users(username, first_name, last_name, email, password, role, location)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                username,
                _form_value("first_name") or username,
                _form_value("last_name") or "User",
                email or f"{username}@example.com",
                generate_password_hash(password),
                role,
                _form_value("location") or None,
            ),
        )
        conn.commit()
        flash(f"User {username} created", "success")
    except IntegrityError:
        flash("That username or email is already in use", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_users")


@_admin_required
def edit_admin_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("User not found", "danger")
        return _redirect_admin("admin_users")

    role = _form_value("role") or "user"
    if role not in {"user", "admin"}:
        conn.close()
        flash("Invalid account role", "danger")
        return _redirect_admin("admin_users")
    password = request.form.get("password", "")
    fields = [
        _form_value("first_name") or user["username"],
        _form_value("last_name") or "User",
        _form_value("email").lower() or f"{user['username']}@example.com",
        role,
        _form_value("location") or None,
    ]
    query = """UPDATE users SET first_name=?, last_name=?, email=?, role=?, location=?"""
    if password:
        if len(password) < 6:
            conn.close()
            flash("Password must be at least 6 characters", "danger")
            return _redirect_admin("admin_users")
        query += ", password=?"
        fields.append(generate_password_hash(password))
    query += " WHERE id=?"
    fields.append(user_id)
    try:
        cur.execute(query, fields)
        conn.commit()
        flash(f"User {user['username']} updated", "success")
    except IntegrityError:
        flash("That email address is already in use", "danger")
    finally:
        conn.close()
    return _redirect_admin("admin_users")


@_admin_required
def delete_admin_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("User not found", "danger")
        return _redirect_admin("admin_users")
    if user["username"] == session.get("user"):
        conn.close()
        flash("You cannot delete your own administrator account", "danger")
        return _redirect_admin("admin_users")
    cur.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash(f"User {user['username']} deleted", "success")
    return _redirect_admin("admin_users")


def _save_named_record(table, column, success_message, endpoint="admin_catalog"):
    value = _form_value("name")
    if not value:
        flash("A name is required", "danger")
        return _redirect_admin(endpoint)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"INSERT INTO {table}({column}) VALUES (?)", (value,))
        conn.commit()
        flash(success_message, "success")
    except IntegrityError:
        flash("That name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin(endpoint)


@_admin_required
def create_crop_category():
    description = _form_value("description")
    response = _save_named_record("crop_categories", "name", "Crop category created")
    if description:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE crop_categories SET description=? WHERE name=?",
            (description, _form_value("name")),
        )
        conn.commit()
        conn.close()
    return response


@_admin_required
def edit_crop_category(category_id):
    return _edit_named_record("crop_categories", "name", "id", category_id, "Crop category updated", "description")


@_admin_required
def delete_crop_category(category_id):
    return _delete_named_record("crop_categories", "id", category_id, "Crop category deleted")


@_admin_required
def create_crop():
    return _save_named_record("crops", "crops_name", "Crop created")


@_admin_required
def edit_crop(crop_id):
    return _edit_named_record("crops", "crops_name", "id", crop_id, "Crop updated")


@_admin_required
def delete_crop(crop_id):
    return _delete_named_record("crops", "id", crop_id, "Crop deleted")


@_admin_required
def create_knowledge_category():
    return _save_named_record(
        "knowledge_categories", "category_name", "Knowledge category created", "admin_knowledge_categories"
    )


@_admin_required
def edit_knowledge_category(category_id):
    return _edit_named_record("knowledge_categories", "category_name", "category_id", category_id, "Knowledge category updated", endpoint="admin_knowledge_categories")


@_admin_required
def delete_knowledge_category(category_id):
    return _delete_named_record("knowledge_categories", "category_id", category_id, "Knowledge category deleted", endpoint="admin_knowledge_categories")


def _edit_named_record(table, column, id_column, record_id, message, extra_column=None, endpoint="admin_catalog"):
    value = _form_value("name")
    if not value:
        flash("A name is required", "danger")
        return _redirect_admin(endpoint)
    conn = get_db()
    values = [value]
    query = f"UPDATE {table} SET {column}=?"
    if extra_column:
        query += f", {extra_column}=?"
        values.append(_form_value("description") or None)
    query += f" WHERE {id_column}=?"
    values.append(record_id)
    try:
        cur = conn.cursor()
        cur.execute(query, values)
        conn.commit()
        flash(message, "success")
    except IntegrityError:
        flash("That name already exists", "danger")
    finally:
        conn.close()
    return _redirect_admin(endpoint)


def _delete_named_record(table, id_column, record_id, message, endpoint="admin_catalog"):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"DELETE FROM {table} WHERE {id_column}=?", (record_id,))
        conn.commit()
        flash(message, "success")
    except IntegrityError:
        flash("This record is still in use and cannot be deleted", "danger")
    finally:
        conn.close()
    return _redirect_admin(endpoint)


def admin_knowledge():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    search = request.args.get("q", "").strip()
    search_filter = ""
    params = []
    if search:
        search_filter = "WHERE kp.title LIKE ? OR kp.author LIKE ? OR kc.category_name LIKE ?"
        params = [f"%{search}%"] * 3
    cur.execute(f"""
        SELECT kp.post_id, kp.title, kp.status, kp.is_pinned, kp.created_at, kp.views, kc.category_name, kp.author
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        {search_filter}
        ORDER BY kp.is_pinned DESC, kp.created_at DESC
    """, params)
    posts = cur.fetchall()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    cur.execute("SELECT COUNT(*) AS total_posts FROM knowledge_posts")
    total_posts = cur.fetchone()["total_posts"]
    cur.execute("SELECT COUNT(*) AS published_posts FROM knowledge_posts WHERE status = 'Published'")
    published_posts = cur.fetchone()["published_posts"]
    cur.execute("SELECT COUNT(*) AS draft_posts FROM knowledge_posts WHERE status = 'Draft'")
    draft_posts = cur.fetchone()["draft_posts"]
    conn.close()
    return render_template(
        "admin_knowledge.html",
        posts=posts,
        categories=categories,
        total_posts=total_posts,
        published_posts=published_posts,
        draft_posts=draft_posts,
        search=search,
    )

def create_knowledge_post():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    conn.close()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id") or None
        status = request.form.get("status", "Published")
        is_pinned = request.form.get("is_pinned") == "1"
        if not title or not content:
            flash("Title and content are required")
            return render_template("create_post.html", categories=categories)

        image_path = _save_upload_file(request.files.get("image"), "images")
        video_path = _save_upload_file(request.files.get("video"), "videos")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_posts
                (title, content, category_id, author, image, video, status, is_pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING post_id
            """,
            (
                title, content, category_id, session.get("user"), image_path,
                video_path, status, int(is_pinned),
            ),
        )
        created_post = cur.fetchone()
        if is_pinned and status == "Published":
            notify_published_announcement(cur, created_post["post_id"], title)
        conn.commit()
        conn.close()
        flash("Article created successfully")
        return redirect("/admin/knowledge")

    return render_template("create_post.html", categories=categories)

def edit_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM knowledge_posts WHERE post_id=?", (post_id,))
    post = cur.fetchone()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()
    conn.close()

    if not post:
        flash("Post not found")
        return redirect("/admin/knowledge")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id") or None
        status = request.form.get("status", "Published")
        is_pinned = request.form.get("is_pinned") == "1"
        if not title or not content:
            flash("Title and content are required")
            return render_template("edit_post.html", post=post, categories=categories)

        image_path = _save_upload_file(request.files.get("image"), "images") or post["image"]
        video_path = _save_upload_file(request.files.get("video"), "videos") or post["video"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_posts
            SET title=?, content=?, category_id=?, image=?, video=?, status=?, is_pinned=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE post_id=?
            """,
            (
                title, content, category_id, image_path, video_path, status,
                int(is_pinned), post_id,
            ),
        )
        if (
            is_pinned
            and status == "Published"
            and (not post["is_pinned"] or post["status"] != "Published")
        ):
            notify_published_announcement(cur, post_id, title)
        conn.commit()
        conn.close()
        flash("Article updated successfully")
        return redirect("/admin/knowledge")

    return render_template("edit_post.html", post=post, categories=categories)

def delete_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM knowledge_replies WHERE comment_id IN (SELECT comment_id FROM knowledge_comments WHERE post_id=?)", (post_id,))
    cur.execute("DELETE FROM knowledge_comments WHERE post_id=?", (post_id,))
    cur.execute("DELETE FROM knowledge_likes WHERE post_id=?", (post_id,))
    cur.execute("DELETE FROM knowledge_posts WHERE post_id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("Article deleted successfully")
    return redirect("/admin/knowledge")

def admin():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""SELECT i.*, c.crops_name AS crop_name
                   FROM inventory i LEFT JOIN crops c ON c.id=i.crop_id
                   ORDER BY date_received DESC""")
    inventory = cur.fetchall()
    cur.execute("""SELECT id, username, first_name, last_name, email, role, location,
                   reliability_status, completed_transactions, cancelled_transactions,
                   total_transactions FROM users ORDER BY role, username""")
    users = cur.fetchall()
    cur.execute("SELECT id, name, description FROM crop_categories ORDER BY name")
    crop_categories = cur.fetchall()
    cur.execute("SELECT id, crops_name, category_id FROM crops ORDER BY crops_name")
    crops = cur.fetchall()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    knowledge_categories = cur.fetchall()
    stats = {
        "users": cur.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"],
        "admins": cur.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin'").fetchone()["count"],
        "crops": cur.execute("SELECT COUNT(*) AS count FROM crops").fetchone()["count"],
        "articles": cur.execute("SELECT COUNT(*) AS count FROM knowledge_posts").fetchone()["count"],
        "marketplace": cur.execute("SELECT COUNT(*) AS count FROM marketplace").fetchone()["count"],
    }
    conn.close()
    return render_template(
        "admin.html",
        stats=stats,
    )


@_admin_required
def admin_users():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    query = """SELECT id, username, first_name, last_name, email, role, location,
               reliability_status, completed_transactions, cancelled_transactions,
               total_transactions FROM users"""
    params = []
    if search:
        query += """ WHERE username LIKE ? OR email LIKE ? OR first_name LIKE ?
                     OR last_name LIKE ? OR role LIKE ? OR location LIKE ?"""
        params = [f"%{search}%"] * 6
    query += " ORDER BY role, username"
    users = cur.execute(query, params).fetchall()
    conn.close()
    return render_template("admin_users.html", users=users, search=search)


@_admin_required
def admin_catalog():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    pattern = f"%{search}%"
    crops = cur.execute(
        """SELECT id, crops_name, category_id FROM crops
           WHERE ? = '' OR crops_name LIKE ? ORDER BY crops_name""",
        (search, pattern),
    ).fetchall()
    crop_categories = cur.execute(
        """SELECT id, name, description FROM crop_categories
           WHERE ? = '' OR name LIKE ? OR description LIKE ? ORDER BY name""",
        (search, pattern, pattern),
    ).fetchall()
    conn.close()
    return render_template(
        "admin_catalog.html",
        crops=crops,
        crop_categories=crop_categories,
        search=search,
    )


@_admin_required
def admin_inventory():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    query = """SELECT i.*, c.crops_name AS crop_name
               FROM inventory i LEFT JOIN crops c ON c.id=i.crop_id"""
    params = []
    if search:
        query += " WHERE c.crops_name LIKE ? OR i.farmer LIKE ? OR i.location LIKE ?"
        params = [f"%{search}%"] * 3
    query += " ORDER BY i.date_received DESC"
    inventory = cur.execute(query, params).fetchall()
    conn.close()
    return render_template("admin_inventory.html", inventory=inventory, search=search)


@_admin_required
def admin_marketplace():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    listings = cur.execute(
        """SELECT m.*, u.username AS seller_name
           FROM marketplace m LEFT JOIN users u ON u.id=m.user_id
           WHERE ? = '' OR m.crop_name LIKE ? OR COALESCE(u.username, m.username, '') LIKE ?
             OR COALESCE(m.status, '') LIKE ?
           ORDER BY m.listing_date DESC, m.id DESC""",
        (search, f"%{search}%", f"%{search}%", f"%{search}%"),
    ).fetchall()
    users = cur.execute("SELECT id, username, location FROM users ORDER BY username").fetchall()
    crops = cur.execute("SELECT id, crops_name FROM crops ORDER BY crops_name").fetchall()
    conn.close()
    return render_template(
        "admin_marketplace.html",
        listings=listings,
        users=users,
        crops=crops,
        search=search,
    )


def _admin_marketplace_values():
    username = _form_value("username")
    crop_id_value = _form_value("crop_id")
    unit = _form_value("unit") or "kg"
    description = _form_value("description")[:2000]
    listing_type = _form_value("listing_type")
    status = _form_value("status") or "available"

    if not username or not crop_id_value:
        raise ValueError("Choose a seller and crop.")
    if listing_type not in {"standard", "preorder", "looking_for"}:
        raise ValueError("Choose a valid listing type.")
    if status not in {"available", "expired", "cancelled"}:
        raise ValueError("Choose a valid listing status.")
    if not unit or len(unit) > 32:
        raise ValueError("Enter a valid unit (up to 32 characters).")

    try:
        crop_id = int(crop_id_value)
        amount = int(_form_value("amount"))
        price = float(_form_value("price"))
        expiry_days = int(_form_value("expiry_days") or "30")
    except ValueError as error:
        raise ValueError("Choose a valid crop and enter valid amount, price, and expiry numbers.") from error
    if amount <= 0 or not math.isfinite(price) or price <= 0:
        raise ValueError("Amount and price must be greater than zero.")
    if expiry_days < 1 or expiry_days > 365:
        raise ValueError("Expiry must be between 1 and 365 days.")

    available_date = _form_value("available_date")
    if listing_type == "preorder":
        try:
            datetime.strptime(available_date, "%Y-%m-%dT%H:%M")
        except ValueError as error:
            raise ValueError("Pre-orders require a valid ready date and time.") from error
        available_date = available_date.replace("T", " ")
    else:
        available_date = None

    return username, crop_id, amount, price, unit, description, listing_type, status, available_date, expiry_days


@_admin_required
def create_admin_marketplace_listing():
    try:
        values = _admin_marketplace_values()
    except ValueError as error:
        flash(str(error), "danger")
        return _redirect_admin("admin_marketplace")

    username, crop_id, amount, price, unit, description, listing_type, status, available_date, expiry_days = values
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute(
        "SELECT id, username, location FROM users WHERE username=?",
        (username,),
    ).fetchone()
    crop = cur.execute(
        "SELECT id, crops_name FROM crops WHERE id=?",
        (crop_id,),
    ).fetchone()
    if not user or not crop:
        conn.close()
        flash("Choose an existing seller and crop.", "danger")
        return _redirect_admin("admin_marketplace")

    now = datetime.now(timezone.utc)
    cur.execute(
        """INSERT INTO marketplace(
               user_id, username, crop_id, crop_name, amount, price, unit, status,
               listing_date, expiry_date, description, location, listing_type, available_date
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user["id"], user["username"], crop["id"], crop["crops_name"], amount, price,
            unit, status, now.strftime("%Y-%m-%d %H:%M:%S"),
            (now + timedelta(days=expiry_days)).strftime("%Y-%m-%d %H:%M:%S"),
            description, user["location"], listing_type, available_date,
        ),
    )
    conn.commit()
    conn.close()
    flash("Marketplace listing created.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def edit_admin_marketplace_listing(listing_id):
    try:
        values = _admin_marketplace_values()
    except ValueError as error:
        flash(str(error), "danger")
        return _redirect_admin("admin_marketplace")

    username, crop_id, amount, price, unit, description, listing_type, status, available_date, _ = values
    conn = get_db()
    cur = conn.cursor()
    listing = cur.execute(
        "SELECT buyer_username, status, username FROM marketplace WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        conn.close()
        flash("Marketplace listing not found.", "danger")
        return _redirect_admin("admin_marketplace")
    if listing["buyer_username"] or listing["status"] not in ADMIN_EDITABLE_MARKETPLACE_STATUSES:
        conn.close()
        flash("Listings with an order or completed transaction cannot be edited.", "danger")
        return _redirect_admin("admin_marketplace")

    user = cur.execute(
        "SELECT id, username, location FROM users WHERE username=?",
        (username,),
    ).fetchone()
    crop = cur.execute(
        "SELECT id, crops_name FROM crops WHERE id=?",
        (crop_id,),
    ).fetchone()
    if not user or not crop:
        conn.close()
        flash("Choose an existing seller and crop.", "danger")
        return _redirect_admin("admin_marketplace")

    seller_changed = username != listing["username"]
    update_fields = (
            user["id"], user["username"], crop["id"], crop["crops_name"], amount, price,
            unit, status, description, user["location"], listing_type, available_date,
        )
    if seller_changed:
        cur.execute(
            """UPDATE marketplace
               SET user_id=?, username=?, crop_id=?, crop_name=?, amount=?, price=?, unit=?,
                   status=?, description=?, location=?, listing_type=?, available_date=?,
                   main_image=NULL, thumbnail_verified=0, thumbnail_latitude=NULL,
                   thumbnail_longitude=NULL, thumbnail_distance_meters=NULL,
                   thumbnail_captured_at=NULL
               WHERE id=?""",
            update_fields + (listing_id,),
        )
    else:
        cur.execute(
            """UPDATE marketplace
               SET user_id=?, username=?, crop_id=?, crop_name=?, amount=?, price=?, unit=?,
                   status=?, description=?, location=?, listing_type=?, available_date=?
               WHERE id=?""",
            update_fields + (listing_id,),
        )
    conn.commit()
    conn.close()
    flash("Marketplace listing updated.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def delete_admin_marketplace_listing(listing_id):
    conn = get_db()
    cur = conn.cursor()
    listing = cur.execute(
        "SELECT crop_name, buyer_username, status FROM marketplace WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        conn.close()
        flash("Marketplace listing not found.", "danger")
        return _redirect_admin("admin_marketplace")
    if listing["buyer_username"] or listing["status"] not in ADMIN_EDITABLE_MARKETPLACE_STATUSES:
        conn.close()
        flash("Listings with an order or completed transaction cannot be deleted.", "danger")
        return _redirect_admin("admin_marketplace")

    cur.execute("DELETE FROM marketplace WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()
    flash(f"Marketplace listing for {listing['crop_name']} deleted.", "success")
    return _redirect_admin("admin_marketplace")


@_admin_required
def admin_review_geotag(item_id):
    decision = _form_value("decision")
    if decision not in {"approved", "rejected"}:
        flash("Choose approve or reject for this harvest review", "danger")
        return redirect(url_for("admin_inventory"))

    conn = get_db()
    cur = conn.cursor()
    record = cur.execute(
        "SELECT verification_notes, source FROM inventory WHERE id=?",
        (item_id,),
    ).fetchone()
    if not record:
        conn.close()
        flash("Harvest record not found", "danger")
        return redirect(url_for("admin_inventory"))
    if record["source"] not in (None, "harvest"):
        conn.close()
        flash("Only harvest submissions can receive a geotag decision", "danger")
        return redirect(url_for("admin_inventory"))

    reviewed_at = datetime.now(timezone.utc).isoformat()
    review_note = _form_value("review_note")[:1000]
    existing_note = record["verification_notes"] or ""
    if review_note:
        review_note = f"{existing_note} Admin review: {review_note}".strip()
    else:
        review_note = existing_note or None
    cur.execute(
        "UPDATE inventory SET verification_status=?, reviewed_by=?, reviewed_at=?, "
        "verification_notes=? "
        "WHERE id=?",
        (
            decision,
            session["user"],
            reviewed_at,
            review_note,
            item_id,
        ),
    )
    conn.commit()
    conn.close()
    flash(f"Harvest submission {decision}.", "success")
    return redirect(url_for("admin_inventory"))


@_admin_required
def admin_knowledge_categories():
    search = request.args.get("q", "").strip()
    conn = get_db()
    cur = conn.cursor()
    categories = cur.execute(
        """SELECT category_id, category_name FROM knowledge_categories
           WHERE ? = '' OR category_name LIKE ? ORDER BY category_name""",
        (search, f"%{search}%"),
    ).fetchall()
    conn.close()
    return render_template("admin_knowledge_categories.html", categories=categories, search=search)


def _audit_log_filters():
    search = request.args.get("q", "").strip()[:200]
    category = request.args.get("category", "").strip()
    method = request.args.get("method", "").strip().upper()
    result = request.args.get("result", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    valid_categories = {
        "Administration", "Application", "API", "Authentication",
        "Inventory", "Knowledge", "Marketplace", "Messages", "Notifications", "Profile",
    }
    valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    if category and category not in valid_categories:
        abort(400, description="Invalid audit-log category.")
    if method and method not in valid_methods:
        abort(400, description="Invalid audit-log method.")
    if result and result not in {"success", "failure"}:
        abort(400, description="Invalid audit-log result filter.")

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end_date else None
    except ValueError:
        abort(400, description="Audit-log dates must use YYYY-MM-DD.")
    if start and end and start > end:
        abort(400, description="The start date must not be after the end date.")

    filters = []
    if search:
        pattern = f"%{search}%"
        filters.append(or_(
            AuditEvent.actor.ilike(pattern),
            AuditEvent.action.ilike(pattern),
            AuditEvent.category.ilike(pattern),
            AuditEvent.endpoint.ilike(pattern),
            AuditEvent.path.ilike(pattern),
            AuditEvent.ip_address.ilike(pattern),
        ))
    if category:
        filters.append(AuditEvent.category == category)
    if method:
        filters.append(AuditEvent.method == method)
    if result == "success":
        filters.append(AuditEvent.status_code < 400)
    elif result == "failure":
        filters.append(AuditEvent.status_code >= 400)
    if start:
        filters.append(AuditEvent.occurred_at >= start)
    if end:
        filters.append(AuditEvent.occurred_at < end + timedelta(days=1))

    return {
        "filters": filters,
        "search": search,
        "category": category,
        "method": method,
        "result": result,
        "start_date": start_date,
        "end_date": end_date,
    }


def _csv_cell(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@_admin_required
def admin_audit_logs():
    filter_values = _audit_log_filters()
    filters = filter_values["filters"]
    base_query = select(AuditEvent).where(*filters)

    if request.args.get("export") == "csv":
        def generate_csv():
            yield "\ufeff"
            with db.engine.connect() as connection:
                statement = (
                    select(AuditEvent.__table__)
                    .where(*filters)
                    .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                )
                rows = connection.execution_options(stream_results=True).execute(statement)
                output = io.StringIO(newline="")
                writer = csv.writer(output)
                writer.writerow((
                    "Occurred at (UTC)", "Actor", "Role", "Action", "Category",
                    "Method", "Endpoint", "Path", "Status code", "Duration (ms)",
                    "IP address", "User agent", "Route parameters",
                ))
                yield output.getvalue()
                for row in rows:
                    event = row._mapping
                    output = io.StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(_csv_cell(value) for value in (
                        event["occurred_at"].isoformat() if event["occurred_at"] else "",
                        event["actor"],
                        event["role"],
                        event["action"],
                        event["category"],
                        event["method"],
                        event["endpoint"],
                        event["path"],
                        event["status_code"],
                        event["duration_ms"],
                        event["ip_address"],
                        event["user_agent"],
                        event["details"],
                    ))
                    yield output.getvalue()

        filename = f"agri-direct-audit-log-{datetime.now(timezone.utc):%Y%m%d}.csv"
        return Response(
            stream_with_context(generate_csv()),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = 50
    total = db.session.scalar(
        select(func.count()).select_from(AuditEvent).where(*filters)
    ) or 0
    pages = max(math.ceil(total / page_size), 1)
    events = db.session.scalars(
        base_query
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.occurred_at >= today_start)
    ) or 0
    failure_count = db.session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.status_code >= 400)
    ) or 0
    categories = db.session.scalars(
        select(AuditEvent.category).distinct().order_by(AuditEvent.category)
    ).all()

    return render_template(
        "admin_audit_logs.html",
        events=events,
        total=total,
        today_count=today_count,
        failure_count=failure_count,
        categories=categories,
        page=page,
        pages=pages,
        page_size=page_size,
        **{key: value for key, value in filter_values.items() if key != "filters"},
    )


def page_not_found(e):
    return render_template('404.html'), 404

def internal_error(e):
    return render_template('500.html'), 500

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/admin/knowledge', endpoint='admin_knowledge', view_func=admin_knowledge)
    application.add_url_rule('/admin/knowledge/create', endpoint='create_knowledge_post', view_func=create_knowledge_post, methods=['GET', 'POST'])
    application.add_url_rule('/admin/knowledge/edit/<int:post_id>', endpoint='edit_knowledge_post', view_func=edit_knowledge_post, methods=['GET', 'POST'])
    application.add_url_rule('/admin/knowledge/delete/<int:post_id>', endpoint='delete_knowledge_post', view_func=delete_knowledge_post, methods=['POST'])
    application.add_url_rule('/admin', endpoint='admin', view_func=admin)
    application.add_url_rule('/admin/audit-logs', endpoint='admin_audit_logs', view_func=admin_audit_logs)
    application.add_url_rule('/admin/users', endpoint='admin_users', view_func=admin_users)
    application.add_url_rule('/admin/catalog', endpoint='admin_catalog', view_func=admin_catalog)
    application.add_url_rule('/admin/inventory', endpoint='admin_inventory', view_func=admin_inventory)
    application.add_url_rule('/admin/marketplace', endpoint='admin_marketplace', view_func=admin_marketplace)
    application.add_url_rule('/admin/marketplace/create', endpoint='create_admin_marketplace_listing', view_func=create_admin_marketplace_listing, methods=['POST'])
    application.add_url_rule('/admin/marketplace/edit/<int:listing_id>', endpoint='edit_admin_marketplace_listing', view_func=edit_admin_marketplace_listing, methods=['POST'])
    application.add_url_rule('/admin/marketplace/delete/<int:listing_id>', endpoint='delete_admin_marketplace_listing', view_func=delete_admin_marketplace_listing, methods=['POST'])
    application.add_url_rule('/admin/geotag/<int:item_id>/review', endpoint='admin_review_geotag', view_func=admin_review_geotag, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories', endpoint='admin_knowledge_categories', view_func=admin_knowledge_categories)
    application.add_url_rule('/admin/users/create', endpoint='create_admin_user', view_func=create_admin_user, methods=['POST'])
    application.add_url_rule('/admin/users/edit/<int:user_id>', endpoint='edit_admin_user', view_func=edit_admin_user, methods=['POST'])
    application.add_url_rule('/admin/users/delete/<int:user_id>', endpoint='delete_admin_user', view_func=delete_admin_user, methods=['POST'])
    application.add_url_rule('/admin/crop-categories/create', endpoint='create_crop_category', view_func=create_crop_category, methods=['POST'])
    application.add_url_rule('/admin/crop-categories/edit/<int:category_id>', endpoint='edit_crop_category', view_func=edit_crop_category, methods=['POST'])
    application.add_url_rule('/admin/crop-categories/delete/<int:category_id>', endpoint='delete_crop_category', view_func=delete_crop_category, methods=['POST'])
    application.add_url_rule('/admin/crops/create', endpoint='create_crop', view_func=create_crop, methods=['POST'])
    application.add_url_rule('/admin/crops/edit/<int:crop_id>', endpoint='edit_crop', view_func=edit_crop, methods=['POST'])
    application.add_url_rule('/admin/crops/delete/<int:crop_id>', endpoint='delete_crop', view_func=delete_crop, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories/create', endpoint='create_knowledge_category', view_func=create_knowledge_category, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories/edit/<int:category_id>', endpoint='edit_knowledge_category', view_func=edit_knowledge_category, methods=['POST'])
    application.add_url_rule('/admin/knowledge-categories/delete/<int:category_id>', endpoint='delete_knowledge_category', view_func=delete_knowledge_category, methods=['POST'])
    application.register_error_handler(404, page_not_found)
    application.register_error_handler(500, internal_error)
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = [
    'admin_knowledge', 'create_knowledge_post', 'edit_knowledge_post', 'delete_knowledge_post',
    'admin', 'admin_users', 'admin_catalog', 'admin_inventory', 'admin_marketplace',
    'admin_audit_logs',
    'create_admin_marketplace_listing', 'edit_admin_marketplace_listing', 'delete_admin_marketplace_listing',
    'admin_review_geotag', 'admin_knowledge_categories',
    'create_admin_user', 'edit_admin_user', 'delete_admin_user',
    'create_crop_category', 'edit_crop_category', 'delete_crop_category',
    'create_crop', 'edit_crop', 'delete_crop',
    'create_knowledge_category', 'edit_knowledge_category', 'delete_knowledge_category',
    'page_not_found', 'internal_error'
]

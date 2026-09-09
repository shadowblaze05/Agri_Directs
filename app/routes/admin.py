from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .. import legacy as core
from ..models.database import _save_upload_file, get_db

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})


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
        SELECT kp.post_id, kp.title, kp.status, kp.created_at, kp.views, kc.category_name, kp.author
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        {search_filter}
        ORDER BY kp.created_at DESC
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
        if not title or not content:
            flash("Title and content are required")
            return render_template("create_post.html", categories=categories)

        image_path = _save_upload_file(request.files.get("image"), "images")
        video_path = _save_upload_file(request.files.get("video"), "videos")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_posts (title, content, category_id, author, image, video, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, content, category_id, session.get("user"), image_path, video_path, status),
        )
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
            SET title=?, content=?, category_id=?, image=?, video=?, status=?, updated_at=CURRENT_TIMESTAMP
            WHERE post_id=?
            """,
            (title, content, category_id, image_path, video_path, status, post_id),
        )
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
    application.add_url_rule('/admin/users', endpoint='admin_users', view_func=admin_users)
    application.add_url_rule('/admin/catalog', endpoint='admin_catalog', view_func=admin_catalog)
    application.add_url_rule('/admin/inventory', endpoint='admin_inventory', view_func=admin_inventory)
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
    'admin', 'admin_users', 'admin_catalog', 'admin_inventory', 'admin_knowledge_categories',
    'create_admin_user', 'edit_admin_user', 'delete_admin_user',
    'create_crop_category', 'edit_crop_category', 'delete_crop_category',
    'create_crop', 'edit_crop', 'delete_crop',
    'create_knowledge_category', 'edit_knowledge_category', 'delete_knowledge_category',
    'page_not_found', 'internal_error'
]

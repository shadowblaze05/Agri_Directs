from flask import flash, redirect, render_template, request, session
from .. import legacy as core
from ..models.database import _save_upload_file, get_db

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

def admin_knowledge():
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Admin access required")
        return redirect("/dashboard")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT kp.post_id, kp.title, kp.status, kp.created_at, kp.views, kc.category_name, kp.author
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        ORDER BY kp.created_at DESC
    """)
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
    cur.execute("SELECT * FROM inventory ORDER BY date_received DESC")
    inventory = cur.fetchall()
    cur.execute("SELECT username, role, reliability_status, completed_transactions, cancelled_transactions, total_transactions FROM users ORDER BY role, username")
    users = cur.fetchall()
    conn.close()
    return render_template("admin.html", inventory=inventory, users=users)

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
    application.register_error_handler(404, page_not_found)
    application.register_error_handler(500, internal_error)
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['admin_knowledge', 'create_knowledge_post', 'edit_knowledge_post', 'delete_knowledge_post', 'admin', 'page_not_found', 'internal_error']

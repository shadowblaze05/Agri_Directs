from flask import flash, jsonify, redirect, render_template, request, session, url_for
from .. import legacy as core
from ..models.database import get_db

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

def knowledge_feed():
    if "user" not in session:
        return redirect("/login")

    query = request.args.get("q", "").strip()
    category_id = request.args.get("category_id", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category_id, category_name FROM knowledge_categories ORDER BY category_name")
    categories = cur.fetchall()

    sql = """
        SELECT kp.post_id, kp.title, kp.content, kp.image, kp.video, kp.status, kp.views, kp.created_at,
               kp.author, kc.category_name, kc.category_id,
               (SELECT COUNT(*) FROM knowledge_likes kl WHERE kl.post_id = kp.post_id) AS like_count,
               (SELECT COUNT(*) FROM knowledge_comments kcmt WHERE kcmt.post_id = kp.post_id) AS comment_count
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        WHERE kp.status = 'Published'
    """
    params = []
    if query:
        sql += " AND (kp.title LIKE ? OR kp.content LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if category_id:
        sql += " AND kp.category_id = ?"
        params.append(category_id)
    sql += " ORDER BY kp.created_at DESC"

    posts = cur.execute(sql, params).fetchall()
    conn.close()
    return render_template("knowledge.html", posts=posts, categories=categories, query=query, category_id=category_id)

def knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT kp.post_id, kp.title, kp.content, kp.image, kp.video, kp.status, kp.views, kp.created_at,
               kp.author, kp.category_id, kc.category_name,
               (SELECT COUNT(*) FROM knowledge_likes kl WHERE kl.post_id = kp.post_id) AS like_count
        FROM knowledge_posts kp
        LEFT JOIN knowledge_categories kc ON kp.category_id = kc.category_id
        WHERE kp.post_id = ?
    """, (post_id,))
    post = cur.fetchone()
    if not post:
        conn.close()
        flash("Article not found")
        return redirect("/knowledge")

    cur.execute("UPDATE knowledge_posts SET views = views + 1 WHERE post_id=?", (post_id,))
    conn.commit()

    cur.execute("SELECT comment_id, username, comment, created_at FROM knowledge_comments WHERE post_id=? ORDER BY created_at ASC", (post_id,))
    comments = cur.fetchall()
    replies = {}
    for comment in comments:
        cur.execute("SELECT reply_id, username, reply, created_at FROM knowledge_replies WHERE comment_id=? ORDER BY created_at ASC", (comment["comment_id"],))
        replies[comment["comment_id"]] = cur.fetchall()

    cur.execute("SELECT COUNT(*) AS liked FROM knowledge_likes WHERE post_id=? AND username=?", (post_id, session.get("user")))
    liked = cur.fetchone()["liked"] > 0
    conn.close()
    return render_template("knowledge_post.html", post=post, comments=comments, replies=replies, liked=liked)

def like_knowledge_post(post_id):
    if "user" not in session:
        return jsonify({"status": "error", "message": "Please log in first"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS liked FROM knowledge_likes WHERE post_id=? AND username=?", (post_id, session.get("user")))
    already_liked = cur.fetchone()["liked"] > 0

    if already_liked:
        cur.execute("DELETE FROM knowledge_likes WHERE post_id=? AND username=?", (post_id, session.get("user")))
        status = "unliked"
    else:
        cur.execute("INSERT INTO knowledge_likes (post_id, username) VALUES (?, ?)", (post_id, session.get("user")))
        status = "liked"

    conn.commit()
    cur.execute("SELECT COUNT(*) AS like_count FROM knowledge_likes WHERE post_id=?", (post_id,))
    like_count = cur.fetchone()["like_count"]
    conn.close()
    return jsonify({"status": status, "like_count": like_count})

def comment_knowledge_post(post_id):
    if "user" not in session:
        return redirect("/login")

    comment = request.form.get("comment", "").strip()
    if not comment:
        flash("Comment cannot be empty")
        return redirect(url_for("knowledge_post", post_id=post_id))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO knowledge_comments (post_id, username, comment) VALUES (?, ?, ?)", (post_id, session.get("user"), comment))
    conn.commit()
    conn.close()
    flash("Comment added")
    return redirect(url_for("knowledge_post", post_id=post_id))

def reply_to_comment(comment_id):
    if "user" not in session:
        return redirect("/login")
    if session.get("role") != "admin":
        flash("Only admins can reply to comments")
        return redirect("/dashboard")

    reply = request.form.get("reply", "").strip()
    if not reply:
        flash("Reply cannot be empty")
        return redirect("/knowledge")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT post_id FROM knowledge_comments WHERE comment_id=?", (comment_id,))
    comment_row = cur.fetchone()
    if comment_row:
        cur.execute("INSERT INTO knowledge_replies (comment_id, username, reply) VALUES (?, ?, ?)", (comment_id, session.get("user"), reply))
        conn.commit()
    conn.close()
    flash("Reply posted")
    return redirect(url_for("knowledge_post", post_id=comment_row["post_id"] if comment_row else 1))

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/knowledge', endpoint='knowledge_feed', view_func=knowledge_feed)
    application.add_url_rule('/knowledge/<int:post_id>', endpoint='knowledge_post', view_func=knowledge_post)
    application.add_url_rule('/knowledge/like/<int:post_id>', endpoint='like_knowledge_post', view_func=like_knowledge_post, methods=['POST'])
    application.add_url_rule('/knowledge/comment/<int:post_id>', endpoint='comment_knowledge_post', view_func=comment_knowledge_post, methods=['POST'])
    application.add_url_rule('/knowledge/reply/<int:comment_id>', endpoint='reply_to_comment', view_func=reply_to_comment, methods=['POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['knowledge_feed', 'knowledge_post', 'like_knowledge_post', 'comment_knowledge_post', 'reply_to_comment']

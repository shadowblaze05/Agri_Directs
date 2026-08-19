from flask import flash, redirect, render_template, request, session
from .. import legacy as core
from ..models.database import get_db

# Route implementations use the shared compatibility context.
globals().update({key: value for key, value in core.__dict__.items() if not key.startswith("__")})

def profile():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (session["user"],))
    user = cur.fetchone()

    if request.method == "POST":
        location = request.form.get("location", "").strip()
        cur.execute("UPDATE users SET location=? WHERE username=?", (location, session["user"]))
        conn.commit()
        flash("Profile updated successfully")
        return redirect("/profile")

    # Always show inventory items that belong to the logged-in user
    inventory = []
    cur.execute(
        "SELECT crop_name, SUM(quantity) as total_quantity, MAX(date_received) as last_received "
        "FROM inventory WHERE farmer=? GROUP BY crop_name ORDER BY last_received DESC",
        (session["user"],)
    )
    inventory = cur.fetchall()

    conn.close()
    return render_template("profile.html", user=user, inventory=inventory)

def register(application):
    """Register this domain's routes on the existing Flask app."""
    application.add_url_rule('/profile', endpoint='profile', view_func=profile, methods=['GET', 'POST'])
    for _name in __all__:
        setattr(core, _name, globals()[_name])


__all__ = ['profile']

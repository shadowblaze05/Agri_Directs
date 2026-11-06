import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.database import get_db, init_db
from app.services.auth_service import generate_jwt_token
from app.services.audit_service import should_audit_request


def make_security_app(database_path):
    application = app_module.create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "APP_BASE_URL": "http://localhost",
        "CSRF_ENFORCE_IN_TESTS": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
    })
    with application.app_context():
        init_db()
        db.metadata.create_all(bind=db.engine, tables=[AuditEvent.__table__])
        connection = get_db()
        cursor = connection.cursor()
        for username, role in (
            ("owner", "user"),
            ("buyer", "buyer"),
            ("former-admin", "admin"),
        ):
            cursor.execute(
                "INSERT INTO users (username, role, is_active) VALUES (?, ?, ?)",
                (username, role, True),
            )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS cart "
            "(id INTEGER PRIMARY KEY, user_id INTEGER, quantity INTEGER)"
        )
        crop = cursor.execute("SELECT id FROM crops LIMIT 1").fetchone()
        cursor.execute(
            """INSERT INTO inventory (crop_id, quantity, farmer, date_received, photo_path)
               VALUES (?, ?, ?, ?, ?)""",
            (crop["id"], 3, "owner", "2026-01-01", "private-photo.png"),
        )
        connection.commit()
        connection.close()
    return application


def set_session(client, username, role):
    with client.session_transaction() as user_session:
        user_session["user"] = username
        user_session["role"] = role


def inventory_id(application):
    with application.app_context():
        connection = get_db()
        row = connection.cursor().execute(
            "SELECT id FROM inventory WHERE photo_path=?",
            ("private-photo.png",),
        ).fetchone()
        connection.close()
    return row["id"]


def test_inventory_delete_is_post_only_csrf_checked_and_audited(tmp_path):
    application = make_security_app(tmp_path / "inventory-security.sqlite")
    item_id = inventory_id(application)

    with application.test_client() as client:
        set_session(client, "owner", "user")

        assert client.get(f"/inventory/delete/{item_id}").status_code == 405
        assert client.post(f"/inventory/delete/{item_id}").status_code == 403
        response = client.post(
            f"/inventory/delete/{item_id}",
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 302

    with application.app_context():
        connection = get_db()
        assert connection.cursor().execute(
            "SELECT id FROM inventory WHERE id=?",
            (item_id,),
        ).fetchone() is None
        connection.close()
        event = (
            db.session.query(AuditEvent)
            .filter_by(endpoint="delete_inventory", status_code=302)
            .one()
        )
        assert event.method == "POST"
        assert event.category == "Inventory"
        assert event.action == "Deleted inventory"

    assert should_audit_request(
        "delete_inventory",
        "GET",
        f"/inventory/delete/{item_id}",
    )


def test_cached_admin_role_cannot_access_another_users_inventory(tmp_path):
    application = make_security_app(tmp_path / "stale-admin.sqlite")
    item_id = inventory_id(application)

    with application.app_context():
        connection = get_db()
        connection.cursor().execute(
            "UPDATE users SET role=? WHERE username=?",
            ("user", "former-admin"),
        )
        connection.commit()
        connection.close()

    with application.test_client() as client:
        set_session(client, "former-admin", "admin")
        response = client.get(f"/inventory/edit/{item_id}")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/dashboard")

        set_session(client, "former-admin", "admin")
        response = client.post(
            f"/inventory/delete/{item_id}",
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/dashboard")

        set_session(client, "former-admin", "admin")
        response = client.get("/harvest-evidence/private-photo.png")
        assert response.status_code == 404

        set_session(client, "former-admin", "admin")
        response = client.post(
            "/knowledge/reply/1",
            data={"reply": "Unauthorized reply"},
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/dashboard")

        with client.session_transaction() as user_session:
            assert user_session["role"] == "user"

    with application.app_context():
        connection = get_db()
        assert connection.cursor().execute(
            "SELECT id FROM inventory WHERE id=?",
            (item_id,),
        ).fetchone() is not None
        connection.close()


def test_inactive_session_is_rejected_by_inventory_routes(tmp_path):
    application = make_security_app(tmp_path / "inactive-user.sqlite")
    item_id = inventory_id(application)
    with application.app_context():
        connection = get_db()
        connection.cursor().execute(
            "UPDATE users SET is_active=? WHERE username=?",
            (False, "former-admin"),
        )
        connection.commit()
        connection.close()

    with application.test_client() as client:
        set_session(client, "former-admin", "admin")
        response = client.get(f"/inventory/edit/{item_id}")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        with client.session_transaction() as user_session:
            assert "user" not in user_session


def test_buyer_role_is_saved_and_cannot_manage_harvest_or_listings(tmp_path):
    application = make_security_app(tmp_path / "buyer-role.sqlite")

    with application.test_client() as client:
        set_session(client, "owner", "user")
        response = client.post(
            "/profile/update",
            data={
                "first_name": "Farm",
                "last_name": "Buyer",
                "email": "owner@example.com",
                "role": "buyer",
            },
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 302
        with client.session_transaction() as user_session:
            assert user_session["role"] == "buyer"

        with application.app_context():
            connection = get_db()
            role = connection.cursor().execute(
                "SELECT role FROM users WHERE username=?",
                ("owner",),
            ).fetchone()["role"]
            connection.close()
        assert role == "buyer"
        profile_settings = client.get("/profile/update")
        assert profile_settings.status_code == 200
        assert b'<option value="buyer" selected>Buyer</option>' in profile_settings.data
        profile_response = client.get("/profile")
        assert profile_response.status_code == 200
        assert b"Buyer" in profile_response.data

        item_id = inventory_id(application)
        assert client.get("/inventory").headers["Location"].endswith("/marketplace")
        assert client.get("/upload").headers["Location"].endswith("/marketplace")
        assert client.get("/marketplace/my-purchases").status_code == 200
        marketplace_response = client.get("/marketplace")
        assert marketplace_response.status_code == 200
        assert b'href="/marketplace/add"' not in marketplace_response.data
        assert b'href="/marketplace/my-listings"' not in marketplace_response.data
        assert b'href="/upload"' not in marketplace_response.data
        response = client.post(
            f"/inventory/delete/{item_id}",
            headers={"Origin": "http://localhost"},
        )
        assert response.headers["Location"].endswith("/marketplace")

        response = client.post(
            "/marketplace/add",
            data={},
            headers={"Origin": "http://localhost"},
        )
        assert response.headers["Location"].endswith("/marketplace")
        assert client.get("/marketplace/my-preorder-requests").headers[
            "Location"
        ].endswith("/marketplace")
        response = client.post(
            "/marketplace/preorder/1/accept",
            json={},
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 403
        token = generate_jwt_token("owner")
        response = client.post(
            "/api/harvest",
            headers={"Authorization": f"Bearer {token}"},
            json={"crop_name": "Rice", "quantity": 1, "location": "Farm"},
        )
        assert response.status_code == 403
        assert "Only Sellers" in response.get_json()["error"]

        with application.app_context():
            connection = get_db()
            connection.cursor().execute(
                "UPDATE users SET role=? WHERE username=?",
                ("seller", "owner"),
            )
            connection.commit()
            connection.close()
        set_session(client, "owner", "seller")
        response = client.post(
            "/marketplace/add",
            data={},
            headers={"Origin": "http://localhost"},
        )
        assert response.headers["Location"].endswith("/marketplace/add")
        with application.app_context():
            connection = get_db()
            connection.cursor().execute(
                "UPDATE users SET role=NULL WHERE username=?",
                ("owner",),
            )
            connection.commit()
            connection.close()
        response = client.post(
            "/api/harvest",
            headers={"Authorization": f"Bearer {token}"},
            json={"crop_name": "Rice", "quantity": 1, "location": "Farm"},
        )
        assert response.status_code == 403
        assert "Complete your profile" in response.get_json()["error"]

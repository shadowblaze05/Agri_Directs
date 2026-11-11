import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.database import get_db, init_db
from werkzeug.security import generate_password_hash


def test_admin_users_count_status_and_deactivation(tmp_path, monkeypatch):
    application = app_module.create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'admin-users.db').as_posix()}",
        "INITIAL_ADMIN_USERNAME": "admin",
        "INITIAL_ADMIN_PASSWORD": "Test!GardenBloom9",
    })
    with application.app_context():
        init_db()
        db.metadata.create_all(bind=db.engine, tables=[AuditEvent.__table__])

        connection = get_db()
        connection.cursor().execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("farmer-one", generate_password_hash("password1"), "user"),
        )
        connection.commit()
        connection.close()

    with application.test_client() as client:
        client.post("/login", data={"username": "admin", "password": "Test!GardenBloom9"})
        response = client.get("/admin/users")
        assert response.status_code == 200
        assert b"2 users" in response.data
        assert b"2 active" in response.data
        assert b"0 inactive" in response.data

        with application.app_context():
            connection = get_db()
            admin_id = connection.cursor().execute(
                "SELECT id FROM users WHERE username=?",
                ("admin",),
            ).fetchone()["id"]
            connection.close()
        response = client.post(
            f"/admin/users/edit/{admin_id}",
            data={"role": "seller", "is_active": "1"},
            follow_redirects=True,
        )
        assert b"cannot remove your own administrator access" in response.data
        with application.app_context():
            connection = get_db()
            admin_role = connection.cursor().execute(
                "SELECT role FROM users WHERE username=?",
                ("admin",),
            ).fetchone()["role"]
            connection.close()
        assert admin_role == "admin"

        response = client.post(
            "/admin/users/create",
            data={
                "username": "weak-account",
                "email": "weak-account@example.com",
                "password": "Farmer1",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"at least 8 characters" in response.data
        response = client.post(
            "/admin/users/create",
            data={
                "username": "secure-account",
                "email": "secure-account@example.com",
                "password": "FarmerName7",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        with application.app_context():
            connection = get_db()
            assert connection.cursor().execute(
                "SELECT id FROM users WHERE username=?",
                ("weak-account",),
            ).fetchone() is None
            secure_account = connection.cursor().execute(
                "SELECT id, password FROM users WHERE username=?",
                ("secure-account",),
            ).fetchone()
            assert secure_account is not None
            assert connection.cursor().execute(
                "SELECT id FROM users WHERE id=?",
                (secure_account["id"],),
            ).fetchone() is not None
            original_password_hash = secure_account["password"]
            user = connection.cursor().execute(
                "SELECT id FROM users WHERE username=?",
                ("farmer-one",),
            ).fetchone()
            connection.close()

        response = client.post(
            f"/admin/users/edit/{secure_account['id']}",
            data={
                "role": "user",
                "is_active": "1",
                "email": "secure-account@example.com",
                "password": "Farmer1",
            },
            follow_redirects=True,
        )
        assert b"at least 8 characters" in response.data
        with application.app_context():
            connection = get_db()
            updated_password_hash = connection.cursor().execute(
                "SELECT password FROM users WHERE id=?",
                (secure_account["id"],),
            ).fetchone()["password"]
            connection.close()
        assert updated_password_hash == original_password_hash
        response = client.post(
            f"/admin/users/edit/{secure_account['id']}",
            data={
                "role": "user",
                "is_active": "1",
                "email": "secure-account@example.com",
                "password": "FarmerName8",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        with application.app_context():
            connection = get_db()
            auth_version = connection.cursor().execute(
                "SELECT auth_version FROM users WHERE id=?",
                (secure_account["id"],),
            ).fetchone()["auth_version"]
            connection.close()
        assert auth_version == 1

        response = client.post(
            f"/admin/users/edit/{user['id']}",
            data={
                "role": "user",
                "is_active": "0",
                "first_name": "Farmer",
                "last_name": "One",
                "email": "farmer-one@example.com",
            },
        )
        assert response.status_code == 302

        response = client.get("/admin/users")
        assert b"2 active" in response.data
        assert b"1 inactive" in response.data
        assert b">Inactive</span>" in response.data

    with application.test_client() as inactive_client:
        response = inactive_client.post(
            "/login",
            data={"username": "farmer-one", "password": "password1"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"This account is inactive" in response.data
        with inactive_client.session_transaction() as user_session:
            assert "user" not in user_session


def test_only_superadmin_can_create_or_manage_admin_accounts(tmp_path):
    application = app_module.create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'admin-hierarchy.db').as_posix()}",
        "INITIAL_ADMIN_USERNAME": "admin",
        "INITIAL_ADMIN_PASSWORD": "Test!GardenBloom9",
        "SUPERADMIN_USERNAME": "admin",
    })
    with application.app_context():
        init_db()
        db.metadata.create_all(
            bind=db.engine,
            tables=[AuditEvent.__table__],
        )
        connection = get_db()
        connection.cursor().execute(
            "INSERT INTO users(username, password, role, is_active) VALUES (?, ?, ?, ?)",
            ("day-admin", generate_password_hash("Test!GardenBloom8"), "admin", 1),
        )
        connection.cursor().execute(
            "INSERT INTO users(username, password, role, is_active) VALUES (?, ?, ?, ?)",
            ("other-admin", generate_password_hash("Test!GardenBloom7"), "admin", 1),
        )
        connection.commit()
        other_admin_id = connection.cursor().execute(
            "SELECT id FROM users WHERE username=?", ("other-admin",)
        ).fetchone()["id"]
        connection.close()

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "day-admin"
            user_session["role"] = "admin"

        dashboard = client.get("/admin")
        assert dashboard.status_code == 200
        assert b"Audit log" not in dashboard.data
        assert b"Slow queries" not in dashboard.data

        response = client.get("/admin/users")
        assert response.status_code == 200
        assert b"Only the super admin can manage admin accounts" in response.data

        response = client.post(
            "/admin/users/create",
            data={
                "username": "unauthorized-admin",
                "password": "StrongGarden9",
                "role": "admin",
            },
            follow_redirects=True,
        )
        assert b"Only the super admin can create administrator accounts" in response.data

        for endpoint in ("/admin/audit-logs", "/admin/slow-queries"):
            assert client.get(endpoint).status_code == 302

        response = client.post(
            f"/admin/users/edit/{other_admin_id}",
            data={"role": "seller", "is_active": "0"},
            follow_redirects=True,
        )
        assert b"Only the super admin can manage administrator accounts" in response.data

        response = client.post(
            f"/admin/users/delete/{other_admin_id}",
            follow_redirects=True,
        )
        assert b"Only the super admin can manage administrator accounts" in response.data

    with application.app_context():
        connection = get_db()
        admin = connection.cursor().execute(
            "SELECT role, is_active FROM users WHERE id=?", (other_admin_id,)
        ).fetchone()
        assert admin["role"] == "admin"
        assert admin["is_active"]
        assert connection.cursor().execute(
            "SELECT id FROM users WHERE username=?", ("unauthorized-admin",)
        ).fetchone() is None
        connection.close()

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        response = client.get("/admin/audit-logs")
        assert response.status_code == 200
        response = client.get("/admin/slow-queries")
        assert response.status_code == 200
        response = client.post(
            "/admin/users/create",
            data={
                "username": "new-admin",
                "password": "StrongGarden9",
                "role": "admin",
            },
        )
        assert response.status_code == 302
        response = client.post(
            f"/admin/users/edit/{other_admin_id}",
            data={"role": "seller", "is_active": "0"},
        )
        assert response.status_code == 302

    with application.app_context():
        connection = get_db()
        admin = connection.cursor().execute(
            "SELECT role, is_active FROM users WHERE id=?", (other_admin_id,)
        ).fetchone()
        assert admin["role"] == "seller"
        assert not admin["is_active"]
        assert connection.cursor().execute(
            "SELECT role FROM users WHERE username=?", ("new-admin",)
        ).fetchone()["role"] == "admin"
        connection.close()

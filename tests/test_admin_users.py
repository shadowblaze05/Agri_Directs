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

        response = client.post(
            "/admin/users/create",
            data={
                "username": "weak-account",
                "email": "weak-account@example.com",
                "password": "qwerty",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"at least 12 characters" in response.data
        response = client.post(
            "/admin/users/create",
            data={
                "username": "secure-account",
                "email": "secure-account@example.com",
                "password": "River!Harvest7Moon",
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
                "password": "qwerty",
            },
            follow_redirects=True,
        )
        assert b"at least 12 characters" in response.data
        with application.app_context():
            connection = get_db()
            updated_password_hash = connection.cursor().execute(
                "SELECT password FROM users WHERE id=?",
                (secure_account["id"],),
            ).fetchone()["password"]
            connection.close()
        assert updated_password_hash == original_password_hash

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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from werkzeug.security import generate_password_hash


def test_admin_users_count_status_and_deactivation(tmp_path, monkeypatch):
    db_path = tmp_path / "admin-users.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))
    app_module.init_db()
    app_module.app.config.update(TESTING=True)

    connection = app_module.get_db()
    connection.cursor().execute(
        "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
        ("farmer-one", generate_password_hash("password1"), "user"),
    )
    connection.commit()
    connection.close()

    with app_module.app.test_client() as client:
        client.post("/login", data={"username": "admin", "password": "admin"})
        response = client.get("/admin/users")
        assert response.status_code == 200
        assert b"2 users" in response.data
        assert b"2 active" in response.data
        assert b"0 inactive" in response.data

        connection = app_module.get_db()
        user = connection.cursor().execute(
            "SELECT id FROM users WHERE username=?",
            ("farmer-one",),
        ).fetchone()
        connection.close()
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
        assert b"1 active" in response.data
        assert b"1 inactive" in response.data
        assert b">Inactive</span>" in response.data

    with app_module.app.test_client() as inactive_client:
        response = inactive_client.post(
            "/login",
            data={"username": "farmer-one", "password": "password1"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"This account is inactive" in response.data
        with inactive_client.session_transaction() as user_session:
            assert "user" not in user_session

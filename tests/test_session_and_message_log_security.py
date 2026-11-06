import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.models.database import get_db, init_db
from app.routes import home as home_routes


def make_session_security_app(database_path):
    application = app_module.create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
    })
    with application.app_context():
        init_db()
        connection = get_db()
        connection.cursor().execute(
            "INSERT INTO users (username, role, is_active) VALUES (?, ?, ?)",
            ("session-user", "user", True),
        )
        connection.commit()
        connection.close()

    @application.get("/security/session-probe")
    def session_probe():
        username = app_module.session.get("user")
        if not username:
            return {"error": "Unauthorized"}, 401
        return {"role": app_module.session.get("role")}, 200

    return application


def test_inactive_account_session_is_cleared_on_next_request(tmp_path):
    application = make_session_security_app(tmp_path / "session-security.sqlite")

    with application.app_context():
        connection = get_db()
        connection.cursor().execute(
            "UPDATE users SET is_active=? WHERE username=?",
            (False, "session-user"),
        )
        connection.commit()
        connection.close()

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "session-user"
            user_session["role"] = "admin"

        response = client.get("/security/session-probe")

        assert response.status_code == 401
        with client.session_transaction() as user_session:
            assert "user" not in user_session
            assert "role" not in user_session


def test_session_role_is_refreshed_from_active_account(tmp_path):
    application = make_session_security_app(tmp_path / "session-role.sqlite")

    with application.app_context():
        connection = get_db()
        connection.cursor().execute(
            "UPDATE users SET role=? WHERE username=?",
            ("admin", "session-user"),
        )
        connection.commit()
        connection.close()

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "session-user"
            user_session["role"] = "user"

        response = client.get("/security/session-probe")
        assert response.status_code == 200
        assert response.get_json()["role"] == "admin"


def test_logout_prevents_browser_cached_pages_from_reusing_authenticated_session(tmp_path):
    application = make_session_security_app(tmp_path / "logout-cache.sqlite")

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "session-user"
            user_session["role"] = "user"

        authenticated_response = client.get("/security/session-probe")
        assert authenticated_response.status_code == 200
        assert "no-store" in authenticated_response.headers["Cache-Control"]
        assert authenticated_response.headers["Pragma"] == "no-cache"

        logout_response = client.get("/logout")
        assert logout_response.status_code == 302
        assert "no-store" in logout_response.headers["Cache-Control"]

        with client.session_transaction() as user_session:
            assert "user" not in user_session

        restored_page_response = client.get("/security/session-probe")
        assert restored_page_response.status_code == 401


def test_message_body_is_not_written_to_application_logs(monkeypatch, caplog):
    class FakeCursor:
        def execute(self, *_args):
            return self

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(home_routes, "get_db", FakeConnection)
    monkeypatch.setattr(
        app_module,
        "get_active_user_role",
        lambda _username: "user",
    )
    monkeypatch.setattr(app_module, "record_request_event", lambda *_args: None)
    app_module.app.config.update(TESTING=True)
    caplog.set_level("INFO")
    private_message = "private-message-body-must-not-be-logged"

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "sender"
            user_session["role"] = "user"

        response = client.post(
            "/api/messages",
            json={"recipient": "recipient", "message": private_message},
        )

    assert response.status_code == 200
    assert "Message sent from sender to recipient" in caplog.text
    assert private_message not in caplog.text

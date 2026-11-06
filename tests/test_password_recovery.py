import re
import smtplib
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from werkzeug.security import check_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.routes import auth as auth_routes


def make_password_recovery_app(database_uri):
    application = app_module.create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "password-recovery-test-secret",
            "SQLALCHEMY_DATABASE_URI": database_uri,
            "MAIL_SUPPRESS_SEND": False,
            "MAIL_DEFAULT_SENDER": "noreply@example.test",
            "AGRI_DIRECT_OFFICIAL_EMAIL": "official@example.test",
        }
    )
    with application.app_context():
        db.session.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, username TEXT NOT NULL, email TEXT NOT NULL, "
                "password TEXT NOT NULL, role TEXT)"
            )
        )
        db.session.execute(
            text(
                "INSERT INTO users (id, username, email, password, role) "
                "VALUES (1, 'farmer', 'farmer@example.test', 'old-hash', 'user')"
            )
        )
        db.session.execute(text("CREATE TABLE crops (id INTEGER PRIMARY KEY, crops_name TEXT)"))
        db.session.execute(
            text("CREATE TABLE inventory (crop_id INTEGER, crop_name TEXT)")
        )
        db.session.commit()
        db.metadata.create_all(bind=db.engine, tables=[AuditEvent.__table__])
        db.session.commit()
    return application


def test_password_recovery_uses_emailed_code_and_changes_password_in_app(tmp_path, monkeypatch):
    application = make_password_recovery_app(
        f"sqlite:///{(tmp_path / 'password-recovery.sqlite').as_posix()}"
    )

    with application.test_client() as client, application.app_context():
        outbox = []
        monkeypatch.setattr(auth_routes.mail, "send", outbox.append)
        monkeypatch.setattr(auth_routes.secrets, "randbelow", lambda _upper_bound: 12345)
        response = client.post(
            "/forgot-password",
            data={"email": "farmer@example.test"},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/verify-reset-code")
        assert len(outbox) == 1
        email_body = outbox[0].body
        assert "reset-password/" not in email_body
        code_match = re.search(r"verification code is: (\d{6})", email_body)
        assert code_match
        code = code_match.group(1)
        assert code == "012345"

        response = client.post("/verify-reset-code", data={"code": "000000"})
        assert response.status_code == 200
        with application.app_context():
            attempts = db.session.execute(
                text("SELECT attempt_count FROM password_reset_tokens WHERE user_id = 1")
            ).scalar_one()
            assert attempts == 1
        with client.session_transaction() as user_session:
            assert "password_reset_user_id" not in user_session
            assert user_session["password_reset_email"] == "farmer@example.test"
        with application.app_context():
            reset_row = db.session.execute(
                text(
                    "SELECT token, attempt_count, used_at, expires_at FROM password_reset_tokens "
                    "WHERE user_id = 1"
                )
            ).one()
            assert reset_row.token == auth_routes._reset_code_digest(code)
            assert reset_row.attempt_count == 1
            assert reset_row.used_at is None
            expires_at = datetime.strptime(reset_row.expires_at, "%Y-%m-%d %H:%M:%S")
            assert expires_at.replace(tzinfo=timezone.utc) >= datetime.now(timezone.utc)

        response = client.post("/verify-reset-code", data={"code": code})
        assert response.status_code == 302, response.data.decode()
        assert response.headers["Location"].endswith("/reset-password")

        response = client.post(
            "/reset-password",
            data={"password": "Farmer1", "confirm_password": "Farmer1"},
        )
        assert response.status_code == 200
        assert b"at least 8 characters" in response.data
        with client.session_transaction() as user_session:
            assert user_session.get("password_reset_user_id") == 1

        response = client.post(
            "/reset-password",
            data={
                "password": "FarmerName7",
                "confirm_password": "FarmerName7",
            },
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        password_confirmation = next(
            message for message in outbox
            if message.subject == "Your Agri-Direct password was changed"
        )
        assert password_confirmation.recipients == ["farmer@example.test"]
        assert "successfully changed" in password_confirmation.body
        assert all(
            message.subject != "Agri-Direct account password changed"
            for message in outbox
        )
        assert len(outbox) == 2

        with application.app_context():
            password_hash = db.session.execute(
                text("SELECT password FROM users WHERE id = 1")
            ).scalar_one()
            assert check_password_hash(password_hash, "FarmerName7")

        response = client.get("/login")
        assert response.status_code == 200
        assert b"alert-success" in response.data
        assert b"Password reset successful" in response.data

        response = client.get("/reset-password")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/forgot-password")


def test_password_reset_response_is_generic_when_delivery_fails(tmp_path, monkeypatch):
    application = make_password_recovery_app(
        f"sqlite:///{(tmp_path / 'password-recovery-delivery.sqlite').as_posix()}"
    )

    def fail_delivery(_message):
        raise smtplib.SMTPException("SMTP failure details")

    monkeypatch.setattr(auth_routes.mail, "send", fail_delivery)
    with application.test_client() as client:
        existing = client.post(
            "/forgot-password",
            data={"email": "farmer@example.test"},
            follow_redirects=False,
        )
        unknown = client.post(
            "/forgot-password",
            data={"email": "missing@example.test"},
            follow_redirects=False,
        )

    assert existing.status_code == unknown.status_code == 302
    assert existing.headers["Location"] == unknown.headers["Location"]

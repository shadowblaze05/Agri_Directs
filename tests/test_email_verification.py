import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

import app as app_module
from app.extensions import db
from app.models.database import init_db
from app.routes import auth as auth_routes
from app.services.email_verification_service import purge_expired_pending_accounts


def test_registration_requires_email_code_before_login(tmp_path, monkeypatch):
    application = app_module.create_app({
        "APP_ENV": "testing",
        "TESTING": True,
        "SECRET_KEY": "email-verification-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'verification.sqlite').as_posix()}",
        "MAIL_SUPPRESS_SEND": False,
        "MAIL_DEFAULT_SENDER": "noreply@example.test",
        "INITIAL_ADMIN_USERNAME": "verification-admin",
        "INITIAL_ADMIN_PASSWORD": "Verify!GardenBloom9",
    })
    with application.app_context():
        init_db()

    outbox = []
    monkeypatch.setattr(auth_routes.mail, "send", outbox.append)
    monkeypatch.setattr(auth_routes.secrets, "randbelow", lambda _limit: 12345)

    with application.test_client() as client:
        weak_response = client.post("/register", data={
            "username": "weakfarmer",
            "first_name": "Weak",
            "last_name": "Farmer",
            "email": "weakfarmer@example.test",
            "password": "121212",
            "confirm_password": "121212",
        })
        assert weak_response.status_code == 200
        assert b"at least 12 characters" in weak_response.data
        repeated_numbers_response = client.post("/register", data={
            "username": "repeatednumbers",
            "first_name": "Repeated",
            "last_name": "Numbers",
            "email": "repeatednumbers@example.test",
            "password": "123123123123",
            "confirm_password": "123123123123",
        })
        assert repeated_numbers_response.status_code == 200
        with application.app_context():
            assert db.session.execute(text(
                "SELECT COUNT(*) FROM users "
                "WHERE username IN ('weakfarmer', 'repeatednumbers')"
            )).scalar_one() == 0

        response = client.post("/register", data={
            "username": "verifyfarmer",
            "first_name": "Verify",
            "last_name": "Farmer",
            "email": "verifyfarmer@example.test",
            "password": "River!Harvest7Moon",
            "confirm_password": "River!Harvest7Moon",
        })
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/verify-email")
        assert client.get("/verify-email").status_code == 200
        with client.session_transaction() as user_session:
            assert user_session.get("email_verification_email") == "verifyfarmer@example.test"
            assert "user" not in user_session

        assert len(outbox) == 1
        code = re.search(r"verification code is: (\d{6})", outbox[0].body).group(1)
        assert code == "012345"

        with application.app_context():
            record = db.session.execute(text(
                "SELECT id, is_verified, is_active FROM users WHERE username='verifyfarmer'"
            )).one()
            token = db.session.execute(text(
                "SELECT token, attempt_count, used_at FROM password_reset_tokens "
                "WHERE user_id=:user_id AND purpose='email_verification'"
            ), {"user_id": record.id}).one()
            assert record.is_verified in (False, 0)
            assert record.is_active in (False, 0)
            assert token.token == auth_routes._email_verification_digest(code, record.id)
            assert token.attempt_count == 0
            assert token.used_at is None

        with application.test_client() as admin_client:
            admin_client.post("/login", data={
                "username": "verification-admin",
                "password": "Verify!GardenBloom9",
            })
            admin_response = admin_client.get("/admin/users")
            assert admin_response.status_code == 200
            assert b"1 pending verification" in admin_response.data
            assert b"Pending verification" in admin_response.data
            assert b"Code expires" in admin_response.data

        response = client.post("/verify-email", data={"code": "000000"})
        assert response.status_code == 200
        with application.app_context():
            attempts = db.session.execute(text(
                "SELECT attempt_count FROM password_reset_tokens "
                "WHERE purpose='email_verification'"
            )).scalar_one()
            assert attempts == 1

        response = client.post("/verify-email", data={"code": code})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        with application.app_context():
            assert db.session.execute(text(
                "SELECT is_verified FROM users WHERE username='verifyfarmer'"
            )).scalar_one() in (True, 1)
            assert db.session.execute(text(
                "SELECT is_active FROM users WHERE username='verifyfarmer'"
            )).scalar_one() in (True, 1)
            assert db.session.execute(text(
                "SELECT used_at FROM password_reset_tokens WHERE purpose='email_verification'"
            )).scalar_one() is not None

        response = client.post("/login", data={
            "username": "verifyfarmer",
            "password": "River!Harvest7Moon",
        })
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/home")


def test_registering_again_resends_code_for_existing_pending_account(tmp_path, monkeypatch):
    application = app_module.create_app({
        "APP_ENV": "testing",
        "TESTING": True,
        "SECRET_KEY": "email-verification-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'pending-retry.sqlite').as_posix()}",
        "MAIL_SUPPRESS_SEND": False,
        "MAIL_DEFAULT_SENDER": "noreply@example.test",
    })
    with application.app_context():
        init_db()

    outbox = []
    codes = iter((12345, 67890))
    monkeypatch.setattr(auth_routes.mail, "send", outbox.append)
    monkeypatch.setattr(auth_routes.secrets, "randbelow", lambda _limit: next(codes))
    registration = {
        "username": "pendingretry",
        "first_name": "Pending",
        "last_name": "Retry",
        "email": "pendingretry@example.test",
        "password": "River!Harvest7Moon",
        "confirm_password": "River!Harvest7Moon",
    }

    with application.test_client() as client:
        first = client.post("/register", data=registration)
        second = client.post("/register", data=registration)
        assert first.headers["Location"].endswith("/verify-email")
        assert second.headers["Location"].endswith("/verify-email")
        assert len(outbox) == 2

    with application.app_context():
        user = db.session.execute(text(
            "SELECT id, is_verified, is_active FROM users WHERE username='pendingretry'"
        )).one()
        token = db.session.execute(text(
            "SELECT token FROM password_reset_tokens WHERE user_id=:user_id "
            "AND purpose='email_verification' AND used_at IS NULL"
        ), {"user_id": user.id}).one()
        assert user.is_verified in (False, 0)
        assert user.is_active in (False, 0)
        assert token.token == auth_routes._email_verification_digest("067890", user.id)


def test_expired_unverified_registration_is_retained(tmp_path):
    application = app_module.create_app({
        "APP_ENV": "testing",
        "TESTING": True,
        "SECRET_KEY": "email-verification-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'expired-verification.sqlite').as_posix()}",
    })
    with application.app_context():
        init_db()
        auth_routes._ensure_password_reset_table()
        connection = auth_routes.get_db()
        cur = connection.cursor()
        cur.execute(
            "INSERT INTO users(username, email, password, role, is_verified, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("expiredfarmer", "expired@example.test", "unused", "user", False, False),
        )
        user_id = cur.execute(
            "SELECT id FROM users WHERE username=?", ("expiredfarmer",)
        ).fetchone()["id"]
        now = datetime.now(timezone.utc)
        cur.execute(
            "INSERT INTO password_reset_tokens(user_id, token, expires_at, created_at, "
            "attempt_count, purpose) VALUES (?, ?, ?, ?, 0, 'email_verification')",
            (user_id, "expired-verification-digest",
             (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
             (now - timedelta(minutes=11)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        connection.commit()
        connection.close()

        assert purge_expired_pending_accounts() == 0
        connection = auth_routes.get_db()
        assert connection.cursor().execute(
            "SELECT id FROM users WHERE id=?", (user_id,)
        ).fetchone() is not None
        assert connection.cursor().execute(
            "SELECT id FROM password_reset_tokens WHERE user_id=?", (user_id,)
        ).fetchone() is not None
        connection.close()

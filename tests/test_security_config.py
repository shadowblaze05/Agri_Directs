import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import validate_security_config
import app as app_module
from app import record_request_event
from app.routes import auth as auth_routes


def production_config(**overrides):
    config = {
        "APP_ENV": "production",
        "DEBUG": False,
        "SECRET_KEY": "s" * 48,
        "JWT_SECRET": "j" * 48,
        "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg2://agridirect_app@db/agri_direct",
        "SESSION_COOKIE_SECURE": True,
        "APP_BASE_URL": "https://agridirect.example",
        "RATELIMIT_STORAGE_URI": "redis://redis:6379/0",
    }
    config.update(overrides)
    return config


def test_production_configuration_accepts_secure_values():
    validate_security_config(production_config())


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("SECRET_KEY", "change-this-secret-key"),
        ("JWT_SECRET", "short"),
        ("DEBUG", True),
        ("SESSION_COOKIE_SECURE", False),
        ("APP_BASE_URL", "http://agridirect.example"),
        ("RATELIMIT_STORAGE_URI", "memory://"),
        (
            "SQLALCHEMY_DATABASE_URI",
            "postgresql+psycopg2://postgres@db/agri_direct",
        ),
    ],
)
def test_production_configuration_rejects_insecure_values(setting, value):
    with pytest.raises(RuntimeError):
        validate_security_config(production_config(**{setting: value}))


def test_browser_mutations_require_same_origin(monkeypatch, tmp_path):
    application = app_module.create_app({
        "TESTING": True,
        "CSRF_ENFORCE_IN_TESTS": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'csrf.sqlite').as_posix()}",
    })
    monkeypatch.setattr("app.record_request_event", lambda *_args: None)
    application.add_url_rule(
        "/csrf-probe",
        endpoint="csrf_probe",
        view_func=lambda: ("ok", 200),
        methods=["POST"],
    )

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"

        assert client.post("/csrf-probe").status_code == 403
        assert client.post("/csrf-probe", headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.post("/csrf-probe", headers={"Origin": "http://localhost"}).status_code == 200


def test_login_rate_limit_returns_429(monkeypatch, tmp_path):
    class FakeCursor:
        def execute(self, *_args):
            return self

        def fetchone(self):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    application = app_module.create_app({
        "TESTING": True,
        "RATELIMIT_STORAGE_URI": "memory://",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'rate-limit.sqlite').as_posix()}",
    })
    monkeypatch.setattr(auth_routes, "get_db", FakeConnection)
    monkeypatch.setattr("app.record_request_event", lambda *_args: None)

    with application.test_client() as client:
        responses = [
            client.post("/login", data={"identifier": "unknown", "password": "wrong"})
            for _ in range(6)
        ]

    assert [response.status_code for response in responses[:5]] == [200] * 5
    assert responses[5].status_code == 429


def test_security_headers_are_set_and_hsts_requires_secure_cookie_config(tmp_path):
    application = app_module.create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'headers.sqlite').as_posix()}",
    })
    application.add_url_rule("/security-probe", view_func=lambda: "ok")

    with application.test_client() as client:
        response = client.get("/security-probe")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "geolocation=(self), camera=(self)"
    assert "Strict-Transport-Security" not in response.headers
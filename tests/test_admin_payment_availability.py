import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import admin as admin_routes


def test_admin_can_disable_and_enable_online_payments(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.executed = []

        def execute(self, query, params=()):
            self.executed.append((query, params))
            return self

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()
            self.committed = 0

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            self.committed += 1

        def close(self):
            pass

    connection = FakeConnection()
    monkeypatch.setattr(admin_routes, "get_db", lambda: connection)
    monkeypatch.setattr(
        app_module,
        "get_active_user_role",
        lambda username: "admin" if username == "admin" else None,
    )
    monkeypatch.setattr(
        admin_routes,
        "get_active_user_role",
        lambda username, _connection_factory=None: (
            "admin" if username == "admin" else None
        ),
    )
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user"] = "admin"

        for enabled in ("0", "1"):
            response = client.post(
                "/admin/online-payments/availability",
                data={"enabled": enabled},
            )
            assert response.status_code == 302
            assert response.headers["Location"].endswith("/admin/online-payments")

    assert [params for _query, params in connection.fake_cursor.executed] == [
        ("0",),
        ("1",),
    ]
    assert all(
        "ON CONFLICT(setting_key) DO UPDATE" in query
        for query, _params in connection.fake_cursor.executed
    )
    assert connection.committed == 2

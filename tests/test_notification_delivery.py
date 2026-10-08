import sqlite3

import app as app_module
from app.services.notification_service import notify_published_announcement
from app.routes import home as home_routes


def test_pinned_announcement_notifies_all_non_admin_users_with_a_link():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE users (username TEXT, role TEXT);
        CREATE TABLE notifications (
            username TEXT, title TEXT, message TEXT, type TEXT,
            created_at TEXT, is_read INTEGER, link TEXT
        );
        INSERT INTO users (username, role) VALUES
            ('farmer-one', 'user'),
            ('buyer-one', 'user'),
            ('site-admin', 'admin');
    """)

    notify_published_announcement(
        connection.cursor(), 17, "Weather advisory"
    )
    notifications = connection.execute(
        "SELECT * FROM notifications ORDER BY username"
    ).fetchall()

    assert [item["username"] for item in notifications] == [
        "buyer-one",
        "farmer-one",
    ]
    assert all(item["type"] == "announcement" for item in notifications)
    assert all(item["link"] == "/knowledge/17" for item in notifications)
    assert all("Weather advisory" in item["message"] for item in notifications)


def test_unread_notification_count_is_scoped_to_signed_in_user(monkeypatch):
    class Cursor:
        def execute(self, query, params=()):
            assert "WHERE username=? AND is_read=0" in query
            assert params == ("farmer-one",)
            return self

        def fetchone(self):
            return {"unread_count": 3}

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(home_routes, "get_db", Connection)
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer-one"
        response = client.get("/notifications/unread-count")

    assert response.status_code == 200
    assert response.json == {"unread_count": 3}

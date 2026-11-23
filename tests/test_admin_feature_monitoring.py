import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import admin as admin_routes


class SharedSQLiteConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return self.connection.cursor()

    def close(self):
        return None


def monitoring_database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE users (
            username TEXT PRIMARY KEY,
            role TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            auth_version INTEGER NOT NULL DEFAULT 0,
            profile_photo_captured_at TEXT,
            profile_photo_scan_verified_at TEXT
        );
        CREATE TABLE profile_photo_challenges (
            challenge_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL,
            current_stage INTEGER NOT NULL DEFAULT 0,
            last_stage_at TEXT,
            failed_attempts INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE marketplace (
            id INTEGER PRIMARY KEY,
            username TEXT,
            buyer_username TEXT,
            commodity_name TEXT,
            amount INTEGER,
            unit TEXT,
            price REAL,
            order_status TEXT,
            preorder_status TEXT,
            status TEXT,
            order_date TEXT,
            payment_method TEXT,
            xendit_reference_id TEXT,
            xendit_session_id TEXT,
            delivery_confirmed INTEGER DEFAULT 0,
            buyer_confirmed INTEGER DEFAULT 0
        );
        CREATE TABLE xendit_payment_events (
            id INTEGER PRIMARY KEY,
            reference_id TEXT NOT NULL,
            order_ids TEXT NOT NULL DEFAULT '',
            event_name TEXT NOT NULL,
            result TEXT NOT NULL,
            session_id TEXT,
            amount TEXT,
            currency TEXT,
            received_at TEXT NOT NULL
        );
        CREATE TABLE app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
        );
        INSERT INTO app_settings(setting_key, setting_value)
        VALUES ('online_payments_enabled', '1');
        CREATE TABLE commodities (id INTEGER PRIMARY KEY);
        CREATE TABLE knowledge_posts (post_id INTEGER PRIMARY KEY);
        CREATE TABLE profile_reports (status TEXT);
        CREATE TABLE listing_photo_location_alerts (status TEXT);
        """
    )
    now = datetime.now(timezone.utc)
    timestamps = {
        "now": now.isoformat(),
        "past": (now - timedelta(minutes=2)).isoformat(),
        "future": (now + timedelta(minutes=3)).isoformat(),
        "expired": (now - timedelta(days=1)).isoformat(),
    }
    connection.executemany(
        """INSERT INTO users (
               username, role, profile_photo_captured_at,
               profile_photo_scan_verified_at
           ) VALUES (?, ?, ?, ?)""",
        [
            ("admin", "admin", None, None),
            ("buyer1", "buyer", timestamps["past"], timestamps["now"]),
            ("seller1", "seller", timestamps["past"], None),
        ],
    )
    connection.executemany(
        """INSERT INTO profile_photo_challenges (
               challenge_hash, username, expires_at, consumed_at, created_at,
               current_stage, last_stage_at, failed_attempts
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("active", "buyer1", timestamps["future"], None, timestamps["past"], 2, timestamps["now"], 1),
            ("expired", "seller1", timestamps["expired"], None, timestamps["expired"], 1, None, 0),
            ("failed", "seller1", timestamps["now"], timestamps["now"], timestamps["past"], 3, timestamps["now"], 5),
            ("consumed", "buyer1", timestamps["now"], timestamps["now"], timestamps["past"], 5, timestamps["now"], 0),
        ],
    )
    connection.executemany(
        """INSERT INTO marketplace (
               id, username, buyer_username, commodity_name, amount, unit, price,
               order_status, status, order_date, payment_method,
               xendit_reference_id, xendit_session_id
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, "seller1", "buyer1", "Tomatoes", 2, "kg", 20, "awaiting_payment", "sold", timestamps["past"], "xendit", "ref-pending", "session-pending"),
            (2, "seller1", "buyer2", "Rice", 5, "kg", 10, "to_pay", "sold", timestamps["past"], "xendit", "ref-paid", "session-paid"),
            (3, "seller1", "buyer3", "Corn", 1, "kg", 30, "to_pay", "sold", timestamps["past"], "cod", None, None),
        ],
    )
    connection.executemany(
        """INSERT INTO xendit_payment_events (
               id, reference_id, order_ids, event_name, result, session_id,
               amount, currency, received_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (1, "ref-pending", "1", "checkout.created", "created", "session-pending", "40.00", "PHP", timestamps["past"]),
            (2, "ref-paid", "2", "payment.capture", "paid", "session-paid", "50.00", "PHP", timestamps["now"]),
            (3, "ref-unknown", "", "payment_session.completed", "unknown", None, None, None, timestamps["now"]),
        ],
    )
    connection.commit()
    return connection


def _session_role_for_test(username):
    from flask import session as flask_session

    if flask_session.get("user") != username:
        return None
    return flask_session.get("role", "user")


def _admin_client(connection, monkeypatch, role="admin"):
    monkeypatch.setattr(
        admin_routes,
        "get_db",
        lambda: SharedSQLiteConnection(connection),
    )
    monkeypatch.setattr(app_module, "get_active_user_role", _session_role_for_test)
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "admin" if role == "admin" else "regular"
        session["role"] = role
    return client


def test_face_scan_monitor_shows_challenge_states_and_verified_profiles(monkeypatch):
    connection = monitoring_database()
    response = _admin_client(connection, monkeypatch).get("/admin/face-scan-monitor")

    assert response.status_code == 200
    assert b"Face scan monitoring" in response.data
    assert b"Verified profiles" in response.data
    assert b"@buyer1" in response.data
    assert b"Attempt limit reached" in response.data
    assert b"Camera frames and face landmarks are not stored" in response.data


def test_face_scan_monitor_filters_challenges_by_username_and_status(monkeypatch):
    connection = monitoring_database()
    response = _admin_client(connection, monkeypatch).get(
        "/admin/face-scan-monitor?q=seller1&status=expired"
    )

    assert response.status_code == 200
    assert b"@seller1" in response.data
    assert b"Expired" in response.data
    assert b"@buyer1" not in response.data


def test_online_payment_monitor_shows_pending_and_confirmed_orders(monkeypatch):
    connection = monitoring_database()
    response = _admin_client(connection, monkeypatch).get("/admin/online-payments")

    assert response.status_code == 200
    assert b"Online payment monitoring" in response.data
    assert b"Waiting for Xendit confirmation" in response.data
    assert b"Payment confirmed" in response.data
    assert b"ref-pending" in response.data
    assert b"ref-paid" in response.data
    assert b"ref-cod" not in response.data
    assert b"Xendit event history" in response.data
    assert b"payment.capture" in response.data
    assert b"Failed / rejected events" in response.data


def test_online_payment_monitor_filters_by_reference_and_status(monkeypatch):
    connection = monitoring_database()
    response = _admin_client(connection, monkeypatch).get(
        "/admin/online-payments?q=ref-paid&status=to_pay"
    )

    assert response.status_code == 200
    assert b"ref-paid" in response.data
    assert b"ref-pending" not in response.data


def test_feature_monitoring_requires_admin_role(monkeypatch):
    connection = monitoring_database()
    client = _admin_client(connection, monkeypatch, role="user")

    assert client.get("/admin/face-scan-monitor").status_code == 302
    assert client.get("/admin/online-payments").status_code == 302


def test_admin_console_links_to_both_monitoring_workspaces(monkeypatch):
    connection = monitoring_database()
    response = _admin_client(connection, monkeypatch).get("/admin")

    assert response.status_code == 200
    assert b"Face scan monitoring" in response.data
    assert b'href="/admin/face-scan-monitor"' in response.data
    assert b"Online payment monitoring" in response.data
    assert b'href="/admin/online-payments"' in response.data

import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import marketplace as marketplace_routes
from app.services import xendit_service


class SharedSQLiteConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return self.connection.cursor()

    def commit(self):
        self.connection.commit()

    def close(self):
        return None


def payment_database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE marketplace (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            commodity_id INTEGER,
            commodity_name TEXT,
            amount INTEGER,
            price REAL,
            unit TEXT,
            listing_date TEXT,
            expiry_date TEXT,
            description TEXT,
            location TEXT,
            main_image TEXT,
            listing_type TEXT,
            available_date TEXT,
            order_status TEXT,
            xendit_reference_id TEXT,
            xendit_session_id TEXT,
            xendit_checkout_url TEXT,
            payment_method TEXT,
            reserved_from_listing_id INTEGER,
            buyer_username TEXT,
            status TEXT,
            order_date TEXT,
            delivery_date TEXT,
            delivery_confirmed INTEGER,
            buyer_confirmed INTEGER,
            buyer_confirm_date TEXT,
            buyer_rating INTEGER,
            buyer_rating_date TEXT,
            delivery_province TEXT,
            delivery_city TEXT,
            delivery_barangay TEXT,
            delivery_street TEXT,
            delivery_landmark TEXT
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
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE cart (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            listing_id INTEGER,
            quantity INTEGER,
            added_date TEXT
        );
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY,
            commodity_id INTEGER,
            quantity INTEGER,
            farmer TEXT,
            date_received TEXT,
            location TEXT,
            source TEXT
        );
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY,
            username TEXT,
            title TEXT,
            message TEXT,
            type TEXT,
            created_at TEXT,
            is_read INTEGER
        );
        """
    )
    return connection


def insert_pending_order(connection, **overrides):
    values = {
        "id": 10,
        "order_status": "awaiting_payment",
        "xendit_reference_id": "agri-test-reference",
        "xendit_session_id": "ps-test-session",
        "xendit_checkout_url": "https://dev.xen.to/test",
        "payment_method": "xendit",
        "reserved_from_listing_id": None,
        "amount": 2,
        "price": 15.0,
        "commodity_id": 3,
        "commodity_name": "Tomatoes",
        "buyer_username": "buyer",
        "username": "seller",
        "location": "Palo",
        "status": "sold",
        "order_date": "2026-11-20 10:00:00",
        "delivery_confirmed": 0,
        "buyer_confirmed": 0,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO marketplace ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    connection.commit()


def test_create_payment_session_uses_server_side_basic_auth(monkeypatch):
    response = Mock(
        status_code=201,
        json=Mock(return_value={
            "payment_session_id": "ps-test",
            "payment_link_url": "https://dev.xen.to/test",
        }),
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(xendit_service.requests, "post", post)

    result = xendit_service.create_payment_session(
        "test-secret",
        {"reference_id": "agri-order"},
    )

    assert result["payment_session_id"] == "ps-test"
    assert post.call_args.kwargs["auth"] == ("test-secret", "")
    assert post.call_args.kwargs["timeout"] == 20
    assert post.call_args.kwargs["json"] == {"reference_id": "agri-order"}


def test_payment_session_errors_include_only_safe_validation_fields(monkeypatch):
    response = Mock(
        status_code=400,
        json=Mock(return_value={
            "error_code": "API_VALIDATION_ERROR",
            "message": "One or more fields are invalid.",
            "errors": [
                {
                    "field": "items[0].currency",
                    "message": "Unsupported currency",
                    "value": "sensitive-value",
                },
            ],
        }),
    )
    monkeypatch.setattr(xendit_service.requests, "post", Mock(return_value=response))

    with pytest.raises(xendit_service.XenditError) as raised:
        xendit_service.create_payment_session(
            "server-secret",
            {"reference_id": "agri-order"},
        )

    message = str(raised.value)
    assert "API_VALIDATION_ERROR" in message
    assert "items[0].currency" in message
    assert "sensitive-value" not in message
    assert "server-secret" not in message


def test_callback_token_verification_is_constant_time_and_rejects_missing_values():
    assert xendit_service.verify_callback_token("callback-token", "callback-token")
    assert not xendit_service.verify_callback_token("wrong-token", "callback-token")
    assert not xendit_service.verify_callback_token(None, "callback-token")


def test_create_payment_session_rejects_malformed_checkout_links(monkeypatch):
    response = Mock(
        status_code=201,
        json=Mock(return_value={
            "payment_session_id": "ps-test",
            "payment_link_url": {"unexpected": "object"},
        }),
    )
    monkeypatch.setattr(xendit_service.requests, "post", Mock(return_value=response))

    with pytest.raises(xendit_service.XenditError, match="valid hosted checkout link"):
        xendit_service.create_payment_session("test-secret", {})


def test_completed_payment_updates_orders_and_inventory_once(monkeypatch):
    connection = payment_database()
    insert_pending_order(connection)
    connection.execute(
        """INSERT INTO inventory(commodity_id, quantity, farmer, date_received, location)
           VALUES (3, 5, 'seller', '2026-11-20', 'Palo')"""
    )
    connection.commit()
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: SharedSQLiteConnection(connection),
    )

    event_data = {
        "payment_session_id": "ps-test-session",
        "amount": 30,
        "currency": "PHP",
    }
    with app_module.app.app_context():
        assert marketplace_routes._process_xendit_payment_event(
            "payment_session.completed",
            "agri-test-reference",
            event_data,
        ) == "paid"
        assert marketplace_routes._process_xendit_payment_event(
            "payment_session.completed",
            "agri-test-reference",
            event_data,
        ) == "already_processed"

    order = connection.execute(
        "SELECT order_status FROM marketplace WHERE id = 10"
    ).fetchone()
    assert order["order_status"] == "to_pay"
    buyer_inventory = connection.execute(
        "SELECT quantity FROM inventory WHERE farmer = 'buyer'"
    ).fetchall()
    assert [row["quantity"] for row in buyer_inventory] == [2]
    seller_inventory = connection.execute(
        "SELECT quantity FROM inventory WHERE farmer = 'seller'"
    ).fetchone()
    assert seller_inventory["quantity"] == 3
    notification_count = connection.execute(
        "SELECT COUNT(*) FROM notifications"
    ).fetchone()[0]
    assert notification_count == 1


@pytest.mark.parametrize(
    ("event_name", "amount_field"),
    [
        ("payment.capture", "request_amount"),
        ("capture.succeeded", "captured_amount"),
    ],
)
def test_capture_webhook_confirms_order(monkeypatch, event_name, amount_field):
    connection = payment_database()
    insert_pending_order(connection)
    connection.commit()
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: SharedSQLiteConnection(connection),
    )
    monkeypatch.setitem(app_module.app.config, "XENDIT_WEBHOOK_TOKEN", "callback-token")
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        response = client.post(
            "/xendit/webhook",
            json={
                "event": event_name,
                "data": {
                    "status": "SUCCEEDED",
                    "currency": "PHP",
                    "reference_id": "agri-test-reference",
                    amount_field: 30,
                },
            },
            headers={"X-Callback-Token": "callback-token"},
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "paid"
    order = connection.execute(
        "SELECT order_status FROM marketplace WHERE id = 10"
    ).fetchone()
    assert order["order_status"] == "to_pay"
    event = connection.execute(
        "SELECT event_name, result, order_ids, session_id FROM xendit_payment_events"
    ).fetchone()
    assert tuple(event) == (event_name, "paid", "10", None)


@pytest.mark.parametrize("event_name", ["payment.capture", "capture.succeeded"])
def test_unsuccessful_capture_does_not_confirm_order(monkeypatch, event_name):
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: pytest.fail("unsuccessful capture must not access the database"),
    )

    with app_module.app.app_context():
        result = marketplace_routes._process_xendit_payment_event(
            event_name,
            "agri-test-reference",
            {"status": "FAILED"},
        )

    assert result == "not_succeeded"


def test_expired_payment_restores_listing_without_creating_inventory(monkeypatch):
    connection = payment_database()
    insert_pending_order(connection)
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: SharedSQLiteConnection(connection),
    )

    with app_module.app.app_context():
        result = marketplace_routes._process_xendit_payment_event(
            "payment_session.expired",
            "agri-test-reference",
            {"payment_session_id": "ps-test-session", "amount": 30, "currency": "PHP"},
        )

    assert result == "expired"
    listing = connection.execute(
        "SELECT status, order_status, buyer_username, xendit_checkout_url "
        "FROM marketplace WHERE id = 10"
    ).fetchone()
    assert tuple(listing) == ("available", "available", None, None)
    assert connection.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0


def test_expired_partial_payment_merges_reserved_quantity_into_source_listing(monkeypatch):
    connection = payment_database()
    connection.execute(
        """INSERT INTO marketplace(
               id, user_id, username, commodity_id, commodity_name, amount, price,
               unit, listing_type, status, order_status
           ) VALUES (3, 5, 'seller', 8, 'Ampalaya', 10, 90, 'kg',
                     'standard', 'available', 'available')"""
    )
    insert_pending_order(
        connection,
        id=10,
        amount=40,
        price=90,
        commodity_id=8,
        commodity_name="Ampalaya",
        xendit_reference_id="agri-test-reference",
        reserved_from_listing_id=3,
    )
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: SharedSQLiteConnection(connection),
    )

    with app_module.app.app_context():
        result = marketplace_routes._process_xendit_payment_event(
            "payment_session.expired",
            "agri-test-reference",
            {"payment_session_id": "ps-test-session", "amount": 3600, "currency": "PHP"},
        )

    assert result == "expired"
    listings = connection.execute(
        "SELECT id, amount, status FROM marketplace ORDER BY id"
    ).fetchall()
    assert [tuple(row) for row in listings] == [(3, 50, "available")]


def test_cod_checkout_places_order_without_calling_xendit(monkeypatch):
    connection = payment_database()
    connection.execute(
        "INSERT INTO users(id, username) VALUES (2, 'buyer')"
    )
    connection.execute(
        """INSERT INTO marketplace(
               id, user_id, username, commodity_id, commodity_name, amount, price,
               unit, listing_date, expiry_date, description, location, main_image,
               listing_type, available_date, order_status, payment_method, status
           ) VALUES (
               3, 1, 'seller', 8, 'Tomatoes', 5, 12.5, 'kg',
               '2026-11-20', NULL, 'Fresh', 'Palo', NULL,
               'standard', NULL, 'available', NULL, 'available'
           )"""
    )
    connection.execute(
        """INSERT INTO inventory(commodity_id, quantity, farmer, date_received, location)
           VALUES (8, 5, 'seller', '2026-11-20', 'Palo')"""
    )
    connection.execute(
        """INSERT INTO cart(id, user_id, listing_id, quantity, added_date)
           VALUES (16, 2, 3, 2, '2026-11-20')"""
    )
    connection.commit()
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: SharedSQLiteConnection(connection),
    )
    monkeypatch.setattr(
        marketplace_routes,
        "create_payment_session",
        lambda *_args, **_kwargs: pytest.fail("COD must not call Xendit"),
    )
    monkeypatch.setattr(
        app_module,
        "get_active_user_role",
        lambda username: "buyer" if username == "buyer" else None,
    )
    monkeypatch.setitem(app_module.app.config, "XENDIT_SECRET_KEY", "")
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session["user"] = "buyer"
        response = client.post(
            "/marketplace/cart/checkout",
            json={
                "delivery_province": "Leyte",
                "delivery_city": "Palo",
                "delivery_barangay": "Pawing",
                "delivery_street": "12 Farm Road",
                "payment_method": "cod",
            },
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    order = connection.execute(
        """SELECT order_status, payment_method, buyer_username
           FROM marketplace WHERE buyer_username = 'buyer'"""
    ).fetchone()
    assert tuple(order) == ("to_pay", "cod", "buyer")
    assert connection.execute(
        "SELECT amount FROM marketplace WHERE id = 3"
    ).fetchone()["amount"] == 3
    assert connection.execute(
        "SELECT quantity FROM inventory WHERE farmer = 'buyer'"
    ).fetchone()["quantity"] == 2
    assert connection.execute(
        "SELECT quantity FROM inventory WHERE farmer = 'seller'"
    ).fetchone()["quantity"] == 3
    assert connection.execute("SELECT COUNT(*) FROM cart").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 1


def test_webhook_rejects_invalid_callback_token_without_database_access(monkeypatch):
    monkeypatch.setitem(app_module.app.config, "XENDIT_WEBHOOK_TOKEN", "expected-token")
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: pytest.fail("invalid webhook must not access the database"),
    )
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        response = client.post(
            "/xendit/webhook",
            json={"event": "payment_session.completed", "data": {}},
            headers={"X-Callback-Token": "wrong-token"},
        )

    assert response.status_code == 401

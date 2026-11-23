import sys
from pathlib import Path

import pytest
from flask import session as flask_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import marketplace as marketplace_routes


@pytest.fixture(autouse=True)
def session_role_lookup(monkeypatch):
    role_lookup = lambda username, _connection_factory=None: (
        flask_session.get("role", "user")
        if flask_session.get("user") == username
        else None
    )
    monkeypatch.setattr(app_module, "get_active_user_role", role_lookup)
    monkeypatch.setattr(marketplace_routes, "get_active_user_role", role_lookup)


def test_seller_transactions_page_shows_buyer_details_and_current_order_state(monkeypatch):
    transaction = {
        "id": 17,
        "commodity_name": "Tomatoes",
        "order_status": "packing",
        "buyer_first_name": "Buyer",
        "buyer_last_name": "Person",
        "buyer_username": "buyer",
        "buyer_profile_username": "buyer",
        "buyer_email": "buyer@example.com",
        "buyer_phone_number": "+639123456789",
        "buyer_location": "Sample City",
        "amount": 3,
        "unit": "kg",
        "price": 25,
        "order_date": "2026-10-09 10:00:00",
        "delivery_confirmed": 0,
        "buyer_confirmed": 0,
        "delivery_province": "Leyte",
        "delivery_city": "Palo",
        "delivery_barangay": "Pawing",
        "delivery_street": "12 Farm Road",
        "delivery_landmark": "Near the public market",
    }

    class FakeCursor:
        def __init__(self):
            self.query = ""

        def execute(self, query, _params=()):
            self.query = query
            return self

        def fetchone(self):
            if "SELECT role, is_active FROM users" in self.query:
                return {"role": "seller", "is_active": True}
            return {"id": 4}

        def fetchall(self):
            assert "LEFT JOIN users buyer" in self.query
            return [transaction]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "seller"

        response = client.get("/marketplace/transactions")

    assert response.status_code == 200
    assert b"Transactions" in response.data
    assert b"Buyer Person" in response.data
    assert b"Contact Buyer" in response.data
    assert b'href="/profile/buyer"' in response.data
    assert b"View Buyer Profile" in response.data
    assert b'href="/messages?recipient=buyer"' in response.data
    assert b"buyer@example.com" in response.data
    assert b"+639123456789" in response.data
    assert b"12 Farm Road" in response.data
    assert b"Near the public market" in response.data
    assert b"Packing" in response.data
    assert b"Mark as Shipped" in response.data
    assert b'id="transaction-search"' in response.data
    assert b'id="transaction-status-filter"' in response.data
    assert b'id="transaction-date-from"' in response.data
    assert b'id="transaction-date-to"' in response.data


def test_buyer_purchases_page_renders_orders_in_their_current_stage(monkeypatch):
    purchase = {
        "id": 22,
        "commodity_name": "Sweet Corn",
        "seller_name": "farmer",
        "order_date": "2026-10-09 11:30:00",
        "delivery_date": None,
        "amount": 2,
        "unit": "kg",
        "price": 30,
        "order_status": "to_pay",
        "buyer_confirmed": 0,
        "delivery_confirmed": 0,
        "buyer_rating": None,
    }

    class FakeCursor:
        def execute(self, _query, _params=()):
            return self

        def fetchall(self):
            return [purchase]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/my-purchases")

    assert response.status_code == 200
    assert b"My Purchases" in response.data
    assert b"Sweet Corn" in response.data
    assert b"Waiting for the seller to start packing" in response.data
    assert b'href="/profile/farmer"' in response.data
    assert b'id="purchase-search"' in response.data
    assert b'id="purchase-status-filter"' in response.data
    assert b'id="purchase-date-from"' in response.data
    assert b'id="purchase-date-to"' in response.data


def test_cart_page_renders_marketplace_listing_thumbnail(monkeypatch):
    cart_item = {
        "id": 8,
        "commodity_name": "Tomatoes",
        "price": 45,
        "unit": "kg",
        "main_image": "tomatoes.jpg",
        "thumbnail_verified": 1,
        "seller_name": "farmer",
        "available_amount": 10,
        "listing_id": 3,
        "quantity": 2,
    }

    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.queries = []

        def execute(self, query, _params=()):
            self.query = query
            self.queries.append(query)
            return self

        def fetchone(self):
            if "SELECT setting_value FROM app_settings" in self.query:
                return {"setting_value": "0"}
            if "saved_delivery_province" in self.query:
                return {
                    "id": 5,
                    "saved_delivery_province": "Leyte",
                    "saved_delivery_city": "Palo",
                    "saved_delivery_barangay": "Pawing",
                    "saved_delivery_street": "12 Farm Road",
                    "saved_delivery_landmark": "Near the public market",
                }
            return {"id": 5}

        def fetchall(self):
            return [cart_item]

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 2)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/cart")

    assert response.status_code == 200
    assert b"Your Cart" in response.data
    assert b"Tomatoes" in response.data
    assert b"tomatoes.jpg" in response.data
    assert b'name="delivery_province"' in response.data
    assert b'name="delivery_city"' in response.data
    assert b'name="delivery_barangay"' in response.data
    assert b'name="delivery_street"' in response.data
    assert b'name="delivery_landmark"' in response.data
    assert b'value="Leyte"' in response.data
    assert b'value="Near the public market"' in response.data
    assert b'id="rememberDeliveryAddress" checked' in response.data
    assert b"currently unavailable" in response.data
    assert b'This feature is currently not available.' in response.data
    assert b'id="paymentCod" value="cod" checked' in response.data


def test_buyer_purchases_show_a_continue_payment_link_for_pending_xendit_order(monkeypatch):
    purchase = {
        "id": 29,
        "commodity_name": "Tomatoes",
        "seller_name": "farmer",
        "order_date": "2026-11-20 11:30:00",
        "delivery_date": None,
        "amount": 2,
        "unit": "kg",
        "price": 30,
        "order_status": "awaiting_payment",
        "buyer_confirmed": 0,
        "delivery_confirmed": 0,
        "buyer_rating": None,
        "delivery_province": "Leyte",
        "delivery_city": "Palo",
        "delivery_barangay": "Pawing",
        "delivery_street": "12 Farm Road",
        "delivery_landmark": None,
        "payment_method": "xendit",
        "xendit_checkout_url": "https://dev.xen.to/test-session",
    }

    class FakeCursor:
        def execute(self, _query, _params=()):
            return self

        def fetchall(self):
            return [purchase]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/my-purchases")

    assert response.status_code == 200
    assert b"Awaiting Payment" in response.data
    assert b"Waiting for Xendit to confirm your payment." in response.data
    assert b'href="https://dev.xen.to/test-session"' in response.data
    assert b"Cancel unpaid checkout" in response.data
    assert b'data-order-id="29"' in response.data
    assert b"This page will update automatically." in response.data


def test_pending_payment_status_returns_only_the_logged_in_buyers_pending_orders(monkeypatch):
    class FakeCursor:
        def execute(self, query, params=()):
            assert "buyer_username = ?" in query
            assert "order_status = 'awaiting_payment'" in query
            assert params == ("buyer",)
            return self

        def fetchall(self):
            return [{"id": 29}]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/pending-payment-status")

    assert response.status_code == 200
    assert response.get_json() == {"pending_order_ids": [29]}
    assert "no-store" in response.headers["Cache-Control"]


def test_buyer_can_cancel_their_own_pending_xendit_checkout(monkeypatch):
    class FakeCursor:
        def execute(self, query, params=()):
            assert "buyer_username = ?" in query
            assert "order_status = 'awaiting_payment'" in query
            assert params == (29, "buyer")
            return self

        def fetchone(self):
            return {"xendit_reference_id": "agri-test-reference"}

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    released_references = []
    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(
        marketplace_routes,
        "_release_xendit_reservation",
        released_references.append,
    )
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.post("/marketplace/cancel-pending-payment/29")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/marketplace/my-purchases")
    assert released_references == ["agri-test-reference"]


def test_buyer_cannot_cancel_another_users_pending_checkout(monkeypatch):
    class FakeCursor:
        def execute(self, query, params=()):
            assert "buyer_username = ?" in query
            assert params == (29, "buyer")
            return self

        def fetchone(self):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(
        marketplace_routes,
        "_release_xendit_reservation",
        lambda _reference: pytest.fail("another buyer's checkout must not be released"),
    )
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.post("/marketplace/cancel-pending-payment/29")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/marketplace/my-purchases")


def test_seller_cannot_start_packing_before_payment_is_confirmed(monkeypatch):
    order = {
        "id": 29,
        "commodity_name": "Tomatoes",
        "order_status": "awaiting_payment",
        "buyer_username": "buyer",
        "buyer_first_name": "Buyer",
        "buyer_last_name": "Person",
        "buyer_profile_username": "buyer",
        "buyer_email": "buyer@example.com",
        "buyer_phone_number": "+639123456789",
        "buyer_location": "Sample City",
        "amount": 2,
        "unit": "kg",
        "price": 30,
        "order_date": "2026-11-20 11:30:00",
        "delivery_confirmed": 0,
        "buyer_confirmed": 0,
        "delivery_province": "Leyte",
        "delivery_city": "Palo",
        "delivery_barangay": "Pawing",
        "delivery_street": "12 Farm Road",
        "delivery_landmark": None,
        "payment_method": "xendit",
    }

    class FakeCursor:
        def __init__(self):
            self.query = ""

        def execute(self, query, _params=()):
            self.query = query
            return self

        def fetchone(self):
            return {"id": 4}

        def fetchall(self):
            return [order]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "seller"
            session["role"] = "seller"

        response = client.get("/marketplace/transactions")

    assert response.status_code == 200
    assert b"Awaiting Payment" in response.data
    assert b"Online payment via Xendit" in response.data
    assert b"Online payment confirmed by Xendit" not in response.data
    assert b"Waiting for the buyer's payment confirmation." in response.data
    assert b"Mark as Packing" not in response.data


def test_product_page_contact_seller_link_opens_seller_messages(monkeypatch):
    listing = {
        "id": 3,
        "user_id": 4,
        "commodity_name": "Banana",
        "listing_type": "standard",
        "price": 23,
        "unit": "kg",
        "amount": 13,
        "listing_date": "2026-10-09 19:41:00",
        "description": "",
        "available_date": None,
        "location": "Palo, Leyte, Eastern Visayas",
        "seller_name": "seller name",
        "seller_location": "Palo, Leyte",
        "reliability_score": None,
        "reliability_status": "Not Yet Rated",
        "completed_transactions": 0,
        "cancelled_transactions": 0,
        "total_transactions": 0,
        "main_image": None,
    }

    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.queries = []

        def execute(self, query, _params=()):
            self.query = query
            self.queries.append(query)
            return self

        def fetchone(self):
            return listing

        def fetchall(self):
            return []

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "promote_due_preorders", lambda: None)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)
    app_module.app.config.update(TESTING=True)

    connection = FakeConnection()
    monkeypatch.setattr(marketplace_routes, "get_db", lambda: connection)
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/product/3")

    assert response.status_code == 200
    assert b"Palo, Leyte, Eastern Visayas" in response.data
    assert b"Contact Seller" in response.data
    assert b"/messages?recipient=seller+name" in response.data
    assert "FROM marketplace" in connection.fake_cursor.queries[2]


def test_checkout_requires_delivery_address_before_database_access(monkeypatch):
    monkeypatch.setattr(
        marketplace_routes,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be accessed")),
    )
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.post("/marketplace/cart/checkout", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Province is required for delivery."


def test_checkout_saves_delivery_address_on_order(monkeypatch):
    listing = {
        "id": 3,
        "user_id": 4,
        "username": "farmer",
        "commodity_id": 9,
        "commodity_name": "Tomatoes",
        "amount": 5,
        "price": 45,
        "unit": "kg",
        "listing_date": "2026-10-09 19:41:00",
        "expiry_date": None,
        "description": "Fresh produce",
        "location": "Farm location",
        "main_image": "tomatoes.jpg",
        "listing_type": "standard",
        "available_date": None,
    }
    cart_item = {
        "cart_id": 16,
        "listing_id": 3,
        "quantity": 5,
        "listing_status": "available",
    }
    marketplace_updates = []
    saved_address_updates = []
    session_payloads = []

    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.rowcount = 1

        def execute(self, query, params=()):
            self.query = query
            if query.lstrip().startswith("UPDATE marketplace"):
                marketplace_updates.append((query, params))
            if query.lstrip().startswith("UPDATE users"):
                saved_address_updates.append((query, params))
            return self

        def fetchone(self):
            if "SELECT id FROM users" in self.query:
                return {"id": 5}
            if "FROM marketplace" in self.query and "status = 'available'" in self.query:
                return listing
            return None

        def fetchall(self):
            if "FROM cart c" in self.query:
                return [cart_item]
            return []

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setitem(app_module.app.config, "XENDIT_SECRET_KEY", "test-secret")
    monkeypatch.setitem(app_module.app.config, "XENDIT_COUNTRY", "PH")
    monkeypatch.setitem(app_module.app.config, "XENDIT_CURRENCY", "PHP")
    monkeypatch.setitem(app_module.app.config, "APP_BASE_URL", "https://agri.example")

    def create_session(_secret_key, payload):
        session_payloads.append(payload)
        return {
            "payment_session_id": "ps-test",
            "payment_link_url": "https://dev.xen.to/pay-test",
        }

    monkeypatch.setattr(marketplace_routes, "create_payment_session", create_session)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.post(
            "/marketplace/cart/checkout",
            json={
                "delivery_province": "Leyte",
                "delivery_city": "Palo",
                "delivery_barangay": "Pawing",
                "delivery_street": "12 Farm Road",
                "delivery_landmark": "Near the public market",
                "remember_delivery_address": True,
            },
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "redirect"
    assert response.get_json()["checkout_url"] == "https://dev.xen.to/pay-test"
    update_query, update_params = marketplace_updates[0]
    assert "delivery_province = ?" in update_query
    assert update_params[3:8] == (
        "Leyte",
        "Palo",
        "Pawing",
        "12 Farm Road",
        "Near the public market",
    )
    assert "order_status = ?" in update_query
    assert update_params[1] == "awaiting_payment"
    assert update_params[9] == "xendit"
    assert len(saved_address_updates) == 1
    assert saved_address_updates[0][1] == (
        "Leyte",
        "Palo",
        "Pawing",
        "12 Farm Road",
        "Near the public market",
        5,
    )
    assert session_payloads[0]["amount"] == 225
    assert session_payloads[0]["currency"] == "PHP"
    assert session_payloads[0]["items"][0]["quantity"] == 5
    assert session_payloads[0]["items"][0]["category"] == "Agricultural products"
    assert session_payloads[0]["success_return_url"] == (
        "https://agri.example/marketplace/my-purchases"
    )
    assert session_payloads[0]["cancel_return_url"] == (
        "https://agri.example/marketplace/my-purchases"
    )

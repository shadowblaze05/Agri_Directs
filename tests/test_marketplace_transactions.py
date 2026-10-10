import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import marketplace as marketplace_routes


def test_seller_transactions_page_shows_buyer_details_and_current_order_state(monkeypatch):
    transaction = {
        "id": 17,
        "crop_name": "Tomatoes",
        "order_status": "packing",
        "buyer_first_name": "Buyer",
        "buyer_last_name": "Person",
        "buyer_username": "buyer",
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
    assert b'href="/messages?recipient=buyer"' in response.data
    assert b"buyer@example.com" in response.data
    assert b"+639123456789" in response.data
    assert b"12 Farm Road" in response.data
    assert b"Near the public market" in response.data
    assert b"Packing" in response.data
    assert b"Mark as Shipped" in response.data


def test_buyer_purchases_page_renders_orders_in_their_current_stage(monkeypatch):
    purchase = {
        "id": 22,
        "crop_name": "Sweet Corn",
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
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/my-purchases")

    assert response.status_code == 200
    assert b"My Purchases" in response.data
    assert b"Sweet Corn" in response.data
    assert b"Waiting for the seller to start packing" in response.data


def test_cart_page_renders_marketplace_listing_thumbnail(monkeypatch):
    cart_item = {
        "id": 8,
        "crop_name": "Tomatoes",
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

        def execute(self, query, _params=()):
            self.query = query
            return self

        def fetchone(self):
            return {"id": 5}

        def fetchall(self):
            return [cart_item]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

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


def test_product_page_contact_seller_link_opens_seller_messages(monkeypatch):
    listing = {
        "id": 3,
        "user_id": 4,
        "crop_name": "Banana",
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

        def execute(self, query, _params=()):
            self.query = query
            return self

        def fetchone(self):
            return listing

        def fetchall(self):
            return []

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "promote_due_preorders", lambda: None)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"

        response = client.get("/marketplace/product/3")

    assert response.status_code == 200
    assert b"Palo, Leyte, Eastern Visayas" in response.data
    assert b"Contact Seller" in response.data
    assert b"/messages?recipient=seller+name" in response.data


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
    listing = {"amount": 5, "status": "available"}
    cart_item = {
        "listing_id": 3,
        "seller_id": 4,
        "seller_name": "farmer",
        "crop_id": 9,
        "crop_name": "Tomatoes",
        "price": 45,
        "amount": 5,
        "available_amount": 5,
        "unit": "kg",
        "location": "Farm location",
        "quantity": 5,
    }
    marketplace_updates = []

    class FakeCursor:
        def __init__(self):
            self.query = ""

        def execute(self, query, params=()):
            self.query = query
            if query.lstrip().startswith("UPDATE marketplace"):
                marketplace_updates.append((query, params))
            return self

        def fetchone(self):
            if "SELECT id FROM users" in self.query:
                return {"id": 5}
            if "SELECT amount, status FROM marketplace" in self.query:
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
            },
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    update_query, update_params = marketplace_updates[0]
    assert "delivery_province = ?" in update_query
    assert update_params[2:7] == (
        "Leyte",
        "Palo",
        "Pawing",
        "12 Farm Road",
        "Near the public market",
    )

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.routes import admin as admin_routes
from sqlalchemy import text


class FakeCursor:
    def __init__(self, role="admin"):
        self.calls = []
        self.role = role

    def execute(self, query, params=()):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        if "SELECT role, is_active FROM users" in self.calls[-1][0]:
            return {"role": self.role, "is_active": 1}
        return {"total": 2, "completed": 1}

    def fetchall(self):
        return [
            {
                "id": 12,
                "crop_name": "Tomatoes",
                "username": "farmer",
                "seller_name": "farmer",
                "buyer_username": "buyer",
                "amount": 4,
                "preorder_quantity": None,
                "transaction_quantity": 4,
                "unit": "kg",
                "price": 25,
                "listing_type": "standard",
                "order_status": "completed",
                "preorder_status": None,
                "status": "delivered",
                "order_date": "2026-10-01",
                "delivery_confirmed": 1,
                "buyer_confirmed": 1,
                "completion_state": "completed",
            },
            {
                "id": 13,
                "crop_name": "Sweet corn",
                "username": "farmer",
                "seller_name": "farmer",
                "buyer_username": "buyer2",
                "amount": 3,
                "preorder_quantity": None,
                "transaction_quantity": 3,
                "unit": "kg",
                "price": 20,
                "listing_type": "standard",
                "order_status": "packing",
                "preorder_status": None,
                "status": "sold",
                "order_date": "2026-10-02",
                "delivery_confirmed": 0,
                "buyer_confirmed": 0,
                "completion_state": "incomplete",
            },
        ]


class FakeConnection:
    def __init__(self, role="admin"):
        self.fake_cursor = FakeCursor(role)

    def cursor(self):
        return self.fake_cursor

    def close(self):
        return None


def test_admin_transactions_lists_completed_and_incomplete_orders(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(admin_routes, "get_db", lambda: connection)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"

        response = client.get("/admin/marketplace/transactions")

    assert response.status_code == 200
    assert b"Marketplace transactions" in response.data
    assert b"2</div>" in response.data
    assert b"Completed" in response.data
    assert b"Incomplete" in response.data
    assert b"Tomatoes" in response.data
    assert b"Sweet corn" in response.data
    assert any("buyer_username" in query and "order_status" in query for query, _ in connection.fake_cursor.calls)


def test_admin_transactions_requires_admin_role(monkeypatch):
    connection = FakeConnection(role="user")
    monkeypatch.setattr(admin_routes, "get_db", lambda: connection)
    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "regular-user"
            session["role"] = "user"

        response = client.get("/admin/marketplace/transactions")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_demoted_admin_session_loses_admin_console_access(monkeypatch):
    connection = FakeConnection(role="user")
    monkeypatch.setattr(admin_routes, "get_db", lambda: connection)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"

        response = client.get("/admin")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_admin_transactions_query_includes_all_order_states_not_open_listings(tmp_path):
    database_uri = f"sqlite:///{(tmp_path / 'admin-transactions.db').as_posix()}"
    application = app_module.create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": database_uri}
    )
    with application.app_context():
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, "
                "is_active INTEGER NOT NULL DEFAULT 1)"
            ))
            connection.execute(text("""
                CREATE TABLE marketplace (
                    id INTEGER PRIMARY KEY, user_id INTEGER, username TEXT, crop_name TEXT,
                    buyer_username TEXT, amount INTEGER, preorder_quantity INTEGER,
                    unit TEXT, price FLOAT, listing_type TEXT, order_status TEXT,
                    preorder_status TEXT, status TEXT, order_date TEXT, delivery_date TEXT,
                    delivery_confirmed INTEGER, buyer_confirmed INTEGER, buyer_rating INTEGER,
                    listing_date TEXT
                )
            """))
            connection.execute(text(
                "INSERT INTO users (id, username, role, is_active) "
                "VALUES (1, 'farmer', 'user', 1), (2, 'admin', 'admin', 1)"
            ))
            connection.execute(text("""
                INSERT INTO marketplace (
                    id, user_id, username, crop_name, buyer_username, amount, unit, price,
                    listing_type, order_status, status, order_date, delivery_confirmed,
                    buyer_confirmed, listing_date
                ) VALUES
                    (1, 1, 'farmer', 'Tomatoes', 'buyer1', 4, 'kg', 25, 'standard',
                     'completed', 'delivered', '2026-10-01', 1, 1, '2026-09-01'),
                    (2, 1, 'farmer', 'Sweet corn', 'buyer2', 3, 'kg', 20, 'standard',
                     'packing', 'sold', '2026-10-02', 0, 0, '2026-09-02'),
                    (3, 1, 'farmer', 'Rice', NULL, 10, 'kg', 15, 'standard',
                     'available', 'available', NULL, 0, 0, '2026-09-03'),
                    (4, 1, 'farmer', 'Traded beans', NULL, 2, 'kg', 0, 'standard',
                     'available', 'traded', NULL, 0, 0, '2026-09-04')
            """))

    with application.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"

        response = client.get("/admin/marketplace/transactions")

    assert response.status_code == 200
    assert b"Tomatoes" in response.data
    assert b"Sweet corn" in response.data
    assert b"Traded beans" in response.data
    assert b"Rice" not in response.data
    assert b"All transactions</div><div class=\"fs-3 fw-bold\">3" in response.data
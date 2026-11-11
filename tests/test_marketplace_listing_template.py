import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import marketplace as marketplace_routes
from app.routes.marketplace import _available_inventory_quantity


def test_available_inventory_excludes_active_standard_listings():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE inventory (farmer TEXT, crop_id INTEGER, quantity INTEGER);
        CREATE TABLE marketplace (
            username TEXT, crop_id INTEGER, amount INTEGER, status TEXT,
            listing_type TEXT
        );
        INSERT INTO inventory VALUES ('farmer', 1, 24);
        INSERT INTO marketplace VALUES ('farmer', 1, 9, 'available', 'standard');
        INSERT INTO marketplace VALUES ('farmer', 1, 20, 'available', 'preorder');
        INSERT INTO marketplace VALUES ('farmer', 1, 5, 'sold', 'standard');
        INSERT INTO marketplace VALUES ('another-farmer', 1, 4, 'available', 'standard');
    """)

    assert _available_inventory_quantity(connection.cursor(), "farmer", 1) == 15
    connection.close()


def test_add_listing_renders_inventory_crop_as_option_text():
    crop = {
        "id": 1,
        "crops_name": "Tomatoes",
        "total_quantity": 12,
        "pricing_mode": None,
        "reference_price": None,
        "price_range": None,
        "minimum_price": None,
        "maximum_price": None,
    }

    with app_module.app.test_request_context("/marketplace/add"):
        rendered = app_module.app.jinja_env.get_template("add_listing.html").render(
            listing=None,
            crops=[crop],
            all_crops=[],
            cart_count=0,
            profile_location_available=False,
            user_inventory=[],
        )

    assert '<option value="1"' in rendered
    assert ">Tomatoes (12 kg available)" in rendered
    assert 'id="amountLabel" class="form-label">Amount (kg) *' in rendered
    assert "Quantity Wanted (kg) *" in rendered
    assert "GPS is compared with your saved profile coordinates" in rendered
    assert "neither location is independently verified" in rendered
    assert "Camera-verified thumbnail" not in rendered


@pytest.mark.parametrize(
    ("role", "expected_type"),
    [("buyer", "standard"), ("seller", "looking_for")],
)
def test_marketplace_defaults_listing_type_filter_for_role(
    monkeypatch, role, expected_type
):
    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            return self

        def fetchall(self):
            return []

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "promote_due_preorders", lambda: None)
    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    monkeypatch.setattr(marketplace_routes, "get_cart_count", lambda _username: 0)

    with app_module.app.test_request_context("/marketplace"):
        from flask import session

        session["user"] = "test-user"
        session["role"] = role
        response = marketplace_routes.marketplace()

    assert f'<option value="{expected_type}" selected>' in response

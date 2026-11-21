from io import BytesIO
import sys
from pathlib import Path

from PIL import Image
from sqlalchemy import text
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db


def _image_upload():
    image_data = BytesIO()
    Image.new("RGB", (8, 8), color="green").save(image_data, format="PNG")
    image_data.seek(0)
    return image_data


def test_admin_can_manage_commodity_details_and_default_image(tmp_path):
    database_uri = f"sqlite:///{(tmp_path / 'commodity-details.db').as_posix()}"
    application = app_module.create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": database_uri}
    )
    with application.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT,
                    role TEXT, email TEXT, first_name TEXT, last_name TEXT,
                    location TEXT, is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    is_verified BOOLEAN NOT NULL DEFAULT TRUE,
                    auth_version INTEGER NOT NULL DEFAULT 0,
                    reactivate_on DATE
                )
            """))
            connection.execute(text("""
                CREATE TABLE commodity_categories (
                    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                    description TEXT, default_price_unit TEXT NOT NULL DEFAULT 'kg'
                )
            """))
            connection.execute(text("""
                CREATE TABLE commodities (
                    id INTEGER PRIMARY KEY, commodity_name TEXT UNIQUE NOT NULL,
                    category_id INTEGER, description TEXT, default_image TEXT,
                    default_price_unit TEXT NOT NULL DEFAULT 'kg'
                )
            """))
            connection.execute(text("""
                CREATE TABLE commodity_pricing (
                    commodity_id INTEGER PRIMARY KEY, price_unit TEXT NOT NULL DEFAULT 'kg'
                )
            """))
            connection.execute(text("""
                CREATE TABLE commodity_price_units (unit TEXT PRIMARY KEY NOT NULL)
            """))
            connection.execute(text("""
                CREATE TABLE marketplace (id INTEGER PRIMARY KEY, unit TEXT)
            """))
            connection.execute(
                text("INSERT INTO commodity_price_units (unit) VALUES ('kg'), ('pc'), ('pack')")
            )
            connection.execute(
                text("INSERT INTO users (username, password, role) "
                     "VALUES ('admin', :password, 'admin')"),
                {"password": generate_password_hash("admin")},
            )

    image_directory = Path(application.static_folder) / "uploads" / "commodity_details"
    saved_image_path = None
    try:
        with application.test_client() as client:
            client.post("/login", data={"username": "admin", "password": "admin"})

            response = client.get("/admin/commodity-details")
            assert response.status_code == 200
            assert b"Commodity details &amp; images" in response.data
            assert b'id="commodityInformationButton"' in response.data
            assert b'id="commodityCategoryButton"' in response.data
            assert b'id="commodityPriceUnitButton"' in response.data
            assert b'id="commodityInformationPanel"' in response.data
            assert b'id="commodityCategoryPanel" role="tabpanel" aria-labelledby="commodityCategoryButton" hidden' in response.data
            assert b'id="commodityPriceUnitPanel" role="tabpanel" aria-labelledby="commodityPriceUnitButton" hidden' in response.data
            assert b"Registered price units" in response.data
            assert b'id="commoditySearch"' in response.data
            assert b'id="commodityFilter"' in response.data

            response = client.post(
                "/admin/commodity-details/categories",
                data={"name": "Vegetables", "description": "Edible crops"},
            )
            assert response.status_code == 302
            with application.app_context():
                category_id = db.session.execute(
                    text("SELECT id FROM commodity_categories WHERE name='Vegetables'")
                ).scalar_one()

            response = client.post(
                "/admin/commodity-details/price-units",
                data={"unit": "sack"},
            )
            assert response.status_code == 302
            assert response.headers["Location"].endswith("#commodityPriceUnitPanel")

            response = client.post(
                "/admin/commodity-details/price-units/kg/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT unit FROM commodity_price_units WHERE unit='kg'")
                ).scalar_one() == "kg"

            response = client.post(
                "/admin/commodity-details/commodities",
                data={
                    "name": "Tomato",
                    "category_id": str(category_id),
                    "description": "Fresh red tomatoes.",
                    "default_image": (_image_upload(), "tomato.png"),
                },
                content_type="multipart/form-data",
            )
            assert response.status_code == 302
            with application.app_context():
                commodity = db.session.execute(
                    text("SELECT id, description, default_image FROM commodities "
                         "WHERE commodity_name='Tomato'")
                ).one()
                commodity_id = commodity.id
                saved_image_path = image_directory / commodity.default_image
                assert commodity.description == "Fresh red tomatoes."
                assert saved_image_path.is_file()

            with application.app_context():
                db.session.execute(
                    text("INSERT INTO commodity_pricing (commodity_id) VALUES (:id)"),
                    {"id": commodity_id},
                )
                db.session.commit()

            response = client.post(
                f"/admin/commodity-details/categories/{category_id}",
                data={
                    "name": "Vegetables",
                    "description": "Edible crops",
                    "default_price_unit": "sack",
                },
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT default_price_unit FROM commodities WHERE id=:id"),
                    {"id": commodity_id},
                ).scalar_one() == "sack"
                assert db.session.execute(
                    text("SELECT price_unit FROM commodity_pricing WHERE commodity_id=:id"),
                    {"id": commodity_id},
                ).scalar_one() == "sack"

            response = client.post(
                f"/admin/commodity-details/commodities/{commodity_id}/price-unit",
                data={"default_price_unit": "sack"},
            )
            assert response.status_code == 302
            assert response.headers["Location"].endswith("#commodityPriceUnitPanel")
            with application.app_context():
                assert db.session.execute(
                    text("SELECT default_price_unit FROM commodities WHERE id=:id"),
                    {"id": commodity_id},
                ).scalar_one() == "sack"
                assert db.session.execute(
                    text("SELECT price_unit FROM commodity_pricing WHERE commodity_id=:id"),
                    {"id": commodity_id},
                ).scalar_one() == "sack"

            response = client.post(
                "/admin/commodity-details/price-units/sack/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT unit FROM commodity_price_units WHERE unit='sack'")
                ).scalar_one() == "sack"

            response = client.post(
                f"/admin/commodity-details/categories/{category_id}/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT id FROM commodity_categories WHERE id=:id"),
                    {"id": category_id},
                ).first() is not None

            response = client.post(
                f"/admin/commodity-details/commodities/{commodity_id}",
                data={
                    "name": "Tomato",
                    "category_id": str(category_id),
                    "description": "Updated commodity description.",
                },
            )
            assert response.status_code == 302
            with application.app_context():
                updated_commodity = db.session.execute(
                    text("SELECT description, default_image, default_price_unit FROM commodities "
                         "WHERE id=:id"),
                    {"id": commodity_id},
                ).one()
                assert updated_commodity.description == "Updated commodity description."
                assert updated_commodity.default_image == commodity.default_image
                assert updated_commodity.default_price_unit == "sack"

            response = client.get("/admin/commodity-details")
            assert response.status_code == 200
            assert (
                f"/admin/commodity-details/commodities/{commodity_id}/delete".encode()
                in response.data
            )

            response = client.post(
                f"/admin/commodity-details/commodities/{commodity_id}/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT id FROM commodities WHERE id=:id"),
                    {"id": commodity_id},
                ).first() is None
                db.session.execute(
                    text("DELETE FROM commodity_pricing WHERE commodity_id=:id"),
                    {"id": commodity_id},
                )
                db.session.commit()
            assert not saved_image_path.exists()

            response = client.post(
                f"/admin/commodity-details/categories/{category_id}/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT id FROM commodity_categories WHERE id=:id"),
                    {"id": category_id},
                ).first() is None

            with application.app_context():
                db.session.execute(
                    text("INSERT INTO marketplace (unit) VALUES ('sack')")
                )
                db.session.commit()
            response = client.post(
                "/admin/commodity-details/price-units/sack/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT unit FROM commodity_price_units WHERE unit='sack'")
                ).scalar_one() == "sack"
                db.session.execute(text("DELETE FROM marketplace"))
                db.session.commit()

            response = client.post(
                "/admin/commodity-details/price-units/sack/delete"
            )
            assert response.status_code == 302
            with application.app_context():
                assert db.session.execute(
                    text("SELECT unit FROM commodity_price_units WHERE unit='sack'")
                ).first() is None
    finally:
        if saved_image_path and saved_image_path.is_file():
            saved_image_path.unlink()


def test_looking_for_listing_uses_commodity_default_image():
    commodity_image = "tomato.png"
    with app_module.app.test_request_context("/marketplace/looking-for"):
        rendered = app_module.app.jinja_env.get_template("looking_for.html").render(
            listings=[{
                "id": 1,
                "main_image": None,
                "commodity_default_image": commodity_image,
                "commodity_name": "Tomato",
                "amount": 10,
                "unit": "kg",
                "price": None,
                "location": "Farm",
                "username": "buyer",
            }],
            cart_count=0,
        )

    assert "uploads/commodity_details/tomato.png" in rendered

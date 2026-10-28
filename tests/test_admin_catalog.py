import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from sqlalchemy import text
from werkzeug.security import generate_password_hash


def test_admin_can_assign_and_reassign_crops_by_category(tmp_path):
    database_uri = f"sqlite:///{(tmp_path / 'admin-catalog.db').as_posix()}"
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
                    is_verified BOOLEAN NOT NULL DEFAULT TRUE
                )
            """))
            connection.execute(text("""
                CREATE TABLE crop_categories (
                    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                    description TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE crops (
                    id INTEGER PRIMARY KEY, crops_name TEXT UNIQUE,
                    category_id INTEGER
                )
            """))
            connection.execute(text("""
                CREATE TABLE crop_pricing (
                    crop_id INTEGER PRIMARY KEY REFERENCES crops(id) ON DELETE CASCADE,
                    pricing_mode TEXT NOT NULL,
                    price_unit TEXT NOT NULL DEFAULT 'kg',
                    reference_price NUMERIC(10, 2),
                    price_range NUMERIC(10, 2),
                    minimum_price NUMERIC(10, 2),
                    maximum_price NUMERIC(10, 2)
                )
            """))
            connection.execute(text("""
                CREATE TABLE inventory (
                    id INTEGER PRIMARY KEY, crop_id INTEGER, crop_name TEXT
                )
            """))
            connection.execute(
                text(
                    "INSERT INTO users (username, password, role) "
                    "VALUES (:username, :password, 'admin')"
                ),
                {
                    "username": "admin",
                    "password": generate_password_hash("admin"),
                },
            )
            connection.execute(
                text("INSERT INTO crop_categories (name) VALUES ('Grains'), ('Vegetables')")
            )
            connection.execute(
                text("INSERT INTO crops (crops_name) VALUES ('Rice')")
            )
            category_ids = connection.execute(
                text("SELECT id, name FROM crop_categories")
            ).all()
            category_ids = {row.name: row.id for row in category_ids}
            grains_id = category_ids["Grains"]
            vegetables_id = category_ids["Vegetables"]

    with application.test_client() as client:
        client.post("/login", data={"username": "admin", "password": "admin"})

        response = client.post(
            "/admin/crops/create",
            data={"name": "Oats", "category_id": str(grains_id)},
        )
        assert response.status_code == 302

        with application.app_context():
            connection = db.session.execute(
                text("SELECT id, category_id FROM crops WHERE crops_name='Oats'")
            ).one()
            oats = {"id": connection.id, "category_id": connection.category_id}
            rice_id = db.session.execute(
                text("SELECT id FROM crops WHERE crops_name='Rice'")
            ).scalar_one()
        assert oats["category_id"] == grains_id

        response = client.post(
            f"/admin/crops/edit/{rice_id}",
            data={"name": "Rice", "category_id": str(vegetables_id)},
        )
        assert response.status_code == 302

        response = client.post(
            f"/admin/crops/edit/{oats['id']}",
            data={"name": "Oats"},
        )
        assert response.status_code == 302
        with application.app_context():
            oats_category_id = db.session.execute(
                text("SELECT category_id FROM crops WHERE id=:id"),
                {"id": oats["id"]},
            ).scalar_one()
        assert oats_category_id == grains_id

        response = client.get("/admin/catalog")
        assert response.status_code == 200
        assert b"Crops by category" in response.data
        assert b"Grains" in response.data
        assert b"Vegetables" in response.data
        assert b"Oats" in response.data

        response = client.post(f"/admin/crop-categories/delete/{grains_id}")
        assert response.status_code == 302
        with application.app_context():
            category = db.session.execute(
                text("SELECT id FROM crop_categories WHERE id=:id"),
                {"id": grains_id},
            ).first()
            assert category is not None

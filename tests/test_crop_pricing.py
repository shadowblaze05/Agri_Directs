import importlib.util
from io import BytesIO
import sys
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _application(tmp_path):
    application = app_module.create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'crop-pricing.db').as_posix()}",
        }
    )
    with application.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE, role TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE, location TEXT,
                    location_latitude REAL, location_longitude REAL,
                    location_verified BOOLEAN NOT NULL DEFAULT FALSE
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
                    id INTEGER PRIMARY KEY, crop_id INTEGER, crop_name TEXT,
                    farmer TEXT, quantity INTEGER
                )
            """))
            connection.execute(text("""
                CREATE TABLE marketplace (
                    id INTEGER PRIMARY KEY, user_id INTEGER, username TEXT,
                    crop_id INTEGER, crop_name TEXT, amount INTEGER, price REAL,
                    unit TEXT, status TEXT, description TEXT, listing_type TEXT,
                    main_image TEXT
                )
            """))
            connection.execute(text(
                "INSERT INTO users (id, username, role) VALUES "
                "(1, 'admin', 'admin'), (2, 'seller', 'user')"
            ))
            connection.execute(text(
                "INSERT INTO crop_categories (id, name) VALUES (1, 'Vegetables')"
            ))
            connection.execute(text(
                "INSERT INTO crops (id, crops_name, category_id) "
                "VALUES (1, 'Tomato', 1)"
            ))
            connection.execute(text(
                "INSERT INTO inventory (crop_id, farmer, quantity) "
                "VALUES (1, 'seller', 0)"
            ))
            connection.execute(text("""
                INSERT INTO marketplace (
                    id, user_id, username, crop_id, crop_name, amount, price,
                    unit, status, description, listing_type, main_image
                ) VALUES (
                    1, 2, 'seller', 1, 'Tomato', 1, 48, 'kg', 'available',
                    '', 'standard', NULL
                )
            """))
    return application


def _set_user(client, username):
    with client.session_transaction() as session:
        session["user"] = username


def _flash_messages(client):
    with client.session_transaction() as session:
        return [message for _, message in session.get("_flashes", [])]


def test_admin_price_range_is_saved_and_enforced_for_seller_listings(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")

    response = admin_client.post(
        "/admin/crops/1/pricing",
        data={
            "pricing_mode": "range",
            "reference_price": "48",
            "price_range": "10",
        },
    )
    assert response.status_code == 302

    with application.app_context():
        pricing = db.session.execute(
            text(
                "SELECT pricing_mode, reference_price, price_range "
                "FROM crop_pricing WHERE crop_id=1"
            )
        ).one()
        assert pricing.pricing_mode == "range"
        assert float(pricing.reference_price) == 48
        assert float(pricing.price_range) == 10

    seller_client = application.test_client()
    _set_user(seller_client, "seller")
    response = seller_client.post(
        "/marketplace/add",
        data={
            "crop_id": "1",
            "amount": "1",
            "price": "37.99",
            "listing_type": "standard",
        },
    )
    assert response.status_code == 302
    assert any("₱38.00–₱58.00" in message for message in _flash_messages(seller_client))

    with seller_client.session_transaction() as session:
        session.pop("_flashes", None)
    response = seller_client.post(
        "/marketplace/add",
        data={
            "crop_id": "1",
            "amount": "1",
            "price": "48",
            "unit": "piece",
            "listing_type": "standard",
        },
    )
    assert response.status_code == 302
    assert any(
        "don't have enough Tomato" in message
        for message in _flash_messages(seller_client)
    )

    with seller_client.session_transaction() as session:
        session.pop("_flashes", None)
    response = seller_client.post(
        "/marketplace/add",
        data={
            "crop_id": "1",
            "amount": "1",
            "price": "58.00",
            "listing_type": "standard",
        },
    )
    assert response.status_code == 302
    assert any(
        "don't have enough Tomato" in message
        for message in _flash_messages(seller_client)
    )

    with seller_client.session_transaction() as session:
        session.pop("_flashes", None)
    response = seller_client.post(
        "/marketplace/edit/1",
        data={"amount": "1", "price": "58", "unit": "piece"},
    )
    assert response.status_code == 302
    with application.app_context():
        listing_unit = db.session.execute(
            text("SELECT unit FROM marketplace WHERE id=1")
        ).scalar_one()
        assert listing_unit == "kg"


def test_admin_can_set_explicit_bounds_and_filter_catalog(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")

    response = admin_client.post(
        "/admin/crops/1/pricing",
        data={
            "pricing_mode": "bounds",
            "minimum_price": "42",
            "maximum_price": "63.50",
            "reference_price": "48",
        },
    )
    assert response.status_code == 302

    response = admin_client.get(
        "/admin/catalog?q=Tomato&category_id=1&crop_id=1"
    )
    assert response.status_code == 200
    assert b"Allowed seller price: \xe2\x82\xb142.00\xe2\x80\x93\xe2\x82\xb163.50" in response.data


def test_catalog_has_selected_crop_pricing_editor(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")

    response = admin_client.get("/admin/catalog")

    assert response.status_code == 200
    assert b"Set a rule for one crop" in response.data
    assert b"selectedPricingCrop" in response.data
    assert b"Apply one price rule to every crop in this file" in response.data


def test_admin_can_import_csv_and_rejects_invalid_rows_without_partial_save(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")

    template_response = admin_client.get("/admin/catalog/pricing/template")
    assert template_response.status_code == 200
    assert b"crop_name,category_name,price_unit" in template_response.data

    csv_data = (
        "crop_name,category_name,price_unit\n"
        "Tomato,Vegetables,kg\n"
    )
    response = admin_client.post(
        "/admin/catalog/pricing/import",
        data={"file": (BytesIO(csv_data.encode("utf-8")), "prices.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with application.app_context():
        assert db.session.execute(
            text("SELECT COUNT(*) FROM crop_pricing WHERE crop_id=1")
        ).scalar_one() == 0
        assert db.session.execute(
            text("SELECT crops_name FROM crops WHERE id=1")
        ).scalar_one() == "Tomato"

    invalid_csv = (
        "crop_name,category_name,price_unit\n"
        "New Crop,New Category,kg\n"
        "Tomato,Vegetables,piece\n"
    )
    response = admin_client.post(
        "/admin/catalog/pricing/import",
        data={"file": (BytesIO(invalid_csv.encode("utf-8")), "prices.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert any(
        "price_unit must be kg" in message
        for message in _flash_messages(admin_client)
    )
    with application.app_context():
        assert db.session.execute(
            text("SELECT COUNT(*) FROM crop_pricing")
        ).scalar_one() == 0
        assert db.session.execute(text("SELECT COUNT(*) FROM crops")).scalar_one() == 1
        assert db.session.execute(
            text("SELECT COUNT(*) FROM crop_categories")
        ).scalar_one() == 1

    valid_new_crop_csv = (
        "crop_name,category_name,price_unit\n"
        "New Crop,New Category,kg\n"
    )
    response = admin_client.post(
        "/admin/catalog/pricing/import",
        data={
            "file": (BytesIO(valid_new_crop_csv.encode("utf-8")), "new-crops.csv")
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with application.app_context():
        new_crop = db.session.execute(
            text(
                "SELECT crops.id, crop_categories.name AS category_name "
                "FROM crops JOIN crop_categories ON crop_categories.id=crops.category_id "
                "WHERE crops.crops_name='New Crop'"
            )
        ).one()
        assert new_crop.category_name == "New Category"
        assert db.session.execute(
            text("SELECT COUNT(*) FROM crop_pricing WHERE crop_id=:id"),
            {"id": new_crop.id},
        ).scalar_one() == 0


def test_admin_can_import_excel_crop_prices(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(
        (
            "crop_name",
            "category_name",
            "price_unit",
        )
    )
    worksheet.append(("Tomato", "Vegetables", "kg"))
    file_data = BytesIO()
    workbook.save(file_data)
    file_data.seek(0)

    response = admin_client.post(
        "/admin/catalog/pricing/import",
        data={"file": (file_data, "prices.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with application.app_context():
        assert db.session.execute(
            text("SELECT crops_name FROM crops WHERE id=1")
        ).scalar_one() == "Tomato"
        assert db.session.execute(
            text("SELECT COUNT(*) FROM crop_pricing WHERE crop_id=1")
        ).scalar_one() == 0


def test_admin_can_apply_shared_price_rule_to_all_imported_crops(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")
    csv_data = (
        "crop_name,category_name,price_unit\n"
        "Tomato,Vegetables,kg\n"
        "New Crop,Vegetables,kg\n"
    )

    response = admin_client.post(
        "/admin/catalog/pricing/import",
        data={
            "file": (BytesIO(csv_data.encode("utf-8")), "crops.csv"),
            "apply_pricing_rule": "1",
            "pricing_mode": "range",
            "reference_price": "50",
            "price_range": "8",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    with application.app_context():
        rules = db.session.execute(
            text(
                "SELECT pricing_mode, reference_price, price_range, price_unit "
                "FROM crop_pricing ORDER BY crop_id"
            )
        ).all()
        assert len(rules) == 2
        assert all(rule.pricing_mode == "range" for rule in rules)
        assert all(float(rule.reference_price) == 50 for rule in rules)
        assert all(float(rule.price_range) == 8 for rule in rules)
        assert all(rule.price_unit == "kg" for rule in rules)


def test_invalid_shared_price_rule_does_not_import_crops(tmp_path):
    application = _application(tmp_path)
    admin_client = application.test_client()
    _set_user(admin_client, "admin")
    csv_data = (
        "crop_name,category_name,price_unit\n"
        "New Crop,New Category,kg\n"
    )

    response = admin_client.post(
        "/admin/catalog/pricing/import",
        data={
            "file": (BytesIO(csv_data.encode("utf-8")), "crops.csv"),
            "apply_pricing_rule": "1",
            "pricing_mode": "bounds",
            "minimum_price": "60",
            "maximum_price": "40",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert any("Shared price rule" in message for message in _flash_messages(admin_client))
    with application.app_context():
        assert db.session.execute(text("SELECT COUNT(*) FROM crops")).scalar_one() == 1
        assert db.session.execute(
            text("SELECT COUNT(*) FROM crop_categories")
        ).scalar_one() == 1


def test_seller_expiry_requires_at_least_one_day(tmp_path):
    application = _application(tmp_path)
    seller_client = application.test_client()
    _set_user(seller_client, "seller")

    response = seller_client.post(
        "/marketplace/add",
        data={
            "crop_id": "1",
            "amount": "1",
            "price": "48",
            "expiry_days": "0",
            "listing_type": "standard",
        },
    )

    assert response.status_code == 302
    assert any("at least 1 day" in message for message in _flash_messages(seller_client))
    with application.app_context():
        assert db.session.execute(
            text("SELECT COUNT(*) FROM marketplace")
        ).scalar_one() == 1


def test_crop_pricing_migration_creates_database_foreign_key():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "3b6a91d8e2f4_add_crop_pricing.py"
    )
    spec = importlib.util.spec_from_file_location("crop_pricing_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE crops (id INTEGER PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        table_info = inspect(connection)
        assert "crop_pricing" in table_info.get_table_names()
        assert table_info.get_pk_constraint("crop_pricing")["constrained_columns"] == [
            "crop_id"
        ]
        assert "price_unit" in {
            column["name"] for column in table_info.get_columns("crop_pricing")
        }
        foreign_keys = table_info.get_foreign_keys("crop_pricing")
        assert any(
            foreign_key["referred_table"] == "crops"
            and foreign_key["constrained_columns"] == ["crop_id"]
            and foreign_key["options"].get("ondelete") == "CASCADE"
            for foreign_key in foreign_keys
        )
        assert {check["name"] for check in table_info.get_check_constraints("crop_pricing")} == {
            "ck_crop_pricing_mode",
            "ck_crop_pricing_unit",
            "ck_crop_pricing_values",
        }

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "crop_pricing" not in inspect(connection).get_table_names()


def test_migration_standardizes_existing_crop_pricing_units_to_kg():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "5d8c2a1e7f43_standardize_crop_pricing_kg.py"
    )
    spec = importlib.util.spec_from_file_location(
        "standardize_crop_pricing_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE crops (id INTEGER PRIMARY KEY)"))
        connection.execute(text("""
            CREATE TABLE crop_pricing (
                crop_id INTEGER PRIMARY KEY REFERENCES crops(id) ON DELETE CASCADE,
                pricing_mode TEXT NOT NULL,
                price_unit TEXT NOT NULL DEFAULT 'kg',
                reference_price NUMERIC(10, 2),
                price_range NUMERIC(10, 2),
                minimum_price NUMERIC(10, 2),
                maximum_price NUMERIC(10, 2),
                CONSTRAINT ck_crop_pricing_mode CHECK (pricing_mode IN ('range', 'bounds')),
                CONSTRAINT ck_crop_pricing_unit CHECK (
                    price_unit IN ('kg', 'g', 'lb', 'oz', 'piece', 'bundle')
                ),
                CONSTRAINT ck_crop_pricing_values CHECK (
                    (pricing_mode = 'range' AND reference_price > 0
                     AND price_range >= 0 AND reference_price > price_range
                     AND minimum_price IS NULL AND maximum_price IS NULL) OR
                    (pricing_mode = 'bounds' AND minimum_price > 0
                     AND maximum_price >= minimum_price AND price_range IS NULL
                     AND (reference_price IS NULL OR reference_price BETWEEN
                          minimum_price AND maximum_price))
                )
            )
        """))
        connection.execute(text("INSERT INTO crops(id) VALUES (1)"))
        connection.execute(text("""
            INSERT INTO crop_pricing(
                crop_id, pricing_mode, price_unit, reference_price, price_range
            ) VALUES (1, 'range', 'piece', 48, 10)
        """))

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(
            text("SELECT price_unit FROM crop_pricing WHERE crop_id=1")
        ).scalar_one() == "kg"
        constraints = inspect(connection).get_check_constraints("crop_pricing")
        unit_constraint = next(
            constraint
            for constraint in constraints
            if constraint["name"] == "ck_crop_pricing_unit"
        )
        assert unit_constraint["sqltext"] == "price_unit = 'kg'"

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        constraints = inspect(connection).get_check_constraints("crop_pricing")
        unit_constraint = next(
            constraint
            for constraint in constraints
            if constraint["name"] == "ck_crop_pricing_unit"
        )
        assert "piece" in unit_constraint["sqltext"]

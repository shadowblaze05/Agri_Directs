import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "6f3b2a9c1d84_add_category_and_custom_price_units.py"
)
SPEC = importlib.util.spec_from_file_location("price_unit_migration", MIGRATION_PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_custom_price_unit_migration_removes_legacy_checks_and_migrates_defaults():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE commodity_categories (
                id INTEGER PRIMARY KEY, name TEXT, description TEXT
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE commodities (
                id INTEGER PRIMARY KEY,
                commodity_name TEXT,
                category_id INTEGER,
                default_price_unit TEXT NOT NULL DEFAULT 'kg'
                    CHECK (default_price_unit IN ('kg', 'pc', 'pack'))
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE commodity_pricing (
                commodity_id INTEGER PRIMARY KEY,
                price_unit TEXT NOT NULL DEFAULT 'kg'
                    CHECK (price_unit IN ('kg', 'pc', 'pack'))
            )
        """)
        connection.exec_driver_sql(
            "INSERT INTO commodity_categories VALUES (1, 'Cigarettes', NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO commodities VALUES (1, 'Cigar', 1, 'kg')"
        )
        connection.exec_driver_sql("INSERT INTO commodity_pricing VALUES (1, 'kg')")

        with Operations.context(MigrationContext.configure(connection)):
            MIGRATION.upgrade()

        assert connection.execute(
            text("SELECT default_price_unit FROM commodity_categories WHERE id=1")
        ).scalar_one() == "pack"
        assert connection.execute(
            text("SELECT default_price_unit FROM commodities WHERE id=1")
        ).scalar_one() == "pack"
        assert connection.execute(
            text("SELECT price_unit FROM commodity_pricing WHERE commodity_id=1")
        ).scalar_one() == "pack"

        for table_name, column_name in (
            ("commodities", "default_price_unit"),
            ("commodity_pricing", "price_unit"),
        ):
            assert not any(
                column_name in (constraint["sqltext"] or "").lower()
                for constraint in inspect(connection).get_check_constraints(table_name)
            )

        connection.execute(
            text("UPDATE commodities SET default_price_unit='sack' WHERE id=1")
        )
        connection.execute(
            text("UPDATE commodity_pricing SET price_unit='sack' WHERE commodity_id=1")
        )
        assert connection.execute(
            text("SELECT default_price_unit FROM commodities WHERE id=1")
        ).scalar_one() == "sack"

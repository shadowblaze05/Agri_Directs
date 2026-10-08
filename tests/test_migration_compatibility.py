import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"


def load_migration(filename):
    path = MIGRATIONS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def run_upgrade(connection, migration, monkeypatch):
    monkeypatch.setattr(
        migration,
        "op",
        Operations(MigrationContext.configure(connection)),
    )
    migration.upgrade()


def test_schema_ahead_of_revision_can_upgrade_without_duplicate_columns_or_data_loss(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, location TEXT, location_latitude FLOAT,
                location_longitude FLOAT, location_verified BOOLEAN NOT NULL DEFAULT 0,
                location_verified_at DATETIME, profile_photo_captured_at DATETIME,
                psgc_location VARCHAR(255), geotag_location VARCHAR(255)
            )
        """))
        connection.execute(text("""
            CREATE TABLE inventory (
                id INTEGER PRIMARY KEY, photo_path VARCHAR(255), latitude FLOAT,
                longitude FLOAT, capture_time DATETIME, distance_from_user FLOAT,
                verification_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                verification_notes TEXT, reviewed_by VARCHAR(128), reviewed_at DATETIME
            )
        """))
        connection.execute(text("""
            CREATE TABLE marketplace (
                id INTEGER PRIMARY KEY, main_image VARCHAR(255),
                thumbnail_verified INTEGER NOT NULL DEFAULT 0,
                thumbnail_latitude FLOAT, thumbnail_longitude FLOAT,
                thumbnail_distance_meters FLOAT, thumbnail_captured_at VARCHAR(32)
            )
        """))
        connection.execute(text(
            "INSERT INTO users (id, location, geotag_location) VALUES (1, 'Farm location', 'GPS label')"
        ))
        connection.execute(text(
            "INSERT INTO marketplace (id, main_image, thumbnail_verified) VALUES (1, 'listing.jpg', 0)"
        ))

        for filename in (
            "b72c946fa310_add_geotag_verification.py",
            "c84a1f6b2d90_add_separate_profile_location_labels.py",
            "4e2d91c7a6b8_verify_marketplace_thumbnails.py",
        ):
            run_upgrade(connection, load_migration(filename), monkeypatch)

        assert connection.execute(
            text("SELECT geotag_location FROM users WHERE id = 1")
        ).scalar_one() == "GPS label"
        assert connection.execute(
            text("SELECT main_image FROM marketplace WHERE id = 1")
        ).scalar_one() == "listing.jpg"

        inspector = inspect(connection)
        assert len({column["name"] for column in inspector.get_columns("users")}) == len(
            inspector.get_columns("users")
        )
        assert len({column["name"] for column in inspector.get_columns("inventory")}) == len(
            inspector.get_columns("inventory")
        )
        assert len({column["name"] for column in inspector.get_columns("marketplace")}) == len(
            inspector.get_columns("marketplace")
        )


def test_missing_legacy_columns_are_added_by_upgrade(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, location TEXT)"))
        connection.execute(text("CREATE TABLE inventory (id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE marketplace (id INTEGER PRIMARY KEY, main_image VARCHAR(255))"
        ))

        for filename in (
            "b72c946fa310_add_geotag_verification.py",
            "c84a1f6b2d90_add_separate_profile_location_labels.py",
            "4e2d91c7a6b8_verify_marketplace_thumbnails.py",
        ):
            run_upgrade(connection, load_migration(filename), monkeypatch)

        assert "location_latitude" in {
            column["name"] for column in inspect(connection).get_columns("users")
        }
        assert "photo_path" in {
            column["name"] for column in inspect(connection).get_columns("inventory")
        }
        assert "thumbnail_verified" in {
            column["name"] for column in inspect(connection).get_columns("marketplace")
        }


def test_pinned_update_and_notification_link_migration_is_repeatable(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration(
        "d6a1c8f9032b_add_pinned_updates_and_notification_links.py"
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE knowledge_posts (
                post_id INTEGER PRIMARY KEY, title TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY, username TEXT, title TEXT
            )
        """))

        run_upgrade(connection, migration, monkeypatch)
        run_upgrade(connection, migration, monkeypatch)

        knowledge_columns = {
            column["name"] for column in inspect(connection).get_columns("knowledge_posts")
        }
        notification_columns = {
            column["name"] for column in inspect(connection).get_columns("notifications")
        }
        assert "is_pinned" in knowledge_columns
        assert "link" in notification_columns

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.models.database import PostgreSQLCursor


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


def run_downgrade(connection, migration, monkeypatch):
    monkeypatch.setattr(
        migration,
        "op",
        Operations(MigrationContext.configure(connection)),
    )
    migration.downgrade()


def test_legacy_inventory_insert_rejects_invalid_column_names():
    cursor = PostgreSQLCursor()

    with pytest.raises(ValueError, match="invalid column names"):
        cursor.execute(
            "INSERT INTO inventory (crop_name, location; DROP TABLE users) VALUES (?, ?)",
            ("Wheat", "Farm"),
        )


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


def test_auth_version_migration_defaults_existing_users_to_zero(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration("cfe42a17b690_revoke_auth_on_password_change.py")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO users (id, username) VALUES (1, 'existing-user')"
        ))

        run_upgrade(connection, migration, monkeypatch)

        assert connection.execute(
            text("SELECT auth_version FROM users WHERE id=1")
        ).scalar_one() == 0
        connection.execute(
            text("INSERT INTO users (id, username) VALUES (2, 'new-user')")
        )
        assert connection.execute(
            text("SELECT auth_version FROM users WHERE id=2")
        ).scalar_one() == 0


def test_auth_version_migration_preserves_existing_column_and_repairs_nulls(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration("cfe42a17b690_revoke_auth_on_password_change.py")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                auth_version INTEGER
            )
        """))
        connection.execute(text(
            "INSERT INTO users (id, username, auth_version) "
            "VALUES (1, 'existing-user', NULL), (2, 'versioned-user', 4)"
        ))

        run_upgrade(connection, migration, monkeypatch)

        assert connection.execute(
            text("SELECT auth_version FROM users WHERE id=1")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT auth_version FROM users WHERE id=2")
        ).scalar_one() == 4


def test_profile_photo_privacy_migration_defaults_existing_photos_to_private(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration(
        "a9d2f3c7e601_profile_photo_privacy_challenges.py"
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(128) NOT NULL,
                profile_picture VARCHAR(255)
            )
        """))
        connection.execute(text(
            "INSERT INTO users (id, username, profile_picture) "
            "VALUES (1, 'existing-user', '/static/uploads/profiles/existing.jpg')"
        ))

        run_upgrade(connection, migration, monkeypatch)

        assert not bool(connection.execute(
            text("SELECT profile_picture_public FROM users WHERE id=1")
        ).scalar_one())
        connection.execute(
            text("INSERT INTO users (id, username) VALUES (2, 'new-user')")
        )
        assert not bool(connection.execute(
            text("SELECT profile_picture_public FROM users WHERE id=2")
        ).scalar_one())
        inspector = inspect(connection)
        assert "profile_photo_challenges" in inspector.get_table_names()
        assert "ix_profile_photo_challenges_user_expiry" in {
            index["name"]
            for index in inspector.get_indexes("profile_photo_challenges")
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


def test_delivery_address_migration_is_repeatable_for_legacy_marketplace_table(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration(
        "e41b7c2a9d50_add_marketplace_delivery_addresses.py"
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE marketplace (id INTEGER PRIMARY KEY)"))

        run_upgrade(connection, migration, monkeypatch)
        run_upgrade(connection, migration, monkeypatch)

        marketplace_columns = {
            column["name"] for column in inspect(connection).get_columns("marketplace")
        }
        assert {
            "delivery_province",
            "delivery_city",
            "delivery_barangay",
            "delivery_street",
            "delivery_landmark",
        } <= marketplace_columns


def test_profile_report_migration_creates_report_table_and_review_index(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration("8c4d2a71f6b3_add_profile_reports.py")
    with engine.begin() as connection:
        run_upgrade(connection, migration, monkeypatch)

        inspector = inspect(connection)
        report_columns = {
            column["name"] for column in inspector.get_columns("profile_reports")
        }
        report_indexes = {
            index["name"] for index in inspector.get_indexes("profile_reports")
        }
        assert {
            "reporter_username",
            "reported_username",
            "description",
            "status",
            "created_at",
            "reviewed_by",
            "reviewed_at",
        } <= report_columns
        assert "ix_profile_reports_status_created" in report_indexes


def test_profile_report_evidence_migration_can_be_rolled_back(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration("71a6d9c2e8f4_add_profile_report_evidence.py")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE profile_reports (id INTEGER PRIMARY KEY)"
        ))

        run_upgrade(connection, migration, monkeypatch)
        assert {
            "evidence_filename",
            "evidence_original_name",
        } <= {
            column["name"]
            for column in inspect(connection).get_columns("profile_reports")
        }

        run_downgrade(connection, migration, monkeypatch)
        assert {
            "evidence_filename",
            "evidence_original_name",
        }.isdisjoint({
            column["name"]
            for column in inspect(connection).get_columns("profile_reports")
        })


def test_face_scan_challenge_migration_adds_and_removes_stage_state(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration(
        "ce82a314fd17_face_scan_challenge_stages.py"
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE profile_photo_challenges (
                challenge_hash VARCHAR(64) PRIMARY KEY,
                username VARCHAR(128) NOT NULL,
                expires_at VARCHAR(40) NOT NULL,
                consumed_at VARCHAR(40),
                created_at VARCHAR(40) NOT NULL
            )
        """))
        connection.execute(text(
            "INSERT INTO profile_photo_challenges "
            "(challenge_hash, username, expires_at, created_at) "
            "VALUES ('hash', 'owner', 'later', 'now')"
        ))

        run_upgrade(connection, migration, monkeypatch)
        run_upgrade(connection, migration, monkeypatch)

        scan_columns = {
            column["name"]
            for column in inspect(connection).get_columns("profile_photo_challenges")
        }
        assert {
            "movement_sequence",
            "current_stage",
            "last_stage_at",
            "failed_attempts",
        } <= scan_columns
        assert connection.execute(text(
            "SELECT movement_sequence, current_stage, failed_attempts "
            "FROM profile_photo_challenges WHERE challenge_hash='hash'"
        )).one() == ("[]", 0, 0)

        run_downgrade(connection, migration, monkeypatch)
        remaining_columns = {
            column["name"]
            for column in inspect(connection).get_columns("profile_photo_challenges")
        }
        assert {
            "movement_sequence",
            "current_stage",
            "last_stage_at",
            "failed_attempts",
        }.isdisjoint(remaining_columns)


def test_profile_scan_verification_migration_preserves_existing_profile_data(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration(
        "c2f0a8e4d531_require_verified_profile_photo_scan.py"
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(128) NOT NULL,
                profile_picture VARCHAR(255),
                profile_photo_captured_at DATETIME
            )
        """))
        connection.execute(text("""
            INSERT INTO users (id, username, profile_picture)
            VALUES (1, 'owner', 'existing.jpg')
        """))

        run_upgrade(connection, migration, monkeypatch)
        run_upgrade(connection, migration, monkeypatch)
        user_columns = {
            column["name"] for column in inspect(connection).get_columns("users")
        }
        assert "profile_photo_scan_verified_at" in user_columns
        assert connection.execute(text(
            "SELECT profile_picture, profile_photo_scan_verified_at "
            "FROM users WHERE username='owner'"
        )).one() == ("existing.jpg", None)

        run_downgrade(connection, migration, monkeypatch)
        user_columns = {
            column["name"] for column in inspect(connection).get_columns("users")
        }
        assert "profile_photo_scan_verified_at" not in user_columns
        assert connection.execute(text(
            "SELECT profile_picture FROM users WHERE username='owner'"
        )).scalar_one() == "existing.jpg"

    engine.dispose()


def test_commodity_schema_migration_renames_tables_and_preserves_rows(monkeypatch):
    engine = create_engine("sqlite://")
    migration = load_migration(
        "df14a6c8b209_rename_crops_to_commodities.py"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(text("""
            CREATE TABLE crop_categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE crops (
                id INTEGER PRIMARY KEY,
                crops_name VARCHAR(128) NOT NULL,
                category_id INTEGER REFERENCES crop_categories(id)
            )
        """))
        connection.execute(text("""
            CREATE TABLE crop_pricing (
                crop_id INTEGER PRIMARY KEY REFERENCES crops(id),
                pricing_mode VARCHAR(16) NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE inventory (
                id INTEGER PRIMARY KEY,
                crop_id INTEGER REFERENCES crops(id),
                crop_name VARCHAR(128),
                quantity INTEGER
            )
        """))
        connection.execute(text("""
            CREATE TABLE harvest (
                id INTEGER PRIMARY KEY,
                crop_id INTEGER REFERENCES crops(id),
                quantity INTEGER
            )
        """))
        connection.execute(text("""
            CREATE TABLE marketplace (
                id INTEGER PRIMARY KEY,
                crop_id INTEGER REFERENCES crops(id),
                crop_name VARCHAR(128),
                amount INTEGER
            )
        """))
        connection.execute(text("""
            CREATE TABLE analytics (
                id INTEGER PRIMARY KEY,
                top_crop VARCHAR(128),
                top_crop_volume INTEGER,
                top_crop_id INTEGER REFERENCES crops(id)
            )
        """))
        connection.execute(text("INSERT INTO crop_categories VALUES (1, 'Grains')"))
        connection.execute(text("INSERT INTO crops VALUES (1, 'Rice', 1)"))
        connection.execute(text("INSERT INTO crop_pricing VALUES (1, 'range')"))
        connection.execute(text("INSERT INTO inventory VALUES (1, 1, 'Rice', 250)"))
        connection.execute(text("INSERT INTO harvest VALUES (1, 1, 250)"))
        connection.execute(text("INSERT INTO marketplace VALUES (1, 1, 'Rice', 100)"))
        connection.execute(text(
            "INSERT INTO analytics VALUES (1, 'Rice', 250, 1)"
        ))

        run_upgrade(connection, migration, monkeypatch)

        inspector = inspect(connection)
        assert {
            "commodities",
            "commodity_categories",
            "commodity_pricing",
        } <= set(inspector.get_table_names())
        assert {"commodity_id", "commodity_name"} <= {
            column["name"] for column in inspector.get_columns("inventory")
        }
        assert connection.execute(text(
            "SELECT commodity_name, category_id FROM commodities WHERE id=1"
        )).one() == ("Rice", 1)
        assert connection.execute(text(
            "SELECT commodity_id, commodity_name, quantity FROM inventory WHERE id=1"
        )).one() == (1, "Rice", 250)
        assert connection.execute(text(
            "SELECT commodity_id FROM harvest WHERE id=1"
        )).scalar_one() == 1
        assert connection.execute(text(
            "SELECT top_commodity, top_commodity_volume, top_commodity_id "
            "FROM analytics WHERE id=1"
        )).one() == ("Rice", 250, 1)
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []

        run_downgrade(connection, migration, monkeypatch)

        inspector = inspect(connection)
        assert {"crops", "crop_categories", "crop_pricing"} <= set(
            inspector.get_table_names()
        )
        assert {"crop_id", "crop_name"} <= {
            column["name"] for column in inspector.get_columns("inventory")
        }
        assert connection.execute(text(
            "SELECT crops_name FROM crops WHERE id=1"
        )).scalar_one() == "Rice"
        assert connection.execute(text(
            "SELECT crop_id, crop_name, quantity FROM inventory WHERE id=1"
        )).one() == (1, "Rice", 250)
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []

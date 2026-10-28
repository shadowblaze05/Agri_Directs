import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers

from app.extensions import db


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"


def load_migration():
    path = MIGRATIONS / "e7b6d2a93c41_reconcile_erd_relationships.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def load_expanded_user_migration():
    path = MIGRATIONS / "f2c8a6d9e413_expand_user_erd_relationships.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def run_migration(connection, migration, direction):
    migration.op = Operations(MigrationContext.configure(connection))
    getattr(migration, direction)()


def create_schema(connection):
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, location_verified INTEGER)")
    connection.exec_driver_sql("CREATE TABLE crops (id INTEGER PRIMARY KEY)")
    connection.exec_driver_sql("CREATE TABLE marketplace (id INTEGER PRIMARY KEY, crop_id INTEGER, user_id INTEGER)")
    connection.exec_driver_sql("CREATE TABLE knowledge_categories (category_id INTEGER PRIMARY KEY)")
    connection.exec_driver_sql("CREATE TABLE knowledge_posts (post_id INTEGER PRIMARY KEY, category_id INTEGER)")
    connection.exec_driver_sql("CREATE TABLE knowledge_likes (id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE knowledge_comments (comment_id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE knowledge_replies (reply_id INTEGER PRIMARY KEY, comment_id INTEGER NOT NULL)")
    connection.exec_driver_sql(
        "CREATE TABLE password_reset_tokens (id INTEGER PRIMARY KEY, user_id INTEGER, purpose TEXT, expires_at TEXT, used_at TEXT)"
    )
    connection.exec_driver_sql("CREATE TABLE audit_events (id INTEGER PRIMARY KEY, status_code INTEGER, method TEXT, occurred_at TEXT)")
    connection.exec_driver_sql(
        "CREATE TABLE profile_reports (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE listing_photo_location_alerts (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)"
    )

    connection.execute(text("INSERT INTO users (id, location_verified) VALUES (1, 0)"))
    connection.execute(text("INSERT INTO crops (id) VALUES (1)"))
    connection.execute(text("INSERT INTO marketplace (id, crop_id, user_id) VALUES (1, 1, NULL)"))
    connection.execute(text("INSERT INTO knowledge_categories (category_id) VALUES (1)"))
    connection.execute(text("INSERT INTO knowledge_posts (post_id, category_id) VALUES (1, 1)"))
    connection.execute(text("INSERT INTO knowledge_likes (id, post_id) VALUES (1, 1)"))
    connection.execute(text("INSERT INTO knowledge_comments (comment_id, post_id) VALUES (1, 1)"))
    connection.execute(text("INSERT INTO knowledge_replies (reply_id, comment_id) VALUES (1, 1)"))
    migration = load_migration()
    used_ids = {11, 12, 39, 41, 43}
    token_rows = []
    for token_id in sorted(migration._EXPECTED_TOKEN_IDS):
        purpose = migration._EXPECTED_TOKEN_PURPOSES[token_id]
        if token_id in used_ids:
            expiry = "2099-01-01T00:00:00+00:00"
            used_at = "2020-01-01T00:00:00+00:00"
        else:
            expiry = "2000-01-01T00:00:00+00:00"
            used_at = None
        token_rows.append(
            {
                "id": token_id,
                "purpose": purpose,
                "expiry": expiry,
                "used_at": used_at,
                "user_id": 99,
            }
        )
    token_rows.extend(
        [
            {
                "id": token_id,
                "purpose": "password_reset",
                "expiry": "2099-01-01T00:00:00+00:00",
                "used_at": None,
                "user_id": 1,
            }
            for token_id in (101, 102, 103)
        ]
    )
    connection.execute(
        text(
            "INSERT INTO password_reset_tokens "
            "(id, user_id, purpose, expires_at, used_at) "
            "VALUES (:id, :user_id, :purpose, :expiry, :used_at)"
        ),
        token_rows,
    )


def test_erd_reconciliation_is_the_single_alembic_head():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["f2c8a6d9e413"]


def test_expanded_relationship_migration_preserves_legacy_labels_and_covers_user_links():
    migration = load_expanded_user_migration()
    links = {
        (table, column, source, key)
        for table, column, source, key in migration._USER_LINKS
    }
    assert migration.down_revision == "e7b6d2a93c41"
    assert len(links) == 19
    assert {
        ("marketplace", "seller_user_id", "user_id", "id"),
        ("messages", "sender_user_id", "sender", "username"),
        ("messages", "recipient_user_id", "recipient", "username"),
        ("notifications", "user_id", "username", "username"),
        ("audit_events", "actor_user_id", "actor", "username"),
    } <= links
    assert migration._CROP_LINK == ("analytics", "top_crop_id", "crops", "id")
    assert migration._APPROVED_DATABASES == {
        "AgriDirect",
        "AgriDirect_erd_verify",
        "AgriDirect_erd_rollback_verify",
    }


def test_application_metadata_declares_expanded_clone_relationships():
    migration = load_expanded_user_migration()
    configure_mappers()
    expected = {
        (
            table_name,
            column_name,
            "users" if source_key in {"id", "username"} else source_key,
            "id",
            "SET NULL",
            migration._constraint_name(table_name, column_name),
        )
        for table_name, column_name, _source_column, source_key in migration._USER_LINKS
    }
    expected.add(
        (
            "analytics",
            "top_crop_id",
            "crops",
            "id",
            "SET NULL",
            "fk_analytics_top_crop_id_crops",
        )
    )

    actual = set()
    for table_name, column_name, _source_column, source_key in migration._USER_LINKS:
        table = db.metadata.tables[table_name]
        foreign_key = next(
            fk
            for fk in table.foreign_keys
            if fk.parent.name == column_name
        )
        actual.add(
            (
                table_name,
                column_name,
                foreign_key.column.table.name,
                foreign_key.column.name,
                foreign_key.ondelete,
                foreign_key.constraint.name,
            )
        )

    analytics_fk = next(
        fk
        for fk in db.metadata.tables["analytics"].foreign_keys
        if fk.parent.name == "top_crop_id"
    )
    actual.add(
        (
            "analytics",
            "top_crop_id",
            analytics_fk.column.table.name,
            analytics_fk.column.name,
            analytics_fk.ondelete,
            analytics_fk.constraint.name,
        )
    )
    assert actual == expected
    for table_name, column_name, _source_column, _source_key in migration._USER_LINKS:
        mapper = next(
            mapper
            for mapper in db.Model.registry.mappers
            if mapper.local_table.name == table_name
        )
        assert not mapper.attrs[column_name].deferred


def test_relationship_migration_cleans_only_inactive_orphan_tokens_and_enforces_foreign_keys():
    engine = create_engine("sqlite://")
    migration = load_migration()
    with engine.begin() as connection:
        create_schema(connection)
        run_migration(connection, migration, "upgrade")

        tokens = connection.execute(
            text("SELECT id FROM password_reset_tokens ORDER BY id")
        ).scalars().all()
        assert tokens == [101, 102, 103]

        inspector = inspect(connection)
        expected = {
            ("marketplace", "crop_id", "crops"),
            ("knowledge_posts", "category_id", "knowledge_categories"),
            ("knowledge_likes", "post_id", "knowledge_posts"),
            ("knowledge_comments", "post_id", "knowledge_posts"),
            ("knowledge_replies", "comment_id", "knowledge_comments"),
            ("password_reset_tokens", "user_id", "users"),
        }
        actual = {
            (
                table,
                foreign_key["constrained_columns"][0],
                foreign_key["referred_table"],
            )
            for table, _, _, _, _, _ in migration._FOREIGN_KEYS
            for foreign_key in inspector.get_foreign_keys(table)
        }
        assert expected <= actual
        actual_actions = {
            (table, foreign_key["constrained_columns"][0]): (
                foreign_key.get("options", {}).get("ondelete")
            )
            for table, *_ in migration._FOREIGN_KEYS
            for foreign_key in inspector.get_foreign_keys(table)
        }
        assert actual_actions == {
            ("marketplace", "crop_id"): "RESTRICT",
            ("knowledge_posts", "category_id"): "SET NULL",
            ("knowledge_likes", "post_id"): "CASCADE",
            ("knowledge_comments", "post_id"): "CASCADE",
            ("knowledge_replies", "comment_id"): "CASCADE",
            ("password_reset_tokens", "user_id"): "CASCADE",
        }
        assert not any(
            foreign_key["constrained_columns"] == ["user_id"]
            for foreign_key in inspector.get_foreign_keys("marketplace")
        )
        connection.execute(
            text(
                "INSERT INTO marketplace (id, crop_id, user_id) "
                "VALUES (2, 1, 999)"
            )
        )

        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text("INSERT INTO knowledge_likes (id, post_id) VALUES (2, 999)")
                )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(text("DELETE FROM crops WHERE id = 1"))

        connection.execute(
            text("DELETE FROM knowledge_categories WHERE category_id = 1")
        )
        assert connection.execute(
            text("SELECT category_id FROM knowledge_posts WHERE post_id = 1")
        ).scalar_one() is None

        connection.execute(text("DELETE FROM knowledge_posts WHERE post_id = 1"))
        assert connection.execute(
            text("SELECT count(*) FROM knowledge_likes")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT count(*) FROM knowledge_comments")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT count(*) FROM knowledge_replies")
        ).scalar_one() == 0
        connection.execute(text("DELETE FROM users WHERE id = 1"))
        assert connection.execute(
            text("SELECT count(*) FROM password_reset_tokens")
        ).scalar_one() == 0
        assert "ix_profile_reports_status_created" in {
            index["name"] for index in inspect(connection).get_indexes("profile_reports")
        }


def test_relationship_migration_refuses_to_delete_unexpired_orphan_tokens():
    engine = create_engine("sqlite://")
    migration = load_migration()
    with engine.begin() as connection:
        create_schema(connection)
        connection.execute(
            text(
                "UPDATE password_reset_tokens SET expires_at = "
                "'2099-01-01T00:00:00+00:00' WHERE id = 5"
            )
        )
        with pytest.raises(RuntimeError, match="still unexpired"):
            run_migration(connection, migration, "upgrade")
        assert connection.execute(
            text("SELECT count(*) FROM password_reset_tokens")
        ).scalar_one() == 26


def test_downgrade_removes_schema_constraints_but_does_not_restore_deleted_tokens():
    engine = create_engine("sqlite://")
    migration = load_migration()
    with engine.begin() as connection:
        create_schema(connection)
        run_migration(connection, migration, "upgrade")
        run_migration(connection, migration, "downgrade")

        for table, *_ in migration._FOREIGN_KEYS:
            assert inspect(connection).get_foreign_keys(table) == []
        assert connection.execute(
            text("SELECT count(*) FROM password_reset_tokens")
        ).scalar_one() == 3
        for table, index_name in (
            ("marketplace", "ix_marketplace_crop_id"),
            ("knowledge_likes", "ix_knowledge_likes_post_id"),
            ("profile_reports", "ix_profile_reports_status_created"),
            ("audit_events", "ix_audit_events_method_occurred"),
            ("audit_events", "ix_audit_events_status_occurred"),
        ):
            assert index_name not in {
                index["name"] for index in inspect(connection).get_indexes(table)
            }

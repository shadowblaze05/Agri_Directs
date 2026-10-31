"""Reconcile verified schema drift and add missing ERD foreign keys."""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "e7b6d2a93c41"
down_revision = ("8c4d2a71f6b3", "c1d9e4f7a2b6")
branch_labels = None
depends_on = None


_FOREIGN_KEYS = (
    (
        "marketplace",
        "fk_marketplace_crop_id_crops",
        "crops",
        ["crop_id"],
        ["id"],
        "RESTRICT",
    ),
    (
        "knowledge_posts",
        "fk_knowledge_posts_category_id_knowledge_categories",
        "knowledge_categories",
        ["category_id"],
        ["category_id"],
        "SET NULL",
    ),
    (
        "knowledge_likes",
        "fk_knowledge_likes_post_id_knowledge_posts",
        "knowledge_posts",
        ["post_id"],
        ["post_id"],
        "CASCADE",
    ),
    (
        "knowledge_comments",
        "fk_knowledge_comments_post_id_knowledge_posts",
        "knowledge_posts",
        ["post_id"],
        ["post_id"],
        "CASCADE",
    ),
    (
        "knowledge_replies",
        "fk_knowledge_replies_comment_id_knowledge_comments",
        "knowledge_comments",
        ["comment_id"],
        ["comment_id"],
        "CASCADE",
    ),
    (
        "password_reset_tokens",
        "fk_password_reset_tokens_user_id_users",
        "users",
        ["user_id"],
        ["id"],
        "CASCADE",
    ),
)

_TEXT_TO_VARCHAR = (
    ("inventory", "photo_path", 255),
    ("inventory", "verification_status", 32),
    ("inventory", "reviewed_by", 128),
    ("slow_query_stats", "fingerprint", 64),
    ("marketplace", "thumbnail_captured_at", 32),
    ("marketplace", "delivery_province", 255),
    ("marketplace", "delivery_city", 255),
    ("marketplace", "delivery_barangay", 255),
    ("marketplace", "delivery_street", 255),
    ("marketplace", "delivery_landmark", 255),
    ("messages", "attachment_type", 16),
    ("profile_reports", "reporter_username", 128),
    ("profile_reports", "reported_username", 128),
    ("profile_reports", "status", 24),
    ("profile_reports", "reviewed_by", 128),
    ("listing_photo_location_alerts", "username", 128),
    ("listing_photo_location_alerts", "thumbnail_captured_at", 32),
    ("listing_photo_location_alerts", "status", 24),
    ("listing_photo_location_alerts", "reviewed_by", 128),
)

_TEXT_COLUMN_NULLABILITY = {
    ("inventory", "photo_path"): True,
    ("inventory", "verification_status"): False,
    ("inventory", "reviewed_by"): True,
    ("slow_query_stats", "fingerprint"): False,
    ("marketplace", "thumbnail_captured_at"): True,
    ("marketplace", "delivery_province"): True,
    ("marketplace", "delivery_city"): True,
    ("marketplace", "delivery_barangay"): True,
    ("marketplace", "delivery_street"): True,
    ("marketplace", "delivery_landmark"): True,
    ("messages", "attachment_type"): True,
    ("profile_reports", "reporter_username"): False,
    ("profile_reports", "reported_username"): False,
    ("profile_reports", "status"): False,
    ("profile_reports", "reviewed_by"): True,
    ("listing_photo_location_alerts", "username"): False,
    ("listing_photo_location_alerts", "thumbnail_captured_at"): False,
    ("listing_photo_location_alerts", "status"): False,
    ("listing_photo_location_alerts", "reviewed_by"): True,
}

_AUDIT_INDEXES = (
    ("ix_audit_events_status_occurred", ["status_code", "occurred_at"]),
    ("ix_audit_events_method_occurred", ["method", "occurred_at"]),
)

_NEW_INDEXES = {
    "ix_marketplace_crop_id": ("marketplace", ["crop_id"]),
    "ix_knowledge_likes_post_id": ("knowledge_likes", ["post_id"]),
}

_EXPECTED_PARENT_HEADS = {"8c4d2a71f6b3", "c1d9e4f7a2b6"}
_EXPECTED_PRE_STAMP_REVISION = {"a81f4c6e2b90"}
_APPROVED_DATABASES = {
    "AgriDirect",
    "AgriDirect_erd_verify",
    "AgriDirect_erd_rollback_verify",
}
_EXPECTED_TOKEN_IDS = {
    1, 5, 7, 11, 12, 13, 15, 17, 18, 21, 22, 23, 26,
    28, 29, 30, 32, 35, 38, 39, 41, 42, 43,
}
_EXPECTED_USED_TOKEN_IDS = {11, 12, 39, 41, 43}
_EXPECTED_ORPHAN_LISTING_IDS = set(range(1, 10))
_EXPECTED_TOKEN_PURPOSES = {
    1: "password_reset",
    5: "password_reset",
    7: "password_reset",
    11: "password_reset",
    12: "email_verification",
    13: "email_verification",
    15: "email_verification",
    17: "email_verification",
    18: "email_verification",
    21: "email_verification",
    22: "email_verification",
    23: "email_verification",
    26: "password_reset",
    28: "email_verification",
    29: "email_verification",
    30: "email_verification",
    32: "email_verification",
    35: "email_verification",
    38: "email_verification",
    39: "email_verification",
    41: "password_reset",
    42: "email_verification",
    43: "email_verification",
}

_PARENT_INDEXES = {
    "ix_users_email": ["email"],
    "ix_marketplace_status_listing_date": ["status", "listing_date"],
    "ix_marketplace_user_status_listing_date": ["user_id", "status", "listing_date"],
    "ix_marketplace_buyer_status_order_date": ["buyer_username", "status", "order_date"],
    "ix_marketplace_username_rating": ["username", "buyer_rating"],
    "ix_marketplace_status_type_listing_date": ["status", "listing_type", "listing_date"],
    "ix_inventory_farmer_crop_date": ["farmer", "crop_id", "date_received"],
    "ix_inventory_crop_date": ["crop_id", "date_received"],
    "ix_inventory_source_date": ["source", "date_received"],
    "ix_knowledge_posts_status_pin_created": ["status", "is_pinned", "created_at"],
    "ix_knowledge_posts_category_status_created": ["category_id", "status", "created_at"],
    "ix_knowledge_comments_post_created": ["post_id", "created_at"],
    "ix_knowledge_replies_comment_created": ["comment_id", "created_at"],
    "ix_notifications_username_read_created": ["username", "is_read", "created_at"],
    "ix_messages_sender_recipient_time": ["sender", "recipient", "timestamp"],
    "ix_messages_recipient_sender_time": ["recipient", "sender", "timestamp"],
    "ix_password_reset_user_used_expiry": ["user_id", "used_at", "expires_at"],
    "ix_marketplace_images_listing": ["listing_id"],
    "ix_cart_user_listing": ["user_id", "listing_id"],
    "ix_analytics_period_type_value": ["period_type", "period_value"],
    "ix_audit_events_status_occurred": ["status_code", "occurred_at"],
    "ix_audit_events_method_occurred": ["method", "occurred_at"],
    "ix_profile_reports_status_created": ["status", "created_at"],
    "ix_listing_photo_alerts_status_created": ["status", "created_at"],
}

_PARENT_INDEX_TABLES = {
    "ix_users_email": "users",
    "ix_marketplace_status_listing_date": "marketplace",
    "ix_marketplace_user_status_listing_date": "marketplace",
    "ix_marketplace_buyer_status_order_date": "marketplace",
    "ix_marketplace_username_rating": "marketplace",
    "ix_marketplace_status_type_listing_date": "marketplace",
    "ix_inventory_farmer_crop_date": "inventory",
    "ix_inventory_crop_date": "inventory",
    "ix_inventory_source_date": "inventory",
    "ix_knowledge_posts_status_pin_created": "knowledge_posts",
    "ix_knowledge_posts_category_status_created": "knowledge_posts",
    "ix_knowledge_comments_post_created": "knowledge_comments",
    "ix_knowledge_replies_comment_created": "knowledge_replies",
    "ix_notifications_username_read_created": "notifications",
    "ix_messages_sender_recipient_time": "messages",
    "ix_messages_recipient_sender_time": "messages",
    "ix_password_reset_user_used_expiry": "password_reset_tokens",
    "ix_marketplace_images_listing": "marketplace_images",
    "ix_cart_user_listing": "cart",
    "ix_analytics_period_type_value": "analytics",
    "ix_audit_events_status_occurred": "audit_events",
    "ix_audit_events_method_occurred": "audit_events",
    "ix_profile_reports_status_created": "profile_reports",
    "ix_listing_photo_alerts_status_created": "listing_photo_location_alerts",
}

_PARENT_TABLE_COLUMNS = {
    "knowledge_posts": {
        "is_pinned": (("INTEGER",), False),
    },
    "notifications": {
        "link": (("TEXT",), True),
    },
    "marketplace": {
        "delivery_province": (("TEXT", "VARCHAR(255)"), True),
        "delivery_city": (("TEXT", "VARCHAR(255)"), True),
        "delivery_barangay": (("TEXT", "VARCHAR(255)"), True),
        "delivery_street": (("TEXT", "VARCHAR(255)"), True),
        "delivery_landmark": (("TEXT", "VARCHAR(255)"), True),
    },
    "slow_query_stats": {
        "fingerprint": (("TEXT", "VARCHAR(64)"), False),
        "statement": (("TEXT",), False),
        "call_count": (("INTEGER",), False),
        "total_time_ms": (("DOUBLE PRECISION", "FLOAT"), False),
        "max_time_ms": (("DOUBLE PRECISION", "FLOAT"), False),
        "last_seen_at": (("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"), False),
    },
    "profile_reports": {
        "id": (("INTEGER",), False),
        "reporter_username": (("TEXT", "VARCHAR(128)"), False),
        "reported_username": (("TEXT", "VARCHAR(128)"), False),
        "description": (("TEXT",), False),
        "status": (("TEXT", "VARCHAR(24)"), False),
        "created_at": (("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"), False),
        "reviewed_by": (("TEXT", "VARCHAR(128)"), True),
        "reviewed_at": (("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"), True),
    },
    "listing_photo_location_alerts": {
        "id": (("INTEGER",), False),
        "username": (("TEXT", "VARCHAR(128)"), False),
        "distance_meters": (("REAL", "FLOAT"), False),
        "thumbnail_captured_at": (("TEXT", "VARCHAR(32)"), False),
        "status": (("TEXT", "VARCHAR(24)"), False),
        "created_at": (("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"), False),
        "reviewed_by": (("TEXT", "VARCHAR(128)"), True),
        "reviewed_at": (("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP"), True),
    },
}

_PARENT_PRIMARY_KEYS = {
    "slow_query_stats": ["fingerprint"],
    "profile_reports": ["id"],
    "listing_photo_location_alerts": ["id"],
}

_CORE_FOREIGN_KEYS = (
    ("cart", ["listing_id"], "marketplace", ["id"], "CASCADE"),
    ("cart", ["user_id"], "users", ["id"], "CASCADE"),
    ("marketplace_images", ["listing_id"], "marketplace", ["id"], "CASCADE"),
    ("crops", ["category_id"], "crop_categories", ["id"], None),
    ("harvest", ["crop_id"], "crops", ["id"], None),
    ("inventory", ["crop_id"], "crops", ["id"], None),
)

_KNOWN_MISSING_PARENT_INDEXES = {
    "ix_audit_events_status_occurred",
    "ix_audit_events_method_occurred",
    "ix_profile_reports_status_created",
}


def _require_postgresql_type(inspector, table_name, column_name, allowed_types, nullable):
    column = next(
        (
            item
            for item in inspector.get_columns(table_name)
            if item["name"] == column_name
        ),
        None,
    )
    if column is None:
        raise RuntimeError(f"Required column {table_name}.{column_name} is missing.")
    actual_type = str(column["type"]).upper()
    if actual_type not in allowed_types or column["nullable"] != nullable:
        raise RuntimeError(
            f"Unexpected definition for {table_name}.{column_name}: "
            f"type={actual_type}, nullable={column['nullable']}."
        )
    return column


def _require_primary_key(inspector, table_name, expected_columns):
    actual = inspector.get_pk_constraint(table_name).get("constrained_columns")
    if actual != expected_columns:
        raise RuntimeError(
            f"Unexpected primary key on {table_name}: {actual!r}; "
            f"expected {expected_columns!r}."
        )


def _require_unique_constraint(inspector, table_name, expected_columns):
    constraints = inspector.get_unique_constraints(table_name)
    indexes = inspector.get_indexes(table_name)
    if not any(
        constraint.get("column_names") == expected_columns
        for constraint in constraints
    ) and not any(
        index.get("unique")
        and index.get("column_names") == expected_columns
        for index in indexes
    ):
        raise RuntimeError(
            f"Required unique key is missing on {table_name}{expected_columns!r}."
        )


def _require_foreign_key(inspector, table_name, columns, referred_table, referred_columns, ondelete):
    matches = [
        foreign_key
        for foreign_key in inspector.get_foreign_keys(table_name)
        if foreign_key.get("constrained_columns") == columns
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one foreign key on {table_name}{columns!r}; "
            f"found {len(matches)}."
        )
    foreign_key = matches[0]
    actual_ondelete = foreign_key.get("options", {}).get("ondelete")
    if (
        foreign_key.get("referred_table") != referred_table
        or foreign_key.get("referred_columns") != referred_columns
        or (actual_ondelete or "").upper() != (ondelete or "").upper()
    ):
        raise RuntimeError(
            f"Unexpected foreign key on {table_name}{columns!r}: "
            f"{foreign_key!r}."
        )


def _require_parent_indexes(connection, inspector):
    found = {}
    for table_name in set(_PARENT_INDEX_TABLES.values()):
        for index in inspector.get_indexes(table_name):
            found[index["name"]] = index

    unexpected_missing = set(_PARENT_INDEXES) - set(found) - _KNOWN_MISSING_PARENT_INDEXES
    if unexpected_missing:
        raise RuntimeError(
            "Parent migration index preflight failed; unexpected indexes are "
            f"missing: {sorted(unexpected_missing)!r}."
        )
    known_present = set(_KNOWN_MISSING_PARENT_INDEXES) & set(found)
    if known_present:
        raise RuntimeError(
            "Parent schema differs from the reviewed snapshot; indexes expected "
            f"to be repaired are already present: {sorted(known_present)!r}."
        )

    for index_name, columns in _PARENT_INDEXES.items():
        index = found.get(index_name)
        if index is None:
            continue
        if index.get("column_names") != columns or index.get("unique"):
            raise RuntimeError(
                f"Unexpected definition for parent index {index_name}: {index!r}."
            )

    expression_index = connection.execute(
        sa.text(
            """
            SELECT pg_get_expr(indexprs, indrelid)
            FROM pg_index
            WHERE indexrelid = to_regclass('public.ix_users_lower_email')
            """
        )
    ).scalar_one_or_none()
    if expression_index not in {"lower((email)::text)", "lower(email)"}:
        raise RuntimeError(
            "Parent migration expression index ix_users_lower_email is missing "
            "or has an unexpected definition."
        )


def _require_server_default(inspector, table_name, column_name, expected_fragment):
    column = next(
        item
        for item in inspector.get_columns(table_name)
        if item["name"] == column_name
    )
    actual = str(column.get("default") or "").lower().replace(" ", "")
    if expected_fragment not in actual:
        raise RuntimeError(
            f"Unexpected server default for {table_name}.{column_name}: "
            f"{column.get('default')!r}."
        )


def _preflight_parent_schema(connection, expected_heads=_EXPECTED_PARENT_HEADS):
    inspector = sa.inspect(connection)
    required_tables = set(_PARENT_TABLE_COLUMNS) | set(_PARENT_INDEX_TABLES.values())
    required_tables |= {
        "alembic_version",
        "users",
        "crops",
        "crop_categories",
        "harvest",
        "inventory",
        "cart",
        "marketplace_images",
        "analytics",
        "knowledge_categories",
        "knowledge_likes",
        "knowledge_comments",
        "knowledge_replies",
        "password_reset_tokens",
        "messages",
        "audit_events",
    }
    _require_tables(inspector, required_tables)

    versions = set(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != expected_heads:
        raise RuntimeError(
            "Unexpected Alembic revision state during reconciliation preflight; "
            f"found {sorted(versions)!r}."
        )

    for table_name, columns in _PARENT_TABLE_COLUMNS.items():
        actual_names = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing = set(columns) - actual_names
        if missing:
            raise RuntimeError(
                f"Parent schema columns are missing from {table_name}: "
                f"{sorted(missing)!r}."
            )
        for column_name, (allowed_types, nullable) in columns.items():
            _require_postgresql_type(
                inspector,
                table_name,
                column_name,
                allowed_types,
                nullable,
            )

    for table_name, column_name, default in (
        ("knowledge_posts", "is_pinned", "0"),
        ("slow_query_stats", "call_count", "0"),
        ("slow_query_stats", "total_time_ms", "0"),
        ("slow_query_stats", "max_time_ms", "0"),
        ("profile_reports", "status", "open"),
        ("profile_reports", "created_at", "current_timestamp"),
        ("listing_photo_location_alerts", "status", "open"),
        ("listing_photo_location_alerts", "created_at", "current_timestamp"),
    ):
        _require_server_default(inspector, table_name, column_name, default)

    for table_name, columns in _PARENT_PRIMARY_KEYS.items():
        _require_primary_key(inspector, table_name, columns)

    for table_name, column_name, length in _TEXT_TO_VARCHAR:
        column = _require_postgresql_type(
            inspector,
            table_name,
            column_name,
            ("TEXT", f"VARCHAR({length})"),
            _TEXT_COLUMN_NULLABILITY[(table_name, column_name)],
        )
        if isinstance(column["type"], sa.Text):
            too_long = connection.execute(
                sa.text(
                    f"SELECT count(*) FROM {table_name} "
                    f"WHERE {column_name} IS NOT NULL "
                    f"AND length({column_name}) > :length"
                ),
                {"length": length},
            ).scalar_one()
            if too_long:
                raise RuntimeError(
                    f"{table_name}.{column_name} contains {too_long} value(s) "
                    f"longer than VARCHAR({length})."
                )

    location_verified = _require_postgresql_type(
        inspector,
        "users",
        "location_verified",
        ("INTEGER", "BOOLEAN"),
        False,
    )
    if isinstance(location_verified["type"], sa.Integer):
        invalid_flags = connection.execute(
            sa.text(
                "SELECT count(*) FROM users "
                "WHERE location_verified IS NULL OR location_verified NOT IN (0, 1)"
            )
        ).scalar_one()
        if invalid_flags:
            raise RuntimeError(
                "users.location_verified contains null or non-boolean integer values."
            )

    _require_primary_key(inspector, "users", ["id"])
    _require_primary_key(inspector, "crops", ["id"])
    _require_primary_key(inspector, "crop_categories", ["id"])
    _require_primary_key(inspector, "knowledge_categories", ["category_id"])
    _require_primary_key(inspector, "knowledge_posts", ["post_id"])
    _require_primary_key(inspector, "knowledge_likes", ["id"])
    _require_primary_key(inspector, "knowledge_comments", ["comment_id"])
    _require_primary_key(inspector, "knowledge_replies", ["reply_id"])
    _require_primary_key(inspector, "marketplace", ["id"])
    _require_primary_key(inspector, "password_reset_tokens", ["id"])
    _require_primary_key(inspector, "audit_events", ["id"])
    for table_name, column_name in (
        ("users", "username"),
        ("users", "email"),
        ("crops", "crops_name"),
        ("crop_categories", "name"),
        ("knowledge_categories", "category_name"),
        ("password_reset_tokens", "token"),
    ):
        _require_unique_constraint(inspector, table_name, [column_name])

    for table_name, columns, referred_table, referred_columns, ondelete in _CORE_FOREIGN_KEYS:
        _require_foreign_key(
            inspector,
            table_name,
            columns,
            referred_table,
            referred_columns,
            ondelete,
        )

    for table_name, constraint_name, referred_table, columns, referred_columns, ondelete in _FOREIGN_KEYS:
        matches = [
            foreign_key
            for foreign_key in inspector.get_foreign_keys(table_name)
            if foreign_key.get("constrained_columns") == columns
        ]
        unexpected_matches = [
            foreign_key
            for foreign_key in matches
            if (
                foreign_key.get("referred_table") != referred_table
                or foreign_key.get("referred_columns") != referred_columns
            )
        ]
        if unexpected_matches:
            raise RuntimeError(
                f"Foreign key preflight found an existing constraint on "
                f"{table_name}{columns!r}; review it before applying this migration."
            )

    for index_name, (table_name, _columns) in _NEW_INDEXES.items():
        if index_name in {
            index["name"] for index in inspector.get_indexes(table_name)
        }:
            raise RuntimeError(
                f"Index {index_name} already exists; review it before applying "
                "this migration."
            )

    marketplace_user_id = next(
        column
        for column in inspector.get_columns("marketplace")
        if column["name"] == "user_id"
    )
    if not marketplace_user_id["nullable"] or any(
        foreign_key.get("constrained_columns") == ["user_id"]
        for foreign_key in inspector.get_foreign_keys("marketplace")
    ):
        raise RuntimeError(
            "marketplace.user_id must remain nullable and unconstrained until "
            "orphaned seller ownership is resolved."
        )
    orphan_listing_ids = set(
        connection.execute(
            sa.text(
                """
                SELECT id
                FROM marketplace
                WHERE user_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM users WHERE users.id = marketplace.user_id
                  )
                ORDER BY id
                """
            )
        ).scalars()
    )
    if orphan_listing_ids != _EXPECTED_ORPHAN_LISTING_IDS:
        raise RuntimeError(
            "Marketplace seller preflight failed; orphan listing IDs differ "
            f"from the reviewed set (found {sorted(orphan_listing_ids)!r})."
        )

    _require_parent_indexes(connection, inspector)


def _require_tables(inspector, required_tables):
    missing = sorted(set(required_tables) - set(inspector.get_table_names()))
    if missing:
        raise RuntimeError(
            "Cannot reconcile Alembic heads: verified branch schema is missing "
            f"tables {missing!r}. Restore the schema before applying this revision."
        )


def _assert_no_orphans(connection, source_table, source_column, target_table, target_column):
    count = connection.execute(
        sa.text(
            f"SELECT count(*) FROM {source_table} AS source "
            f"LEFT JOIN {target_table} AS target "
            f"ON target.{target_column} = source.{source_column} "
            f"WHERE source.{source_column} IS NOT NULL AND target.{target_column} IS NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot add {source_table}.{source_column} foreign key: "
            f"{count} orphaned row(s) reference {target_table}.{target_column}."
        )


def _validate_orphan_reset_tokens(connection):
    bind_names = [f"id_{index}" for index in range(len(_EXPECTED_TOKEN_IDS))]
    parameters = {
        name: token_id
        for name, token_id in zip(bind_names, sorted(_EXPECTED_TOKEN_IDS))
    }
    placeholders = ", ".join(f":{name}" for name in bind_names)
    lock_clause = " FOR UPDATE" if connection.dialect.name == "postgresql" else ""
    rows = connection.execute(
        sa.text(
            f"""
            SELECT id, purpose, expires_at, used_at, user_id
            FROM password_reset_tokens
            WHERE id IN ({placeholders})
            ORDER BY id{lock_clause}
            """
        ),
        parameters,
    ).all()
    actual_ids = {row.id for row in rows}
    if actual_ids != _EXPECTED_TOKEN_IDS:
        raise RuntimeError(
            "Reset-token cleanup preflight failed: candidate IDs differ from the "
            f"reviewed set (found {sorted(actual_ids)!r})."
        )

    all_orphan_ids = set(
        connection.execute(
            sa.text(
                """
                SELECT id
                FROM password_reset_tokens AS tokens
                WHERE NOT EXISTS (
                    SELECT 1 FROM users WHERE users.id = tokens.user_id
                )
                ORDER BY id
                """
            )
        ).scalars()
    )
    if all_orphan_ids != _EXPECTED_TOKEN_IDS:
        raise RuntimeError(
            "Reset-token cleanup preflight failed: orphan IDs differ from the "
            f"reviewed set (found {sorted(all_orphan_ids)!r})."
        )

    now = datetime.now(timezone.utc)
    for token_id, purpose, expires_at, used_at, user_id in rows:
        if user_id is None or purpose != _EXPECTED_TOKEN_PURPOSES[token_id]:
            raise RuntimeError(
                f"Reset-token cleanup preflight failed for row {token_id}: "
                "owner or purpose differs from the reviewed snapshot."
            )
        if token_id in _EXPECTED_USED_TOKEN_IDS:
            if used_at is None:
                raise RuntimeError(
                    f"Reset-token cleanup preflight failed: row {token_id} "
                    "is no longer marked used."
                )
            continue
        if used_at is not None:
            raise RuntimeError(
                f"Reset-token cleanup preflight failed: row {token_id} has an "
                "unexpected used status."
            )
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                "Cannot clean orphan password-reset tokens: token row "
                f"{token_id} has no safely parseable expiry."
            ) from error
        if expiry > now:
            raise RuntimeError(
                "Cannot clean orphan password-reset tokens: token row "
                f"{token_id} is still unexpired."
            )
    return sorted(_EXPECTED_TOKEN_IDS)


def _add_foreign_key(table_name, constraint_name, referred_table, columns, referred_columns, ondelete):
    inspector = sa.inspect(op.get_bind())
    foreign_keys = inspector.get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        same_definition = (
            foreign_key.get("constrained_columns") == columns
            and foreign_key.get("referred_table") == referred_table
            and foreign_key.get("referred_columns") == referred_columns
            and foreign_key.get("options", {}).get("ondelete", "").upper() == ondelete
        )
        if same_definition:
            return
        same_relationship = (
            foreign_key.get("constrained_columns") == columns
            and foreign_key.get("referred_table") == referred_table
            and foreign_key.get("referred_columns") == referred_columns
        )
        if same_relationship and foreign_key.get("name") is not None:
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(
                    foreign_key["name"],
                    type_="foreignkey",
                )
            continue
        if (
            foreign_key.get("name") == constraint_name
            or foreign_key.get("constrained_columns") == columns
        ):
            raise RuntimeError(
                f"Constraint {constraint_name} exists with a different definition."
            )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.create_foreign_key(
            constraint_name,
            referred_table,
            columns,
            referred_columns,
            ondelete=ondelete,
        )


def _alter_text_columns_to_varchar(connection):
    if connection.dialect.name != "postgresql":
        return
    inspector = sa.inspect(connection)
    for table_name, column_name, length in _TEXT_TO_VARCHAR:
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        column = columns.get(column_name)
        if column is None:
            raise RuntimeError(
                f"Cannot reconcile schema: {table_name}.{column_name} is missing."
            )
        if isinstance(column["type"], sa.String) and column["type"].length == length:
            continue
        if not isinstance(column["type"], sa.Text):
            raise RuntimeError(
                f"Cannot reconcile schema: {table_name}.{column_name} has unexpected "
                f"type {column['type']}."
            )
        too_long = connection.execute(
            sa.text(
                f"SELECT count(*) FROM {table_name} "
                f"WHERE {column_name} IS NOT NULL AND length({column_name}) > :length"
            ),
            {"length": length},
        ).scalar_one()
        if too_long:
            raise RuntimeError(
                f"Cannot convert {table_name}.{column_name} to VARCHAR({length}): "
                f"{too_long} value(s) exceed the target length."
            )
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Text(),
            type_=sa.String(length=length),
            existing_nullable=_TEXT_COLUMN_NULLABILITY[(table_name, column_name)],
        )
        inspector = sa.inspect(connection)


def _ensure_audit_indexes():
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {
        index["name"] for index in inspector.get_indexes("audit_events")
    }
    for name, columns in _AUDIT_INDEXES:
        if name not in existing_indexes:
            op.create_index(name, "audit_events", columns)


def _ensure_parent_indexes():
    inspector = sa.inspect(op.get_bind())
    for name in sorted(_KNOWN_MISSING_PARENT_INDEXES):
        table_name = (
            _PARENT_INDEX_TABLES[name]
        )
        existing = {
            index["name"] for index in inspector.get_indexes(table_name)
        }
        if name not in existing:
            op.create_index(name, table_name, _PARENT_INDEXES[name])


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if connection.dialect.name == "postgresql":
        current_database = connection.execute(
            sa.text("SELECT current_database()")
        ).scalar_one()
        if current_database not in _APPROVED_DATABASES:
            raise RuntimeError(
                "This reviewed reconciliation is approved only for AgriDirect "
                "and its named verification clones."
            )
    _require_tables(
        inspector,
        {
            "users",
            "marketplace",
            "crops",
            "knowledge_categories",
            "knowledge_posts",
            "knowledge_likes",
            "knowledge_comments",
            "knowledge_replies",
            "password_reset_tokens",
            "audit_events",
        },
    )
    if connection.dialect.name == "postgresql":
        _preflight_parent_schema(connection)

    for table_name, column_name, nullable in (
        ("marketplace", "crop_id", True),
        ("knowledge_posts", "category_id", True),
        ("knowledge_likes", "post_id", False),
        ("knowledge_comments", "post_id", False),
        ("knowledge_replies", "comment_id", False),
        ("password_reset_tokens", "user_id", True),
    ):
        _require_postgresql_type(
            inspector,
            table_name,
            column_name,
            ("INTEGER",),
            nullable,
        )

    for source_table, source_column, target_table, target_column in (
        ("marketplace", "crop_id", "crops", "id"),
        (
            "knowledge_posts",
            "category_id",
            "knowledge_categories",
            "category_id",
        ),
        ("knowledge_likes", "post_id", "knowledge_posts", "post_id"),
        ("knowledge_comments", "post_id", "knowledge_posts", "post_id"),
        ("knowledge_replies", "comment_id", "knowledge_comments", "comment_id"),
    ):
        _assert_no_orphans(
            connection,
            source_table,
            source_column,
            target_table,
            target_column,
        )

    candidate_token_ids = _validate_orphan_reset_tokens(connection)
    token_bind_names = [
        f"id_{index}" for index in range(len(candidate_token_ids))
    ]
    token_parameters = {
        name: token_id
        for name, token_id in zip(token_bind_names, candidate_token_ids)
    }
    token_placeholders = ", ".join(f":{name}" for name in token_bind_names)
    deleted_tokens = connection.execute(
        sa.text(
            f"""
            DELETE FROM password_reset_tokens AS tokens
            WHERE tokens.id IN ({token_placeholders})
              AND NOT EXISTS (
                SELECT 1 FROM users WHERE users.id = tokens.user_id
            )
            """
        ),
        token_parameters,
    ).rowcount
    if deleted_tokens != len(_EXPECTED_TOKEN_IDS):
        raise RuntimeError(
            "Reset-token cleanup deleted an unexpected number of rows: "
            f"expected {len(_EXPECTED_TOKEN_IDS)}, deleted {deleted_tokens}."
        )

    if connection.dialect.name == "postgresql":
        invalid_location_flags = connection.execute(
            sa.text(
                "SELECT count(*) FROM users "
                "WHERE location_verified NOT IN (0, 1)"
            )
        ).scalar_one()
        if invalid_location_flags:
            raise RuntimeError(
                "Cannot convert users.location_verified to BOOLEAN: "
                f"{invalid_location_flags} value(s) are not 0 or 1."
            )
        location_verified = next(
            column
            for column in inspector.get_columns("users")
            if column["name"] == "location_verified"
        )
        if isinstance(location_verified["type"], sa.Integer):
            op.execute(
                "ALTER TABLE users ALTER COLUMN location_verified DROP DEFAULT"
            )
            op.execute(
                "ALTER TABLE users ALTER COLUMN location_verified TYPE BOOLEAN "
                "USING CASE WHEN location_verified = 1 THEN TRUE ELSE FALSE END"
            )
            op.execute(
                "ALTER TABLE users ALTER COLUMN location_verified SET DEFAULT FALSE"
            )
        _alter_text_columns_to_varchar(connection)

    for table_name, constraint_name, referred_table, columns, referred_columns, ondelete in _FOREIGN_KEYS:
        _add_foreign_key(
            table_name,
            constraint_name,
            referred_table,
            columns,
            referred_columns,
            ondelete,
        )

    inspector = sa.inspect(connection)
    for index_name, (table_name, columns) in _NEW_INDEXES.items():
        existing_indexes = {
            index["name"] for index in inspector.get_indexes(table_name)
        }
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns)

    _ensure_parent_indexes()
    _ensure_audit_indexes()


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if connection.dialect.name == "postgresql":
        current_database = connection.execute(
            sa.text("SELECT current_database()")
        ).scalar_one()
        if current_database not in _APPROVED_DATABASES:
            raise RuntimeError(
                "This reviewed reconciliation is approved only for AgriDirect "
                "and its named verification clones."
            )
    for table_name, constraint_name, _referred_table, _columns, _referred_columns, _ondelete in reversed(_FOREIGN_KEYS):
        existing_names = {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        if constraint_name in existing_names:
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(constraint_name, type_="foreignkey")
            inspector = sa.inspect(connection)

    for index_name, table_name in (
        ("ix_knowledge_likes_post_id", "knowledge_likes"),
        ("ix_marketplace_crop_id", "marketplace"),
        ("ix_profile_reports_status_created", "profile_reports"),
        ("ix_audit_events_method_occurred", "audit_events"),
        ("ix_audit_events_status_occurred", "audit_events"),
    ):
        if index_name in {
            index["name"] for index in inspector.get_indexes(table_name)
        }:
            op.drop_index(index_name, table_name=table_name)

    if connection.dialect.name == "postgresql":
        location_verified = next(
            column
            for column in inspector.get_columns("users")
            if column["name"] == "location_verified"
        )
        if isinstance(location_verified["type"], sa.Boolean):
            op.execute(
                "ALTER TABLE users ALTER COLUMN location_verified DROP DEFAULT"
            )
            op.execute(
                "ALTER TABLE users ALTER COLUMN location_verified TYPE INTEGER "
                "USING CASE WHEN location_verified THEN 1 ELSE 0 END"
            )
            op.execute(
                "ALTER TABLE users ALTER COLUMN location_verified SET DEFAULT 0"
            )
        inspector = sa.inspect(connection)
        for table_name, column_name, length in reversed(_TEXT_TO_VARCHAR):
            column = next(
                item
                for item in inspector.get_columns(table_name)
                if item["name"] == column_name
            )
            if isinstance(column["type"], sa.String) and column["type"].length == length:
                op.alter_column(
                    table_name,
                    column_name,
                    existing_type=sa.String(length=length),
                    type_=sa.Text(),
                    existing_nullable=_TEXT_COLUMN_NULLABILITY[(table_name, column_name)],
                )
                inspector = sa.inspect(connection)

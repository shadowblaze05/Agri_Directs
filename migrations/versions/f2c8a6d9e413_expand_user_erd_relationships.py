"""Add canonical user links while preserving legacy username fields."""

from alembic import op
import sqlalchemy as sa


revision = "f2c8a6d9e413"
down_revision = "e7b6d2a93c41"
branch_labels = None
depends_on = None


_USER_LINKS = (
    ("marketplace", "seller_user_id", "user_id", "id"),
    ("marketplace", "buyer_user_id", "buyer_username", "username"),
    ("marketplace", "cancel_requested_by_user_id", "cancel_requested_by", "username"),
    ("messages", "sender_user_id", "sender", "username"),
    ("messages", "recipient_user_id", "recipient", "username"),
    ("notifications", "user_id", "username", "username"),
    ("harvest", "farmer_user_id", "farmer", "username"),
    ("inventory", "farmer_user_id", "farmer", "username"),
    ("inventory", "reviewed_by_user_id", "reviewed_by", "username"),
    ("knowledge_posts", "author_user_id", "author", "username"),
    ("knowledge_likes", "user_id", "username", "username"),
    ("knowledge_comments", "user_id", "username", "username"),
    ("knowledge_replies", "user_id", "username", "username"),
    ("profile_reports", "reporter_user_id", "reporter_username", "username"),
    ("profile_reports", "reported_user_id", "reported_username", "username"),
    ("profile_reports", "reviewed_by_user_id", "reviewed_by", "username"),
    ("listing_photo_location_alerts", "user_id", "username", "username"),
    ("listing_photo_location_alerts", "reviewed_by_user_id", "reviewed_by", "username"),
    ("audit_events", "actor_user_id", "actor", "username"),
)

_CROP_LINK = ("analytics", "top_crop_id", "crops", "id")
_APPROVED_DATABASES = {
    "AgriDirect",
    "AgriDirect_erd_verify",
    "AgriDirect_erd_rollback_verify",
}


def _constraint_name(table_name, column_name):
    return f"fk_{table_name}_{column_name}_users"


def _trigger_name(table_name):
    return f"trg_sync_erd_user_links_{table_name}"


def _function_name(table_name):
    return f"sync_erd_user_links_{table_name}"


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("This relationship migration requires PostgreSQL.")

    current_database = connection.execute(
        sa.text("SELECT current_database()")
    ).scalar_one()
    if current_database not in _APPROVED_DATABASES:
        raise RuntimeError(
            "This reviewed relationship expansion is approved only for the "
            "original AgriDirect database and named verification clones."
        )

    versions = set(
        connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != {down_revision}:
        raise RuntimeError(
            "Unexpected revision state before user-link expansion: "
            f"{sorted(versions)!r}."
        )

    inspector = sa.inspect(connection)
    if not inspector.has_table("users"):
        raise RuntimeError("Cannot add user relationships: users table is missing.")
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "username" not in user_columns or "id" not in user_columns:
        raise RuntimeError("Cannot add user relationships: users key columns are missing.")

    for table_name, column_name, source_column, source_key in _USER_LINKS:
        if not inspector.has_table(table_name):
            raise RuntimeError(f"Cannot add user relationship: {table_name} is missing.")
        table_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if source_column not in table_columns:
            raise RuntimeError(
                f"Cannot map {table_name}.{column_name}: "
                f"{table_name}.{source_column} is missing."
            )
        if column_name in table_columns:
            raise RuntimeError(
                f"Cannot add user relationship: {table_name}.{column_name} already exists."
            )
        op.add_column(table_name, sa.Column(column_name, sa.Integer(), nullable=True))
        if source_key == "id":
            connection.execute(
                sa.text(
                    f"UPDATE {table_name} AS source "
                    f"SET {column_name} = users.id "
                    f"FROM users WHERE users.id = source.{source_column}"
                )
            )
        else:
            connection.execute(
                sa.text(
                    f"UPDATE {table_name} AS source "
                    f"SET {column_name} = users.id "
                    f"FROM users WHERE users.username = source.{source_column}"
                )
            )
        op.create_foreign_key(
            _constraint_name(table_name, column_name),
            table_name,
            "users",
            [column_name],
            ["id"],
            ondelete="SET NULL",
        )

    if not inspector.has_table(_CROP_LINK[0]):
        raise RuntimeError("Cannot add analytics crop relationship: analytics is missing.")
    crop_orphans = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM analytics
            WHERE top_crop_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM crops WHERE crops.id = analytics.top_crop_id)
            """
        )
    ).scalar_one()
    if crop_orphans:
        raise RuntimeError(
            "Cannot add analytics.top_crop_id relationship: "
            f"{crop_orphans} orphan reference(s) exist."
        )
    op.create_foreign_key(
        "fk_analytics_top_crop_id_crops",
        "analytics",
        "crops",
        ["top_crop_id"],
        ["id"],
        ondelete="SET NULL",
    )

    links_by_table = {}
    for table_name, column_name, source_column, source_key in _USER_LINKS:
        links_by_table.setdefault(table_name, []).append(
            (column_name, source_column, source_key)
        )

    for table_name, links in links_by_table.items():
        assignments = []
        for column_name, source_column, source_key in links:
            if source_key == "id":
                query = f"SELECT id INTO NEW.{column_name} FROM users WHERE id = NEW.{source_column};"
            else:
                query = (
                    f"SELECT id INTO NEW.{column_name} FROM users "
                    f"WHERE username = NEW.{source_column};"
                )
            assignments.append(query)
        function_name = _function_name(table_name)
        trigger_name = _trigger_name(table_name)
        op.execute(
            f"""
            CREATE FUNCTION {function_name}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                {' '.join(assignments)}
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT OR UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            """
        )


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("This relationship migration requires PostgreSQL.")
    current_database = connection.execute(
        sa.text("SELECT current_database()")
    ).scalar_one()
    if current_database not in _APPROVED_DATABASES:
        raise RuntimeError(
            "This reviewed relationship expansion is approved only for the "
            "original AgriDirect database and named verification clones."
        )

    links_by_table = {}
    for table_name, column_name, _source_column, _source_key in _USER_LINKS:
        links_by_table.setdefault(table_name, []).append(column_name)

    inspector = sa.inspect(connection)
    for table_name in reversed(tuple(links_by_table)):
        trigger_name = _trigger_name(table_name)
        function_name = _function_name(table_name)
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
        op.execute(f"DROP FUNCTION IF EXISTS {function_name}()")

    for table_name, columns in reversed(tuple(links_by_table.items())):
        foreign_keys = {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        for column_name in reversed(columns):
            constraint_name = _constraint_name(table_name, column_name)
            if constraint_name in foreign_keys:
                op.drop_constraint(constraint_name, table_name, type_="foreignkey")
            op.drop_column(table_name, column_name)
            inspector = sa.inspect(connection)

    crop_constraints = {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("analytics")
    }
    if "fk_analytics_top_crop_id_crops" in crop_constraints:
        op.drop_constraint(
            "fk_analytics_top_crop_id_crops",
            "analytics",
            type_="foreignkey",
        )

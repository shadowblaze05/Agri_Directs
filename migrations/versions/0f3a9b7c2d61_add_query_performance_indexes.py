"""Index frequent query filters and add slow-query telemetry."""

from alembic import op
import sqlalchemy as sa


revision = "0f3a9b7c2d61"
down_revision = "e41b7c2a9d50"
branch_labels = None
depends_on = None


INDEXES = (
    ("ix_users_email", "users", ("email",)),
    ("ix_marketplace_status_listing_date", "marketplace", ("status", "listing_date")),
    (
        "ix_marketplace_user_status_listing_date",
        "marketplace",
        ("user_id", "status", "listing_date"),
    ),
    (
        "ix_marketplace_buyer_status_order_date",
        "marketplace",
        ("buyer_username", "status", "order_date"),
    ),
    ("ix_marketplace_username_rating", "marketplace", ("username", "buyer_rating")),
    (
        "ix_marketplace_status_type_listing_date",
        "marketplace",
        ("status", "listing_type", "listing_date"),
    ),
    (
        "ix_inventory_farmer_crop_date",
        "inventory",
        ("farmer", "crop_id", "date_received"),
    ),
    ("ix_inventory_crop_date", "inventory", ("crop_id", "date_received")),
    ("ix_inventory_source_date", "inventory", ("source", "date_received")),
    ("ix_knowledge_posts_status_pin_created", "knowledge_posts", ("status", "is_pinned", "created_at")),
    (
        "ix_knowledge_posts_category_status_created",
        "knowledge_posts",
        ("category_id", "status", "created_at"),
    ),
    ("ix_knowledge_comments_post_created", "knowledge_comments", ("post_id", "created_at")),
    ("ix_knowledge_replies_comment_created", "knowledge_replies", ("comment_id", "created_at")),
    (
        "ix_notifications_username_read_created",
        "notifications",
        ("username", "is_read", "created_at"),
    ),
    ("ix_messages_sender_recipient_time", "messages", ("sender", "recipient", "timestamp")),
    ("ix_messages_recipient_sender_time", "messages", ("recipient", "sender", "timestamp")),
    (
        "ix_password_reset_user_used_expiry",
        "password_reset_tokens",
        ("user_id", "used_at", "expires_at"),
    ),
    ("ix_marketplace_images_listing", "marketplace_images", ("listing_id",)),
    ("ix_cart_user_listing", "cart", ("user_id", "listing_id")),
    ("ix_analytics_period_type_value", "analytics", ("period_type", "period_value")),
    ("ix_audit_events_status_occurred", "audit_events", ("status_code", "occurred_at")),
    ("ix_audit_events_method_occurred", "audit_events", ("method", "occurred_at")),
)


def _existing_index_names(inspector, table_name):
    if op.get_bind().dialect.name == "sqlite":
        return set(
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = :table_name"
                ),
                {"table_name": table_name},
            )
            .scalars()
        )
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "slow_query_stats" not in inspector.get_table_names():
        op.create_table(
            "slow_query_stats",
            sa.Column("fingerprint", sa.String(length=64), primary_key=True),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_time_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("max_time_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        )

    inspector = sa.inspect(op.get_bind())
    for index_name, table_name, columns in INDEXES:
        if table_name not in inspector.get_table_names():
            continue
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if not set(columns).issubset(existing_columns):
            continue
        if index_name not in _existing_index_names(inspector, table_name):
            op.create_index(index_name, table_name, list(columns))

    if "users" in inspector.get_table_names():
        existing_columns = {
            column["name"] for column in inspector.get_columns("users")
        }
        if "email" in existing_columns:
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_users_lower_email "
                "ON users (LOWER(email))"
            )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    for index_name, table_name, _columns in reversed(INDEXES):
        if table_name in inspector.get_table_names() and index_name in _existing_index_names(inspector, table_name):
            op.drop_index(index_name, table_name=table_name)
    op.execute("DROP INDEX IF EXISTS ix_users_lower_email")
    if "slow_query_stats" in inspector.get_table_names():
        op.drop_table("slow_query_stats")

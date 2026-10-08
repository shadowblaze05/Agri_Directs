"""Add pinned Agricultural Updates and notification destinations."""

from alembic import op
import sqlalchemy as sa


revision = "d6a1c8f9032b"
down_revision = "a81f4c6e2b90"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name, column):
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return
    existing_columns = {
        existing["name"] for existing in inspector.get_columns(table_name)
    }
    if column.name not in existing_columns:
        op.add_column(table_name, column)


def upgrade():
    _add_column_if_missing(
        "knowledge_posts",
        sa.Column("is_pinned", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "notifications", sa.Column("link", sa.Text(), nullable=True)
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "notifications" in inspector.get_table_names() and "link" in {
        column["name"] for column in inspector.get_columns("notifications")
    }:
        op.drop_column("notifications", "link")
    if "knowledge_posts" in inspector.get_table_names() and "is_pinned" in {
        column["name"] for column in inspector.get_columns("knowledge_posts")
    }:
        op.drop_column("knowledge_posts", "is_pinned")

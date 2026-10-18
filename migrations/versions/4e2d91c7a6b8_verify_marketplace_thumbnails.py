"""Require camera and nearby GPS for marketplace thumbnails."""

from alembic import op
import sqlalchemy as sa


revision = "4e2d91c7a6b8"
down_revision = "c84a1f6b2d90"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name, column):
    existing_columns = {
        existing["name"] for existing in sa.inspect(op.get_bind()).get_columns(table_name)
    }
    if column.name not in existing_columns:
        op.add_column(table_name, column)
        return True
    return False


def upgrade():
    added_verification_column = _add_column_if_missing(
        "marketplace",
        sa.Column("thumbnail_verified", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "marketplace", sa.Column("thumbnail_latitude", sa.Float(), nullable=True)
    )
    _add_column_if_missing(
        "marketplace", sa.Column("thumbnail_longitude", sa.Float(), nullable=True)
    )
    _add_column_if_missing(
        "marketplace", sa.Column("thumbnail_distance_meters", sa.Float(), nullable=True)
    )
    _add_column_if_missing(
        "marketplace", sa.Column("thumbnail_captured_at", sa.String(length=32), nullable=True)
    )
    if added_verification_column:
        op.execute("UPDATE marketplace SET main_image = NULL WHERE thumbnail_verified = 0")


def downgrade():
    op.drop_column("marketplace", "thumbnail_captured_at")
    op.drop_column("marketplace", "thumbnail_distance_meters")
    op.drop_column("marketplace", "thumbnail_longitude")
    op.drop_column("marketplace", "thumbnail_latitude")
    op.drop_column("marketplace", "thumbnail_verified")

"""Require camera and nearby GPS for marketplace thumbnails."""

from alembic import op
import sqlalchemy as sa


revision = "4e2d91c7a6b8"
down_revision = "c84a1f6b2d90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "marketplace",
        sa.Column("thumbnail_verified", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("marketplace", sa.Column("thumbnail_latitude", sa.Float(), nullable=True))
    op.add_column("marketplace", sa.Column("thumbnail_longitude", sa.Float(), nullable=True))
    op.add_column("marketplace", sa.Column("thumbnail_distance_meters", sa.Float(), nullable=True))
    op.add_column("marketplace", sa.Column("thumbnail_captured_at", sa.String(length=32), nullable=True))
    op.execute("UPDATE marketplace SET main_image = NULL WHERE thumbnail_verified = 0")


def downgrade():
    op.drop_column("marketplace", "thumbnail_captured_at")
    op.drop_column("marketplace", "thumbnail_distance_meters")
    op.drop_column("marketplace", "thumbnail_longitude")
    op.drop_column("marketplace", "thumbnail_latitude")
    op.drop_column("marketplace", "thumbnail_verified")

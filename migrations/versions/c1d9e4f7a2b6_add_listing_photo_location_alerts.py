"""Track out-of-range listing thumbnail location attempts for admin review."""

from alembic import op
import sqlalchemy as sa


revision = "c1d9e4f7a2b6"
down_revision = "a81f4c6e2b90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "listing_photo_location_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("thumbnail_captured_at", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_listing_photo_alerts_status_created",
        "listing_photo_location_alerts",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_listing_photo_alerts_status_created",
        table_name="listing_photo_location_alerts",
    )
    op.drop_table("listing_photo_location_alerts")

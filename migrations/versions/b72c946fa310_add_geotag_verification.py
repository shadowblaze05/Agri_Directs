"""Add profile and harvest geotag verification fields."""

from alembic import op
import sqlalchemy as sa


revision = "b72c946fa310"
down_revision = "9c2f7e4a1b6d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("location_latitude", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("location_longitude", sa.Float(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "location_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("location_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("profile_photo_captured_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("inventory", sa.Column("photo_path", sa.String(length=255), nullable=True))
    op.add_column("inventory", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("inventory", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column(
        "inventory",
        sa.Column("capture_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("inventory", sa.Column("distance_from_user", sa.Float(), nullable=True))
    op.add_column(
        "inventory",
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("inventory", sa.Column("verification_notes", sa.Text(), nullable=True))
    op.add_column("inventory", sa.Column("reviewed_by", sa.String(length=128), nullable=True))
    op.add_column(
        "inventory",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("inventory", "reviewed_at")
    op.drop_column("inventory", "reviewed_by")
    op.drop_column("inventory", "verification_notes")
    op.drop_column("inventory", "verification_status")
    op.drop_column("inventory", "distance_from_user")
    op.drop_column("inventory", "capture_time")
    op.drop_column("inventory", "longitude")
    op.drop_column("inventory", "latitude")
    op.drop_column("inventory", "photo_path")
    op.drop_column("users", "location_verified_at")
    op.drop_column("users", "location_verified")
    op.drop_column("users", "location_longitude")
    op.drop_column("users", "location_latitude")
    op.drop_column("users", "profile_photo_captured_at")

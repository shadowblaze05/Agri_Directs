"""Require a server-verified profile-photo scan for profile completion."""

from alembic import op
import sqlalchemy as sa


revision = "c2f0a8e4d531"
down_revision = "df14a6c8b209"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "users" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "profile_photo_scan_verified_at" not in columns:
        op.add_column(
            "users",
            sa.Column("profile_photo_scan_verified_at", sa.DateTime(timezone=True)),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "users" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "profile_photo_scan_verified_at" in columns:
        op.drop_column("users", "profile_photo_scan_verified_at")

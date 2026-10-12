"""Add profile reports for admin review."""

from alembic import op
import sqlalchemy as sa


revision = "8c4d2a71f6b3"
down_revision = "0f3a9b7c2d61"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "profile_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporter_username", sa.String(length=128), nullable=False),
        sa.Column("reported_username", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
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
        "ix_profile_reports_status_created",
        "profile_reports",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index("ix_profile_reports_status_created", table_name="profile_reports")
    op.drop_table("profile_reports")

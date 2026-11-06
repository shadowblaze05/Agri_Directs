"""Add private evidence attachments to profile reports."""

from alembic import op
import sqlalchemy as sa


revision = "71a6d9c2e8f4"
down_revision = "d3a6f1c8b920"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "profile_reports",
        sa.Column("evidence_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "profile_reports",
        sa.Column("evidence_original_name", sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column("profile_reports", "evidence_original_name")
    op.drop_column("profile_reports", "evidence_filename")

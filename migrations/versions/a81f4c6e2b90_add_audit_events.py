"""Add append-only audit events."""

from alembic import op
import sqlalchemy as sa


revision = "a81f4c6e2b90"
down_revision = "4e2d91c7a6b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_audit_events_occurred_at_id", "audit_events", ["occurred_at", "id"]
    )
    op.create_index("ix_audit_events_actor", "audit_events", ["actor"])
    op.create_index("ix_audit_events_category", "audit_events", ["category"])


def downgrade():
    op.drop_index("ix_audit_events_category", table_name="audit_events")
    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at_id", table_name="audit_events")
    op.drop_table("audit_events")

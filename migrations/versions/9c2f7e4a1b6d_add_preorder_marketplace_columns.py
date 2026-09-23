"""Add preorder fields to marketplace listings."""

from alembic import op
import sqlalchemy as sa


revision = "9c2f7e4a1b6d"
down_revision = "01e53f8bea4f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("marketplace", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("listing_type", sa.String(length=20), server_default="standard")
        )
        batch_op.add_column(sa.Column("available_date", sa.String(length=32)))
        batch_op.add_column(sa.Column("preorder_status", sa.String(length=32)))
        batch_op.add_column(sa.Column("preorder_quantity", sa.Integer()))
        batch_op.add_column(sa.Column("cancel_requested_by", sa.String(length=128)))
        batch_op.add_column(sa.Column("cancel_reason", sa.Text()))
        batch_op.add_column(sa.Column("cancel_requested_date", sa.String(length=32)))


def downgrade():
    with op.batch_alter_table("marketplace", schema=None) as batch_op:
        batch_op.drop_column("cancel_requested_date")
        batch_op.drop_column("cancel_reason")
        batch_op.drop_column("cancel_requested_by")
        batch_op.drop_column("preorder_quantity")
        batch_op.drop_column("preorder_status")
        batch_op.drop_column("available_date")
        batch_op.drop_column("listing_type")

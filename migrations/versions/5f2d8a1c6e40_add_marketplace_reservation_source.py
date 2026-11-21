"""Track source listings for payment reservations."""

from alembic import op
import sqlalchemy as sa


revision = "5f2d8a1c6e40"
down_revision = "3c7b1a9d5e20"
branch_labels = None
depends_on = None


def upgrade():
    if "marketplace" not in sa.inspect(op.get_bind()).get_table_names():
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("marketplace")
    }
    if "reserved_from_listing_id" not in columns:
        op.add_column(
            "marketplace",
            sa.Column("reserved_from_listing_id", sa.Integer(), nullable=True),
        )


def downgrade():
    if "marketplace" not in sa.inspect(op.get_bind()).get_table_names():
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("marketplace")
    }
    if "reserved_from_listing_id" in columns:
        op.drop_column("marketplace", "reserved_from_listing_id")

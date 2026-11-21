"""Store marketplace order payment methods."""

from alembic import op
import sqlalchemy as sa


revision = "3c7b1a9d5e20"
down_revision = "8d4a2f6c1b90"
branch_labels = None
depends_on = None


def upgrade():
    if "marketplace" not in sa.inspect(op.get_bind()).get_table_names():
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("marketplace")
    }
    if "payment_method" not in columns:
        op.add_column(
            "marketplace",
            sa.Column("payment_method", sa.String(length=16), nullable=True),
        )


def downgrade():
    if "marketplace" not in sa.inspect(op.get_bind()).get_table_names():
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("marketplace")
    }
    if "payment_method" in columns:
        op.drop_column("marketplace", "payment_method")

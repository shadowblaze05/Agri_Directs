"""Store a buyer's saved marketplace delivery address."""

from alembic import op
import sqlalchemy as sa


revision = "f84c2a7d1e90"
down_revision = "5f2d8a1c6e40"
branch_labels = None
depends_on = None


def upgrade():
    if "users" not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")
    }
    with op.batch_alter_table("users", schema=None) as batch_op:
        for column_name in (
            "saved_delivery_province",
            "saved_delivery_city",
            "saved_delivery_barangay",
            "saved_delivery_street",
            "saved_delivery_landmark",
        ):
            if column_name not in existing_columns:
                batch_op.add_column(sa.Column(column_name, sa.String(length=255)))


def downgrade():
    if "users" not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")
    }
    with op.batch_alter_table("users", schema=None) as batch_op:
        for column_name in (
            "saved_delivery_landmark",
            "saved_delivery_street",
            "saved_delivery_barangay",
            "saved_delivery_city",
            "saved_delivery_province",
        ):
            if column_name in existing_columns:
                batch_op.drop_column(column_name)

"""Store delivery addresses on marketplace orders."""

from alembic import op
import sqlalchemy as sa


revision = "e41b7c2a9d50"
down_revision = "d6a1c8f9032b"
branch_labels = None
depends_on = None


def upgrade():
    existing_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("marketplace")
    }
    with op.batch_alter_table("marketplace", schema=None) as batch_op:
        for column_name in (
            "delivery_province",
            "delivery_city",
            "delivery_barangay",
            "delivery_street",
            "delivery_landmark",
        ):
            if column_name not in existing_columns:
                batch_op.add_column(sa.Column(column_name, sa.String(length=255)))


def downgrade():
    with op.batch_alter_table("marketplace", schema=None) as batch_op:
        batch_op.drop_column("delivery_landmark")
        batch_op.drop_column("delivery_street")
        batch_op.drop_column("delivery_barangay")
        batch_op.drop_column("delivery_city")
        batch_op.drop_column("delivery_province")

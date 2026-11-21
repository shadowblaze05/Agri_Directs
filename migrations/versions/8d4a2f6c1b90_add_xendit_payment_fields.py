"""Add Xendit payment-session fields to marketplace orders."""

from alembic import op
import sqlalchemy as sa


revision = "8d4a2f6c1b90"
down_revision = "6f3b2a9c1d84"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "marketplace" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("marketplace")
    }
    definitions = (
        ("xendit_reference_id", sa.String(length=64)),
        ("xendit_session_id", sa.String(length=128)),
        ("xendit_checkout_url", sa.Text()),
    )
    for name, column_type in definitions:
        if name not in columns:
            op.add_column(
                "marketplace",
                sa.Column(name, column_type, nullable=True),
            )

    indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("marketplace")
    }
    if "ix_marketplace_xendit_reference_id" not in indexes:
        op.create_index(
            "ix_marketplace_xendit_reference_id",
            "marketplace",
            ["xendit_reference_id"],
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "marketplace" not in inspector.get_table_names():
        return

    indexes = {
        index["name"]
        for index in inspector.get_indexes("marketplace")
    }
    if "ix_marketplace_xendit_reference_id" in indexes:
        op.drop_index("ix_marketplace_xendit_reference_id", table_name="marketplace")

    columns = {
        column["name"]
        for column in inspector.get_columns("marketplace")
    }
    for name in (
        "xendit_checkout_url",
        "xendit_session_id",
        "xendit_reference_id",
    ):
        if name in columns:
            op.drop_column("marketplace", name)

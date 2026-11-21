"""Add descriptions and default images to commodities."""

from alembic import op
import sqlalchemy as sa


revision = "4a7c1d9e5b20"
down_revision = "c2f0a8e4d531"
branch_labels = None
depends_on = None


def _commodity_columns():
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("commodities")
    }


def upgrade():
    columns = _commodity_columns()
    if "description" not in columns:
        op.add_column("commodities", sa.Column("description", sa.Text(), nullable=True))
    if "default_image" not in columns:
        op.add_column("commodities", sa.Column("default_image", sa.String(length=255), nullable=True))


def downgrade():
    columns = _commodity_columns()
    if "default_image" in columns:
        op.drop_column("commodities", "default_image")
    if "description" in columns:
        op.drop_column("commodities", "description")

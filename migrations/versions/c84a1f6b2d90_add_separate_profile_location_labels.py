"""Store GPS-derived and PSGC profile locations separately."""

from alembic import op
import sqlalchemy as sa


revision = "c84a1f6b2d90"
down_revision = "b72c946fa310"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name, column):
    existing_columns = {
        existing["name"] for existing in sa.inspect(op.get_bind()).get_columns(table_name)
    }
    if column.name not in existing_columns:
        op.add_column(table_name, column)


def upgrade():
    _add_column_if_missing(
        "users", sa.Column("psgc_location", sa.String(length=255), nullable=True)
    )
    _add_column_if_missing(
        "users", sa.Column("geotag_location", sa.String(length=255), nullable=True)
    )
    op.execute(
        "UPDATE users SET geotag_location = location "
        "WHERE location IS NOT NULL AND geotag_location IS NULL"
    )


def downgrade():
    op.drop_column("users", "geotag_location")
    op.drop_column("users", "psgc_location")

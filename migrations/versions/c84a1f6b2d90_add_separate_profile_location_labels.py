"""Store GPS-derived and PSGC profile locations separately."""

from alembic import op
import sqlalchemy as sa


revision = "c84a1f6b2d90"
down_revision = "b72c946fa310"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("psgc_location", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("geotag_location", sa.String(length=255), nullable=True))
    op.execute("UPDATE users SET geotag_location = location WHERE location IS NOT NULL")


def downgrade():
    op.drop_column("users", "geotag_location")
    op.drop_column("users", "psgc_location")

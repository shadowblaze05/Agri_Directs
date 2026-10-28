"""Add crop-linked marketplace pricing rules."""

from alembic import op
import sqlalchemy as sa


revision = "3b6a91d8e2f4"
down_revision = "f2c8a6d9e413"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "crop_pricing" not in inspector.get_table_names():
        op.create_table(
            "crop_pricing",
            sa.Column(
                "crop_id",
                sa.Integer(),
                sa.ForeignKey("crops.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("pricing_mode", sa.String(length=16), nullable=False),
            sa.Column(
                "price_unit",
                sa.String(length=16),
                nullable=False,
                server_default="kg",
            ),
            sa.Column("reference_price", sa.Numeric(10, 2), nullable=True),
            sa.Column("price_range", sa.Numeric(10, 2), nullable=True),
            sa.Column("minimum_price", sa.Numeric(10, 2), nullable=True),
            sa.Column("maximum_price", sa.Numeric(10, 2), nullable=True),
            sa.CheckConstraint(
                "pricing_mode IN ('range', 'bounds')",
                name="ck_crop_pricing_mode",
            ),
            sa.CheckConstraint(
                "price_unit = 'kg'",
                name="ck_crop_pricing_unit",
            ),
            sa.CheckConstraint(
                "(pricing_mode = 'range' AND reference_price > 0 "
                "AND price_range >= 0 AND reference_price > price_range "
                "AND minimum_price IS NULL "
                "AND maximum_price IS NULL) OR "
                "(pricing_mode = 'bounds' AND minimum_price > 0 "
                "AND maximum_price >= minimum_price AND price_range IS NULL "
                "AND (reference_price IS NULL OR reference_price BETWEEN "
                "minimum_price AND maximum_price))",
                name="ck_crop_pricing_values",
            ),
        )


def downgrade():
    if "crop_pricing" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("crop_pricing")

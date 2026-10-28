"""Standardize all crop pricing rules to per-kilogram prices."""

from alembic import op
import sqlalchemy as sa


revision = "5d8c2a1e7f43"
down_revision = "3b6a91d8e2f4"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "crop_pricing" not in inspector.get_table_names():
        return

    op.execute("UPDATE crop_pricing SET price_unit='kg' WHERE price_unit <> 'kg'")
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("crop_pricing")
    }
    with op.batch_alter_table("crop_pricing") as batch_op:
        if "ck_crop_pricing_unit" in constraints:
            batch_op.drop_constraint("ck_crop_pricing_unit", type_="check")
        batch_op.create_check_constraint(
            "ck_crop_pricing_unit",
            "price_unit = 'kg'",
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "crop_pricing" not in inspector.get_table_names():
        return
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("crop_pricing")
    }
    with op.batch_alter_table("crop_pricing") as batch_op:
        if "ck_crop_pricing_unit" in constraints:
            batch_op.drop_constraint("ck_crop_pricing_unit", type_="check")
        batch_op.create_check_constraint(
            "ck_crop_pricing_unit",
            "price_unit IN ('kg', 'g', 'lb', 'oz', 'piece', 'bundle')",
        )

"""Rename crop schema objects to commodity terminology."""

from alembic import op
import sqlalchemy as sa


revision = "df14a6c8b209"
down_revision = "ce82a314fd17"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name):
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _rename_table(old_name, new_name):
    tables = _tables()
    if old_name in tables and new_name not in tables:
        op.rename_table(old_name, new_name)


def _rename_column(table_name, old_name, new_name):
    if table_name not in _tables():
        return
    columns = _columns(table_name)
    if old_name in columns and new_name not in columns:
        op.execute(
            sa.text(
                f'ALTER TABLE "{table_name}" RENAME COLUMN '
                f'"{old_name}" TO "{new_name}"'
            )
        )


def upgrade():
    _rename_table("crops", "commodities")
    _rename_table("crop_categories", "commodity_categories")
    _rename_table("crop_pricing", "commodity_pricing")

    for table_name in (
        "commodities",
        "harvest",
        "inventory",
        "marketplace",
        "commodity_pricing",
    ):
        _rename_column(table_name, "crop_id", "commodity_id")
        _rename_column(table_name, "crop_name", "commodity_name")
        _rename_column(table_name, "crops_name", "commodity_name")

    _rename_column("analytics", "top_crop", "top_commodity")
    _rename_column("analytics", "top_crop_volume", "top_commodity_volume")
    _rename_column("analytics", "top_crop_id", "top_commodity_id")


def downgrade():
    for table_name in ("harvest", "inventory", "marketplace", "commodity_pricing"):
        _rename_column(table_name, "commodity_id", "crop_id")

    for table_name in ("inventory", "marketplace"):
        _rename_column(table_name, "commodity_name", "crop_name")

    _rename_column("analytics", "top_commodity", "top_crop")
    _rename_column("analytics", "top_commodity_volume", "top_crop_volume")
    _rename_column("analytics", "top_commodity_id", "top_crop_id")

    _rename_table("commodity_pricing", "crop_pricing")
    _rename_table("commodity_categories", "crop_categories")
    _rename_table("commodities", "crops")
    _rename_column("crops", "commodity_name", "crops_name")

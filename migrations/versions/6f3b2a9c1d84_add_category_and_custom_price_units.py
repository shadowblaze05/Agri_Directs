"""Add category defaults and custom commodity price units."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Index, MetaData, PrimaryKeyConstraint, Table


revision = "6f3b2a9c1d84"
down_revision = "4a7c1d9e5b20"
branch_labels = None
depends_on = None


BUILTIN_UNITS = ("kg", "pc", "pack")


def _column_names(table_name):
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _remove_unit_check(table_name, unit_column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    checks = [
        check
        for check in inspector.get_check_constraints(table_name)
        if unit_column in (check.get("sqltext") or "").lower()
    ]
    if not checks:
        return

    if bind.dialect.name == "sqlite" and any(not check.get("name") for check in checks):
        reflected = Table(table_name, MetaData(), autoload_with=bind)
        retained = [
            constraint
            for constraint in reflected.constraints
            if not isinstance(constraint, PrimaryKeyConstraint)
            and not (
                isinstance(constraint, CheckConstraint)
                and unit_column in str(constraint.sqltext).lower()
            )
        ]
        copy = Table(
            table_name,
            MetaData(),
            *[column._copy() for column in reflected.columns],
            *retained,
            *[index._copy() for index in reflected.indexes],
        )
        column_type = next(
            column["type"]
            for column in inspector.get_columns(table_name)
            if column["name"] == unit_column
        )
        with op.batch_alter_table(
            table_name,
            copy_from=copy,
            recreate="always",
        ) as batch:
            batch.alter_column(
                unit_column,
                existing_type=column_type,
                type_=sa.String(32),
            )
        return

    for check in checks:
        if check.get("name"):
            op.drop_constraint(check["name"], table_name, type_="check")


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "commodity_price_units" not in tables:
        op.create_table(
            "commodity_price_units",
            sa.Column("unit", sa.String(32), primary_key=True, nullable=False),
        )
    for unit in BUILTIN_UNITS:
        op.execute(
            sa.text(
                "INSERT INTO commodity_price_units(unit) VALUES (:unit) "
                "ON CONFLICT(unit) DO NOTHING"
            ).bindparams(unit=unit)
        )

    if "commodity_categories" in tables:
        if "default_price_unit" not in _column_names("commodity_categories"):
            op.add_column(
                "commodity_categories",
                sa.Column(
                    "default_price_unit",
                    sa.String(32),
                    nullable=False,
                    server_default="kg",
                ),
            )
        op.execute(
            """UPDATE commodity_categories SET default_price_unit='pack'
               WHERE LOWER(name) LIKE '%cigarette%' AND default_price_unit='kg'"""
        )

    if "commodities" in tables:
        if "default_price_unit" not in _column_names("commodities"):
            op.add_column(
                "commodities",
                sa.Column(
                    "default_price_unit",
                    sa.String(32),
                    nullable=False,
                    server_default="kg",
                ),
            )
        _remove_unit_check("commodities", "default_price_unit")
        op.execute(
            """UPDATE commodities
               SET default_price_unit=COALESCE(
                   (SELECT default_price_unit FROM commodity_categories
                    WHERE commodity_categories.id=commodities.category_id),
                   default_price_unit,
                   'kg'
               )"""
        )

    if "commodity_pricing" in tables:
        _remove_unit_check("commodity_pricing", "price_unit")
        columns = _column_names("commodity_pricing")
        if "price_unit" in columns:
            column_type = next(
                column["type"]
                for column in inspector.get_columns("commodity_pricing")
                if column["name"] == "price_unit"
            )
            if op.get_bind().dialect.name != "sqlite":
                op.alter_column(
                    "commodity_pricing",
                    "price_unit",
                    existing_type=column_type,
                    type_=sa.String(32),
                )
            if "commodities" in tables:
                op.execute(
                    """UPDATE commodity_pricing
                       SET price_unit=COALESCE(
                           (SELECT default_price_unit FROM commodities
                            WHERE commodities.id=commodity_pricing.commodity_id),
                           price_unit,
                           'kg'
                       )"""
                )


def downgrade():
    op.execute(
        """UPDATE commodity_pricing SET price_unit='kg'
           WHERE price_unit NOT IN ('kg', 'pc', 'pack')"""
    )
    op.execute(
        """UPDATE commodities SET default_price_unit='kg'
           WHERE default_price_unit NOT IN ('kg', 'pc', 'pack')"""
    )
    op.execute(
        """UPDATE commodity_categories SET default_price_unit='kg'
           WHERE default_price_unit NOT IN ('kg', 'pc', 'pack')"""
    )
    op.drop_table("commodity_price_units")
    op.drop_column("commodity_categories", "default_price_unit")

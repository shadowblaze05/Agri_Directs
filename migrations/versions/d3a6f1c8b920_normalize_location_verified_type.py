"""Normalize the profile location verification column to BOOLEAN."""

from alembic import op
import sqlalchemy as sa


revision = "d3a6f1c8b920"
down_revision = ("f2c8a6d9e413", "5d8c2a1e7f43")
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return

    columns = sa.inspect(connection).get_columns("users")
    column = next(
        (item for item in columns if item["name"] == "location_verified"),
        None,
    )
    if column is None:
        raise RuntimeError("users.location_verified is missing.")
    if not isinstance(column["type"], sa.Integer):
        return

    invalid_values = connection.execute(
        sa.text(
            "SELECT count(*) FROM users "
            "WHERE location_verified IS NULL OR location_verified NOT IN (0, 1)"
        )
    ).scalar_one()
    if invalid_values:
        raise RuntimeError(
            "Cannot convert users.location_verified to BOOLEAN: "
            f"{invalid_values} value(s) are not 0 or 1."
        )

    op.execute("ALTER TABLE users ALTER COLUMN location_verified DROP DEFAULT")
    op.execute(
        "ALTER TABLE users ALTER COLUMN location_verified TYPE BOOLEAN "
        "USING CASE WHEN location_verified = 1 THEN TRUE ELSE FALSE END"
    )
    op.execute(
        "ALTER TABLE users ALTER COLUMN location_verified SET DEFAULT FALSE"
    )


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return

    columns = sa.inspect(connection).get_columns("users")
    column = next(
        (item for item in columns if item["name"] == "location_verified"),
        None,
    )
    if column is None:
        raise RuntimeError("users.location_verified is missing.")
    if isinstance(column["type"], sa.Boolean):
        op.execute("ALTER TABLE users ALTER COLUMN location_verified DROP DEFAULT")
        op.execute(
            "ALTER TABLE users ALTER COLUMN location_verified TYPE INTEGER "
            "USING CASE WHEN location_verified THEN 1 ELSE 0 END"
        )
        op.execute("ALTER TABLE users ALTER COLUMN location_verified SET DEFAULT 0")

"""Normalize profile location verification and password-reset user constraints."""

from alembic import op
import sqlalchemy as sa


revision = "d3a6f1c8b920"
down_revision = ("f2c8a6d9e413", "5d8c2a1e7f43")
branch_labels = None
depends_on = None


def _normalize_password_reset_user_foreign_key(connection):
    inspector = sa.inspect(connection)
    if not inspector.has_table("password_reset_tokens"):
        raise RuntimeError("password_reset_tokens table is missing.")
    columns = {
        column["name"]
        for column in inspector.get_columns("password_reset_tokens")
    }
    if "user_id" not in columns:
        raise RuntimeError("password_reset_tokens.user_id is missing.")

    user_foreign_keys = [
        foreign_key
        for foreign_key in inspector.get_foreign_keys("password_reset_tokens")
        if foreign_key.get("constrained_columns") == ["user_id"]
        and foreign_key.get("referred_table") == "users"
        and foreign_key.get("referred_columns") == ["id"]
    ]
    cascading_foreign_key = next(
        (
            foreign_key
            for foreign_key in user_foreign_keys
            if foreign_key.get("options", {}).get("ondelete", "").upper()
            == "CASCADE"
        ),
        None,
    )

    for foreign_key in user_foreign_keys:
        if (
            foreign_key is not cascading_foreign_key
            and foreign_key.get("name") is None
        ):
            raise RuntimeError(
                "Cannot replace an unnamed password_reset_tokens.user_id foreign key."
            )
        if foreign_key is not cascading_foreign_key:
            op.drop_constraint(
                foreign_key["name"],
                "password_reset_tokens",
                type_="foreignkey",
            )

    if cascading_foreign_key is None:
        op.create_foreign_key(
            "fk_password_reset_tokens_user_id_users",
            "password_reset_tokens",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return

    _normalize_password_reset_user_foreign_key(connection)

    columns = sa.inspect(connection).get_columns("users")
    column = next(
        (item for item in columns if item["name"] == "location_verified"),
        None,
    )
    if column is None:
        raise RuntimeError("users.location_verified is missing.")
    if isinstance(column["type"], sa.Integer):
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
    elif not isinstance(column["type"], sa.Boolean):
        raise RuntimeError(
            "users.location_verified must be INTEGER or BOOLEAN; "
            f"found {column['type']}."
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

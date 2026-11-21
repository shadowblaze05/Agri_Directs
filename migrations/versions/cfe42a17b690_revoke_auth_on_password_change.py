"""Add per-account authentication versions for credential revocation."""

import sqlalchemy as sa
from alembic import op


revision = "cfe42a17b690"
down_revision = "ab41d8e6c027"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    user_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }

    if "auth_version" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "auth_version",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    else:
        op.execute(
            "UPDATE users SET auth_version=0 WHERE auth_version IS NULL"
        )
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("users") as batch_op:
                batch_op.alter_column(
                    "auth_version",
                    existing_type=sa.Integer(),
                    server_default=sa.text("0"),
                    nullable=False,
                )
        else:
            op.alter_column(
                "users",
                "auth_version",
                existing_type=sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )


def downgrade():
    op.drop_column("users", "auth_version")

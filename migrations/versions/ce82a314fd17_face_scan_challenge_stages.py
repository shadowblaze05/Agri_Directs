"""Track server-validated profile-photo scan challenge stages."""

from alembic import op
import sqlalchemy as sa


revision = "ce82a314fd17"
down_revision = "a9d2f3c7e601"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "profile_photo_challenges" not in set(inspector.get_table_names()):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("profile_photo_challenges")
    }
    additions = (
        sa.Column(
            "movement_sequence",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "current_stage",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_stage_at", sa.String(length=40), nullable=True),
        sa.Column(
            "failed_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("profile_photo_challenges", column)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "profile_photo_challenges" not in set(inspector.get_table_names()):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("profile_photo_challenges")
    }
    for column_name in (
        "failed_attempts",
        "last_stage_at",
        "current_stage",
        "movement_sequence",
    ):
        if column_name in columns:
            op.drop_column("profile_photo_challenges", column_name)

"""Add private profile-photo visibility and one-use capture challenges."""

from alembic import op
import sqlalchemy as sa


revision = "a9d2f3c7e601"
down_revision = "c71b4a2d9e30"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "users" in tables:
        user_columns = {
            column["name"] for column in inspector.get_columns("users")
        }
        if "profile_picture_public" not in user_columns:
            op.add_column(
                "users",
                sa.Column(
                    "profile_picture_public",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        else:
            op.execute(
                "UPDATE users SET profile_picture_public = FALSE "
                "WHERE profile_picture_public IS NULL"
            )

    if "profile_photo_challenges" not in tables:
        op.create_table(
            "profile_photo_challenges",
            sa.Column("challenge_hash", sa.String(length=64), primary_key=True),
            sa.Column("username", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.String(length=40), nullable=False),
            sa.Column("consumed_at", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )

    challenge_indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("profile_photo_challenges")
    }
    if "ix_profile_photo_challenges_user_expiry" not in challenge_indexes:
        op.create_index(
            "ix_profile_photo_challenges_user_expiry",
            "profile_photo_challenges",
            ["username", "expires_at"],
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "profile_photo_challenges" in tables:
        indexes = {
            index["name"]
            for index in inspector.get_indexes("profile_photo_challenges")
        }
        if "ix_profile_photo_challenges_user_expiry" in indexes:
            op.drop_index(
                "ix_profile_photo_challenges_user_expiry",
                table_name="profile_photo_challenges",
            )
        op.drop_table("profile_photo_challenges")

    if "users" in tables:
        user_columns = {
            column["name"] for column in inspector.get_columns("users")
        }
        if "profile_picture_public" in user_columns:
            op.drop_column("users", "profile_picture_public")

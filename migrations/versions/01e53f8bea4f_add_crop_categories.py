"""Add crop categories

Revision ID: 01e53f8bea4f
Revises: fd6d67b9de23
Create Date: 2026-08-29 20:14:03.132611

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '01e53f8bea4f'
down_revision = 'fd6d67b9de23'
branch_labels = None
depends_on = None


def upgrade():

    # ---------------------------------------------------------
    # 1. Create crop_categories table
    # ---------------------------------------------------------

    op.create_table(
        'crop_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )


    # ---------------------------------------------------------
    # 2. Add category_id to crops
    # ---------------------------------------------------------

    with op.batch_alter_table('crops', schema=None) as batch_op:

        batch_op.add_column(
            sa.Column(
                'category_id',
                sa.Integer(),
                nullable=True
            )
        )

        batch_op.alter_column(
            'crops_name',
            existing_type=sa.VARCHAR(length=128),
            nullable=False
        )

        batch_op.create_foreign_key(
            None,
            'crop_categories',
            ['category_id'],
            ['id']
        )


    # ---------------------------------------------------------
    # 3. Update harvest table
    # ---------------------------------------------------------

    with op.batch_alter_table('harvest', schema=None) as batch_op:

        batch_op.alter_column(
            'crop_id',
            existing_type=sa.INTEGER(),
            nullable=False
        )

        batch_op.create_foreign_key(
            None,
            'crops',
            ['crop_id'],
            ['id']
        )


    # ---------------------------------------------------------
    # 4. Add crop_id to inventory
    # ---------------------------------------------------------

    # IMPORTANT:
    # crop_name is intentionally NOT removed.
    #
    # Existing inventory records already use crop_name.
    # We keep it and add crop_id alongside it.

    with op.batch_alter_table('inventory', schema=None) as batch_op:

        batch_op.add_column(
            sa.Column(
                'crop_id',
                sa.Integer(),
                nullable=True
            )
        )


    # ---------------------------------------------------------
    # 5. Populate crop_id using existing crop_name
    # ---------------------------------------------------------

    op.execute("""
        UPDATE inventory AS i
        SET crop_id = c.id
        FROM crops AS c
        WHERE i.crop_name = c.crops_name
    """)


    # ---------------------------------------------------------
    # 6. Check for unmatched inventory records
    # ---------------------------------------------------------

    connection = op.get_bind()

    unmatched = connection.execute(
        sa.text("""
            SELECT COUNT(*)
            FROM inventory
            WHERE crop_id IS NULL
        """)
    ).scalar()

    if unmatched > 0:
        raise RuntimeError(
            f"{unmatched} inventory record(s) could not be matched "
            "to a crop in the crops table. "
            "Please check inventory.crop_name and crops.crops_name."
        )


    # ---------------------------------------------------------
    # 7. Make inventory.crop_id NOT NULL
    #    and add foreign key
    # ---------------------------------------------------------

    with op.batch_alter_table('inventory', schema=None) as batch_op:

        batch_op.alter_column(
            'crop_id',
            existing_type=sa.INTEGER(),
            nullable=False
        )

        batch_op.create_foreign_key(
            None,
            'crops',
            ['crop_id'],
            ['id']
        )

        # DO NOT DROP crop_name.
        #
        # crop_name is intentionally preserved.


def downgrade():

    # ---------------------------------------------------------
    # 1. Remove inventory crop_id foreign key and column
    # ---------------------------------------------------------

    with op.batch_alter_table('inventory', schema=None) as batch_op:

        batch_op.drop_constraint(
            None,
            type_='foreignkey'
        )

        batch_op.drop_column('crop_id')


    # ---------------------------------------------------------
    # 2. Restore harvest
    # ---------------------------------------------------------

    with op.batch_alter_table('harvest', schema=None) as batch_op:

        batch_op.drop_constraint(
            None,
            type_='foreignkey'
        )

        batch_op.alter_column(
            'crop_id',
            existing_type=sa.INTEGER(),
            nullable=True
        )


    # ---------------------------------------------------------
    # 3. Restore crops
    # ---------------------------------------------------------

    with op.batch_alter_table('crops', schema=None) as batch_op:

        batch_op.drop_constraint(
            None,
            type_='foreignkey'
        )

        batch_op.alter_column(
            'crops_name',
            existing_type=sa.VARCHAR(length=128),
            nullable=True
        )

        batch_op.drop_column('category_id')


    # ---------------------------------------------------------
    # 4. Remove crop_categories
    # ---------------------------------------------------------

    op.drop_table('crop_categories')

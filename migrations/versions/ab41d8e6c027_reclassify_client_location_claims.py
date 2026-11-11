"""Reclassify client-submitted location data as unverified claims."""

from alembic import op


revision = "ab41d8e6c027"
down_revision = "71a6d9c2e8f4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE users SET location_verified=FALSE, location_verified_at=NULL "
        "WHERE location_verified=TRUE"
    )
    op.execute(
        "UPDATE marketplace SET thumbnail_verified=0 "
        "WHERE thumbnail_verified <> 0"
    )
    op.execute(
        """
        UPDATE inventory
        SET verification_status='pending_review',
            verification_notes=CASE
                WHEN verification_notes IS NULL OR verification_notes=''
                    THEN 'Prior GPS coordinates and timestamp are self-reported; proximity is not verification.'
                ELSE verification_notes || ' Prior GPS coordinates and timestamp are self-reported; proximity is not verification.'
            END
        WHERE verification_status IN ('within_range', 'outside_range')
        """
    )


def downgrade():
    # Restoring these values would reclassify untrusted claims as verified.
    pass

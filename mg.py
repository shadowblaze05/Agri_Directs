"""Add pre-order columns to marketplace table."""

from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("=" * 60)
    print("PRE-ORDER MIGRATION")
    print("=" * 60)
    
    inspector = db.inspect(db.engine)
    existing = [col['name'] for col in inspector.get_columns('marketplace')]
    
    # listing_type: 'standard' or 'preorder'
    if 'listing_type' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN listing_type VARCHAR(20) DEFAULT 'standard'"))
        db.session.commit()
        print("✓ Added listing_type")
    else:
        print("- listing_type already exists")
    
    # available_date: when the pre-order will be ready
    if 'available_date' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN available_date VARCHAR(32)"))
        db.session.commit()
        print("✓ Added available_date")
    else:
        print("- available_date already exists")
    
    # preorder_status: pending, confirmed, cancel_requested, cancelled, completed
    if 'preorder_status' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN preorder_status VARCHAR(32)"))
        db.session.commit()
        print("✓ Added preorder_status")
    else:
        print("- preorder_status already exists")
    
    # preorder_quantity: how much the buyer reserved
    if 'preorder_quantity' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN preorder_quantity INTEGER"))
        db.session.commit()
        print("✓ Added preorder_quantity")
    else:
        print("- preorder_quantity already exists")
    
    # cancel_requested_by: username who requested cancel
    if 'cancel_requested_by' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN cancel_requested_by VARCHAR(128)"))
        db.session.commit()
        print("✓ Added cancel_requested_by")
    else:
        print("- cancel_requested_by already exists")
    
    # cancel_reason: buyer/seller reason for cancellation
    if 'cancel_reason' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN cancel_reason TEXT"))
        db.session.commit()
        print("✓ Added cancel_reason")
    else:
        print("- cancel_reason already exists")
    
    # cancel_requested_date: when cancel was requested
    if 'cancel_requested_date' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN cancel_requested_date VARCHAR(32)"))
        db.session.commit()
        print("✓ Added cancel_requested_date")
    else:
        print("- cancel_requested_date already exists")
    
    print("\n✅ Migration complete. Restart Flask.")

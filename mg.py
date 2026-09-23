"""Add looking_for support. Only new column needed: looking_for_notes."""

from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("=" * 60)
    print("LOOKING-FOR MIGRATION")
    print("=" * 60)
    
    inspector = db.inspect(db.engine)
    existing = [col['name'] for col in inspector.get_columns('marketplace')]
    
    if 'looking_for_notes' not in existing:
        db.session.execute(text("ALTER TABLE marketplace ADD COLUMN looking_for_notes TEXT"))
        db.session.commit()
        print("✓ Added looking_for_notes")
    else:
        print("- looking_for_notes already exists")
    
    print("\n✅ Migration complete. Restart Flask.")
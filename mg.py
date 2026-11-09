from app import create_app
from app.extensions import db
from sqlalchemy import text
from datetime import datetime
from app.routes.home import get_welcome_message

app = create_app()

with app.app_context():
    print("Fetching users...")
    users = db.session.execute(text("SELECT username FROM users")).fetchall()
    
    welcome_msg = get_welcome_message()
    count = 0
    
    for row in users:
        username = row[0]
        
        # Check if they already have the welcome message to avoid spamming
        existing = db.session.execute(
            text("SELECT id FROM messages WHERE sender='AgriBot' AND recipient=:u AND message LIKE '%Greetings! Welcome%'"),
            {"u": username}
        ).fetchone()
        
        if not existing:
            db.session.execute(
                text("INSERT INTO messages(sender, recipient, message, timestamp) VALUES ('AgriBot', :u, :m, :t)"),
                {"u": username, "m": welcome_msg, "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            )
            count += 1
            
    db.session.commit()
    print(f"✅ Sent welcome message to {count} existing users.")
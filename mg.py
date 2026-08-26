# reset_password_interactive.py
from app import create_app
from app.extensions import db
from sqlalchemy import text
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    # Show all users
    users = db.session.execute(text("SELECT id, username FROM users ORDER BY id")).fetchall()
    
    print("\n📋 All Users:")
    for user in users:
        print(f"   {user[1]}")
    
    print("\n" + "=" * 40)
    username = input("Enter username to reset: ")
    new_password = input("Enter new password: ")
    
    user = db.session.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": username}
    ).fetchone()
    
    if user:
        hashed = generate_password_hash(new_password)
        db.session.execute(
            text("UPDATE users SET password = :password WHERE username = :username"),
            {"password": hashed, "username": username}
        )
        db.session.commit()
        print(f"\n✅ Password for '{username}' has been reset to: {new_password}")
    else:
        print(f"\n❌ User '{username}' not found!")
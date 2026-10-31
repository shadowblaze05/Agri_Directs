from datetime import datetime, timezone


def notify_published_announcement(cursor, post_id, title):
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO notifications
            (username, title, message, type, created_at, is_read, link)
        SELECT username, ?, ?, 'announcement', ?, 0, ?
        FROM users
        WHERE username IS NOT NULL AND COALESCE(role, 'user') != 'admin'
        """,
        (
            "Pinned Agricultural Update",
            f'"{title}" has been pinned in Agricultural Updates.',
            created_at,
            f"/knowledge/{post_id}",
        ),
    )

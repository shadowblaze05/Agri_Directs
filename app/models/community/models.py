"""Community messaging and notification models."""

from sqlalchemy import ForeignKey, Integer, String, Text
from ..base import Column, Model


class Message(Model):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    sender = Column(String(128))
    sender_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_messages_sender_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    recipient = Column(String(128))
    recipient_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_messages_recipient_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    message = Column(Text)
    timestamp = Column(String(32))
    attachment_url = Column(Text)
    attachment_type = Column(String(16))


class Notification(Model):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    username = Column(String(128))
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_notifications_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    title = Column(String(255))
    message = Column(Text)
    type = Column(String(64))
    created_at = Column(String(32))
    is_read = Column(Integer, default=0)
    link = Column(Text)

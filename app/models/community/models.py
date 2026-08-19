"""Community messaging and notification models."""

from sqlalchemy import Integer, String, Text

from ..base import Column, Model


class Message(Model):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    sender = Column(String(128))
    recipient = Column(String(128))
    message = Column(Text)
    timestamp = Column(String(32))


class Notification(Model):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    username = Column(String(128))
    title = Column(String(255))
    message = Column(Text)
    type = Column(String(64))
    created_at = Column(String(32))
    is_read = Column(Integer, default=0)

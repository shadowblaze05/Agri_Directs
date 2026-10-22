from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from .base import Column, Model


class AuditEvent(Model):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at_id", "occurred_at", "id"),
        Index("ix_audit_events_actor", "actor"),
        Index("ix_audit_events_category", "category"),
    )

    id = Column(Integer, primary_key=True)
    occurred_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    actor = Column(String(128), nullable=True)
    actor_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_audit_events_actor_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    role = Column(String(32), nullable=True)
    action = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    method = Column(String(10), nullable=False)
    endpoint = Column(String(128), nullable=False)
    path = Column(String(512), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    details = Column(Text, nullable=False, default="{}")

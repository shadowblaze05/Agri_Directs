from sqlalchemy import DateTime, Index, Integer, String, Text, func

from .base import Column, Model


class ProfileReport(Model):
    __tablename__ = "profile_reports"
    __table_args__ = (
        Index("ix_profile_reports_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    reporter_username = Column(String(128), nullable=False)
    reported_username = Column(String(128), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="open", server_default="open")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from .base import Column, Model


class ProfileReport(Model):
    __tablename__ = "profile_reports"
    __table_args__ = (
        Index("ix_profile_reports_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    reporter_username = Column(String(128), nullable=False)
    reporter_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_profile_reports_reporter_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    reported_username = Column(String(128), nullable=False)
    reported_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_profile_reports_reported_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    description = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="open", server_default="open")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    reviewed_by = Column(String(128), nullable=True)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_profile_reports_reviewed_by_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

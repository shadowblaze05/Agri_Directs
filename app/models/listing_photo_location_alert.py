from sqlalchemy import DateTime, Float, Index, Integer, String, func

from .base import Column, Model


class ListingPhotoLocationAlert(Model):
    __tablename__ = "listing_photo_location_alerts"
    __table_args__ = (
        Index("ix_listing_photo_alerts_status_created", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String(128), nullable=False)
    distance_meters = Column(Float, nullable=False)
    thumbnail_captured_at = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="open", server_default="open")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

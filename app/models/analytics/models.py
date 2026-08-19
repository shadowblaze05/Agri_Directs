"""Analytics model."""

from sqlalchemy import Integer, String

from ..base import Column, Model


class Analytics(Model):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True)
    period_type = Column(String(32))
    period_value = Column(String(32))
    total_harvest = Column(Integer)
    top_crop = Column(String(128))
    top_crop_volume = Column(Integer)
    top_crop_id = Column(Integer)
    top_location = Column(String(255))
    top_location_volume = Column(Integer)

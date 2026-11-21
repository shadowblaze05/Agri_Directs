"""Analytics model."""

from sqlalchemy import ForeignKey, Integer, String

from ..base import Column, Model


class Analytics(Model):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True)
    period_type = Column(String(32))
    period_value = Column(String(32))
    total_harvest = Column(Integer)
    top_commodity = Column(String(128))
    top_commodity_volume = Column(Integer)
    top_commodity_id = Column(
        Integer,
        ForeignKey(
            "commodities.id",
            name="fk_analytics_top_commodity_id_commodities",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    top_location = Column(String(255))
    top_location_volume = Column(Integer)

"""Marketplace listing model."""

from sqlalchemy import Float, Integer, String, Text

from ..base import Column, Model


class MarketplaceListing(Model):
    __tablename__ = "marketplace"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    username = Column(String(128))
    buyer_username = Column(String(128))
    crop_id = Column(Integer)
    crop_name = Column(String(128))
    amount = Column(Integer)
    price = Column(Float)
    unit = Column(String(16), default="kg")
    status = Column(String(32), default="available")
    order_status = Column(String(32), default="available")
    listing_date = Column(String(32))
    order_date = Column(String(32))
    delivery_date = Column(String(32))
    expiry_date = Column(String(32))
    description = Column(Text)
    location = Column(String(255))
    delivery_confirmed = Column(Integer, default=0)
    buyer_confirmed = Column(Integer, default=0)
    buyer_confirm_date = Column(String(32))
    buyer_rating = Column(Integer)
    buyer_rating_date = Column(String(32))

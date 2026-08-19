"""Agriculture and inventory models."""

from sqlalchemy import Integer, String

from ..base import Column, Model


class Crop(Model):
    __tablename__ = "crops"

    id = Column(Integer, primary_key=True)
    crops_name = Column(String(128), unique=True)


class Harvest(Model):
    __tablename__ = "harvest"

    id = Column(Integer, primary_key=True)
    crop_id = Column(Integer)
    quantity = Column(Integer)
    farmer = Column(String(128))
    date_received = Column(String(32))
    location = Column(String(255))


class Inventory(Model):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    crop_name = Column(String(128))
    quantity = Column(Integer)
    farmer = Column(String(128))
    date_received = Column(String(32))
    location = Column(String(255))
    source = Column(String(32), default="harvest")

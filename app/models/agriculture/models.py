from sqlalchemy import ForeignKey, Integer, String, Text
from ..base import Column, Model


class Crop(Model):
    __tablename__ = "crops"

    id = Column(Integer, primary_key=True)
    crops_name = Column(String(128), unique=True, nullable=False)

    category_id = Column(
        Integer,
        ForeignKey("crop_categories.id"),
        nullable=True
    )


class Harvest(Model):
    __tablename__ = "harvest"

    id = Column(Integer, primary_key=True)

    crop_id = Column(
        Integer,
        ForeignKey("crops.id"),
        nullable=False
    )

    quantity = Column(Integer)
    farmer = Column(String(128))
    date_received = Column(String(32))
    location = Column(String(255))


class Inventory(Model):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)

    crop_id = Column(
        Integer,
        ForeignKey("crops.id"),
        nullable=False
    )

    quantity = Column(Integer)
    farmer = Column(String(128))
    date_received = Column(String(32))
    location = Column(String(255))
    source = Column(String(32), default="harvest")


class CropCategory(Model):
    __tablename__ = "crop_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False)
    description = Column(Text)
    

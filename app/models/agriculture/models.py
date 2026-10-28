from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
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
    pricing = relationship(
        "CropPricing",
        back_populates="crop",
        uselist=False,
        cascade="all, delete-orphan",
    )


class CropPricing(Model):
    __tablename__ = "crop_pricing"
    __table_args__ = (
        CheckConstraint(
            "pricing_mode IN ('range', 'bounds')",
            name="ck_crop_pricing_mode",
        ),
        CheckConstraint(
            "price_unit = 'kg'",
            name="ck_crop_pricing_unit",
        ),
        CheckConstraint(
            "(pricing_mode = 'range' AND reference_price > 0 "
            "AND price_range >= 0 AND reference_price > price_range "
            "AND minimum_price IS NULL "
            "AND maximum_price IS NULL) OR "
            "(pricing_mode = 'bounds' AND minimum_price > 0 "
            "AND maximum_price >= minimum_price AND price_range IS NULL "
            "AND (reference_price IS NULL OR reference_price BETWEEN "
            "minimum_price AND maximum_price))",
            name="ck_crop_pricing_values",
        ),
    )

    crop_id = Column(
        Integer,
        ForeignKey("crops.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pricing_mode = Column(String(16), nullable=False)
    price_unit = Column(String(16), nullable=False, default="kg", server_default="kg")
    reference_price = Column(Numeric(10, 2), nullable=True)
    price_range = Column(Numeric(10, 2), nullable=True)
    minimum_price = Column(Numeric(10, 2), nullable=True)
    maximum_price = Column(Numeric(10, 2), nullable=True)
    crop = relationship("Crop", back_populates="pricing")


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
    farmer_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_harvest_farmer_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
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
    crop_name = Column(String(128))
    farmer = Column(String(128))
    farmer_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_inventory_farmer_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    date_received = Column(String(32))
    location = Column(String(255))
    source = Column(String(32), default="harvest")
    photo_path = Column(String(255), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    capture_time = Column(DateTime(timezone=True), nullable=True)
    distance_from_user = Column(Float, nullable=True)
    verification_status = Column(String(32), default="pending", nullable=False)
    verification_notes = Column(Text, nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_inventory_reviewed_by_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)


class CropCategory(Model):
    __tablename__ = "crop_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False)
    description = Column(Text)
    

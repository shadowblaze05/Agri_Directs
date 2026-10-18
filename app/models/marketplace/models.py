"""Marketplace listing model."""

from sqlalchemy import Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

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
    delivery_province = Column(String(255), nullable=True)
    delivery_city = Column(String(255), nullable=True)
    delivery_barangay = Column(String(255), nullable=True)
    delivery_street = Column(String(255), nullable=True)
    delivery_landmark = Column(String(255), nullable=True)
    expiry_date = Column(String(32))
    description = Column(Text)
    location = Column(String(255))
    delivery_confirmed = Column(Integer, default=0)
    buyer_confirmed = Column(Integer, default=0)
    buyer_confirm_date = Column(String(32))
    buyer_rating = Column(Integer)
    buyer_rating_date = Column(String(32))
    main_image = Column(String(255), nullable=True)
    thumbnail_verified = Column(Integer, nullable=False, default=0)
    thumbnail_latitude = Column(Float, nullable=True)
    thumbnail_longitude = Column(Float, nullable=True)
    thumbnail_distance_meters = Column(Float, nullable=True)
    thumbnail_captured_at = Column(String(32), nullable=True)

# ============ PRE-ORDER FIELDS ============
    listing_type = Column(String(20), default="standard")   # 'standard' or 'preorder'
    available_date = Column(String(32), nullable=True)      # when crop will be ready
    preorder_status = Column(String(32), nullable=True)     # pending, confirmed, cancel_requested, cancelled, completed
    preorder_quantity = Column(Integer, nullable=True)      # reserved amount
    cancel_requested_by = Column(String(128), nullable=True)
    cancel_reason = Column(Text, nullable=True)
    cancel_requested_date = Column(String(32), nullable=True)
# ==========================================

# ============ NEW RELATIONSHIPS ============
    images = relationship("MarketplaceImage", backref="listing", cascade="all, delete-orphan")
    cart_items = relationship("Cart", backref="listing", cascade="all, delete-orphan")


# ============ NEW MODELS ============

class MarketplaceImage(Model):
    """Marketplace listing images"""
    __tablename__ = "marketplace_images"
    
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("marketplace.id", ondelete="CASCADE"), nullable=False)
    image_filename = Column(String(255), nullable=False)
    display_order = Column(Integer, default=0)
    created_at = Column(String(32))
    
    def get_image_url(self):
        return f"/static/uploads/marketplace/{self.image_filename}"


class Cart(Model):
    """Shopping cart model"""
    __tablename__ = "cart"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(Integer, ForeignKey("marketplace.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    added_date = Column(String(32))
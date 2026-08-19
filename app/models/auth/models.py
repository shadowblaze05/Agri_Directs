from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text
)

from ..base import Column, Model


class User(Model):
    __tablename__ = "users"

    # Primary key
    id = Column(
        Integer,
        primary_key=True
    )

    # Account information
    username = Column(
        String(128),
        unique=True,
        nullable=False
    )

    email = Column(
        String(255),
        unique=True,
        nullable=True
    )

    password = Column(
        Text,
        nullable=False
    )

    # Personal information
    first_name = Column(
        String(100),
        nullable=True
    )

    last_name = Column(
        String(100),
        nullable=True
    )

    phone_number = Column(
        String(20),
        nullable=True
    )

    # Profile
    profile_picture = Column(
        String(255),
        nullable=True
    )

    bio = Column(
        Text,
        nullable=True
    )

    # Account role and location
    role = Column(
        String(32),
        default="user",
        nullable=False
    )

    location = Column(
        String(255),
        nullable=True
    )

    # Verification
    is_verified = Column(
        Boolean,
        default=False,
        nullable=False
    )

    # Farmer reliability
    reliability_score = Column(
        Float
    )

    reliability_status = Column(
        String(64),
        default="Not Yet Rated"
    )

    completed_transactions = Column(
        Integer,
        default=0
    )

    cancelled_transactions = Column(
        Integer,
        default=0
    )

    total_transactions = Column(
        Integer,
        default=0
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

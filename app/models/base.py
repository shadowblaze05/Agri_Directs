"""Shared SQLAlchemy model base."""

from ..extensions import db

Model = db.Model
Column = db.Column

__all__ = ["db", "Model", "Column"]

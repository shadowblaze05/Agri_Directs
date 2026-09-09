"""Inventory and marketplace data adapters for market intelligence services."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from ....models.database import get_db


def normalize_records(records: Iterable[dict[str, Any]] | None):
    """Normalize raw rows into a stable structure expected by the services."""
    normalized = []
    for row in records or []:
        if row is None:
            continue
        crop_name = row.get("crop_name") or row.get("crops_name") or row.get("crop") or ""
        quantity = row.get("quantity") or row.get("total") or row.get("qty") or 0
        date_value = (
            row.get("date_received")
            or row.get("date")
            or row.get("received_at")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        location = row.get("location") or row.get("market_location") or ""
        normalized.append(
            {
                "crop_name": str(crop_name).strip(),
                "quantity": float(quantity) if isinstance(quantity, (int, float)) else float(quantity or 0),
                "date_received": str(date_value),
                "location": str(location).strip(),
            }
        )
    return normalized


def load_transaction_records():
    """Load the current inventory snapshot from the live app database."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.crops_name AS crop_name, i.quantity, i.date_received, i.location
        FROM inventory i
        LEFT JOIN crops c ON c.id = i.crop_id
        ORDER BY i.date_received DESC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return normalize_records(
        [{
            "crop_name": row["crop_name"],
            "quantity": row["quantity"],
            "date_received": row["date_received"],
            "location": row["location"],
        } for row in rows]
    )


def build_crop_history(records: Iterable[dict[str, Any]]):
    """Group records by crop and month for time-series forecasting."""
    crop_history = defaultdict(list)
    for row in normalize_records(records):
        if not row["crop_name"] or row["quantity"] <= 0:
            continue
        crop_history[row["crop_name"]].append(row)
    return crop_history

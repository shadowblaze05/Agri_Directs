"""Price-monitoring hooks and current market snapshot helpers."""

from __future__ import annotations

from typing import Any, Iterable

from .supply_data import aggregate_supply


def build_price_snapshot(records: Iterable[dict[str, Any]]):
    """Build a lightweight price-monitoring view from inventory observations."""
    summary = aggregate_supply(records)
    by_crop = summary["by_crop"]
    total_supply = summary["total_quantity"]
    price_items = []
    for crop, supply in sorted(by_crop.items()):
        share = (supply / total_supply) if total_supply else 0
        price_index = round(100 + (1 - share) * 40 + (supply / max(1, sum(by_crop.values()) / max(len(by_crop), 1))) * 5, 2)
        price_items.append(
            {
                "crop": crop,
                "current_supply": round(supply, 2),
                "price_index": max(60.0, min(190.0, price_index)),
                "trend": "Rising" if price_index > 110 else "Stable" if price_index > 95 else "Cooling",
                "signal": "Strong demand" if price_index > 120 else "Balanced" if price_index > 100 else "Pressure",
            }
        )
    return price_items

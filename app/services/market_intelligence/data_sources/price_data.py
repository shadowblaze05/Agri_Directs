"""Price-monitoring hooks and current market snapshot helpers."""

from __future__ import annotations

import math
from typing import Any, Iterable

from .supply_data import aggregate_supply


def _positive_price(value):
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def get_crop_reference_prices(records: Iterable[dict[str, Any]]):
    """Resolve each crop's configured reference price or bounds midpoint."""
    prices = {}
    for row in records or []:
        crop = (row or {}).get("crop_name") or ""
        if not crop or crop in prices:
            continue

        mode = row.get("pricing_mode")
        reference = _positive_price(row.get("reference_price"))
        if mode == "range" and reference is not None:
            prices[crop] = {
                "price": reference,
                "basis": "catalog_reference",
                "label": "Catalog reference",
                "unit": row.get("price_unit") or "kg",
            }
        elif mode == "bounds":
            minimum = _positive_price(row.get("minimum_price"))
            maximum = _positive_price(row.get("maximum_price"))
            if reference is not None:
                price = reference
                basis = "catalog_reference"
                label = "Catalog reference"
            elif minimum is not None and maximum is not None and maximum >= minimum:
                price = (minimum + maximum) / 2
                basis = "bounds_midpoint"
                label = "Bounds midpoint estimate"
            else:
                continue
            prices[crop] = {
                "price": price,
                "basis": basis,
                "label": label,
                "unit": row.get("price_unit") or "kg",
            }
    return prices


def build_price_snapshot(records: Iterable[dict[str, Any]]):
    """Build a configured-price comparison for crops in current inventory."""
    records = list(records or [])
    summary = aggregate_supply(records)
    by_crop = summary["by_crop"]
    crop_prices = get_crop_reference_prices(records)
    priced_crops = {
        crop: crop_prices[crop]["price"]
        for crop in by_crop
        if crop in crop_prices
    }
    average_price = (
        sum(priced_crops.values()) / len(priced_crops)
        if priced_crops
        else None
    )

    price_items = []
    for crop, supply in sorted(by_crop.items()):
        crop_price = crop_prices.get(crop)
        price = crop_price["price"] if crop_price else None
        price_index = (
            round(price / average_price * 100, 2)
            if price is not None and average_price
            else None
        )
        comparison = (
            round((price / average_price - 1) * 100, 2)
            if price is not None and average_price
            else None
        )
        if price is None:
            signal = "No catalog price"
        elif abs(price - average_price) < 0.005:
            signal = "At configured average"
        elif price > average_price:
            signal = "Above configured average"
        else:
            signal = "Below configured average"

        price_items.append(
            {
                "crop": crop,
                "current_supply": round(supply, 2),
                "current_price": round(price, 2) if price is not None else None,
                "price_unit": crop_price["unit"] if crop_price else "kg",
                "price_basis": crop_price["basis"] if crop_price else None,
                "price_basis_label": crop_price["label"] if crop_price else "Unavailable",
                "price_index": price_index,
                "comparison_to_average_percent": comparison,
                "trend": crop_price["label"] if crop_price else "Unavailable",
                "signal": signal,
            }
        )
    return price_items

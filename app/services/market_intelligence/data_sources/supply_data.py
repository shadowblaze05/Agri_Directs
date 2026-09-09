"""Supply aggregation helpers for inventory-based market intelligence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def aggregate_supply(records: Iterable[dict[str, Any]]):
    """Aggregate inventory by crop and month to support threshold logic."""
    by_crop = defaultdict(float)
    monthly = defaultdict(float)
    for row in records or []:
        crop = (row or {}).get("crop_name") or ""
        quantity = float((row or {}).get("quantity") or 0)
        if not crop or quantity <= 0:
            continue
        by_crop[crop] += quantity
        month = str((row or {}).get("date_received") or "").split(" ", 1)[0][:7]
        if month:
            monthly[month] += quantity
    return {
        "by_crop": dict(sorted(by_crop.items())),
        "monthly": dict(sorted(monthly.items())),
        "total_quantity": sum(by_crop.values()),
    }

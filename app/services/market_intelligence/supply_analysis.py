"""Dynamic threshold supply analysis for market intelligence."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from .data_sources.price_data import build_price_snapshot


class SupplyAnalysisService:
    """Derive risk signals and threshold-bound supply classifications from inventory values."""

    @staticmethod
    def _crop_totals(records):
        totals = {}
        for row in records or []:
            crop = (row or {}).get("crop_name") or ""
            quantity = float((row or {}).get("quantity") or 0)
            if not crop or quantity <= 0:
                continue
            totals[crop] = totals.get(crop, 0.0) + quantity
        return totals

    @staticmethod
    def _thresholds(values):
        array = np.asarray(values, dtype=float)
        if array.size == 0:
            return {"lower": 0.0, "upper": 0.0, "mean": 0.0}
        mean = float(array.mean())
        std = float(array.std(ddof=1)) if array.size > 1 else 0.0
        return {"lower": max(0.0, mean - std), "upper": mean + std, "mean": mean}

    def analyze(self, records: Iterable[dict[str, Any]]):
        totals = self._crop_totals(records)
        price_monitoring = build_price_snapshot(records)
        risk_alerts = []
        price_summary = []

        for crop, total in sorted(totals.items()):
            values = []
            for row in records or []:
                if (row or {}).get("crop_name") == crop:
                    values.append(float((row or {}).get("quantity") or 0))
            thresholds = self._thresholds(values)
            current = total
            lower = thresholds["lower"]
            upper = thresholds["upper"]
            if current <= lower * 0.8:
                signal = "critical_shortage"
                severity = "high"
                message = f"{crop} has fallen well below its dynamic supply threshold."
            elif current < lower:
                signal = "undersupply"
                severity = "medium"
                message = f"{crop} is below the expected lower threshold for the current cycle."
            elif current > upper * 1.25:
                signal = "oversupply"
                severity = "high"
                message = f"{crop} is above the dynamic oversupply threshold and may pressure prices."
            elif current > upper:
                signal = "high_supply"
                severity = "medium"
                message = f"{crop} is trending above the normal range for this period."
            else:
                signal = "balanced"
                severity = "low"
                message = f"{crop} remains within the expected dynamic supply band."

            risk_alerts.append({"crop": crop, "type": signal, "severity": severity, "message": message})
            price_summary.append(
                {
                    "crop": crop,
                    "current_supply": round(current, 2),
                    "average_supply": round(thresholds["mean"], 2),
                    "threshold_low": round(lower, 2),
                    "threshold_high": round(upper, 2),
                    "status": signal,
                }
            )

        market_pressure = "balanced"
        if any(alert["type"] in {"oversupply", "critical_shortage"} for alert in risk_alerts):
            market_pressure = "oversupply" if any(alert["type"] == "oversupply" for alert in risk_alerts) else "undersupply"
        elif any(alert["type"] in {"undersupply", "high_supply"} for alert in risk_alerts):
            market_pressure = "undersupply" if any(alert["type"] == "undersupply" for alert in risk_alerts) else "balanced"

        return {
            "summary": {
                "total_quantity": round(float(sum(totals.values())), 2),
                "active_crops": len(totals),
                "average_monthly_supply": round(float(sum(totals.values()) / max(len(totals), 1)), 2),
                "market_pressure": market_pressure,
            },
            "by_crop": totals,
            "price_monitoring": price_monitoring,
            "risk_alerts": risk_alerts,
            "thresholds": price_summary,
        }

"""Market intelligence service package."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .crop_recommendation import CropRecommendationService
from .criteria_builder import build_criteria_weights
from .data_sources.supply_data import aggregate_supply
from .data_sources.transaction_data import load_transaction_records, normalize_records
from .demand_baseline import DemandBaselineService
from .demand_forecasting import DemandForecastingService
from .supply_analysis import SupplyAnalysisService


def analyze_market_intelligence(records: Iterable[dict[str, Any]] | None = None):
    """Run the service stack against the live inventory data and return a market view."""
    normalized = normalize_records(records) if records is not None else load_transaction_records()
    supply = SupplyAnalysisService().analyze(normalized)
    forecast = DemandForecastingService().forecast(normalized)
    baseline = DemandBaselineService().evaluate(normalized)
    recommendation = CropRecommendationService().recommend(
        normalized,
        supply_summary=supply.get("by_crop", {}),
        forecast_summary=forecast.get("forecast", []),
    )

    total_quantity = sum(float(value) for value in supply.get("by_crop", {}).values())
    summary = {
        "total_quantity": round(total_quantity, 2),
        "active_crops": len(supply.get("by_crop", {})),
        "average_monthly_supply": round(total_quantity / max(len(supply.get("by_crop", {})) or 1, 1), 2),
        "market_pressure": supply["summary"]["market_pressure"],
        "current_month": datetime.now().strftime("%B"),
    }

    return {
        "summary": summary,
        "price_monitoring": supply.get("price_monitoring", []),
        "risk_alerts": supply.get("risk_alerts", []),
        "recommendations": recommendation.get("recommendations", []),
        "forecast": forecast.get("forecast", []),
        "baseline": baseline.get("baseline", {}),
        "criteria_weights": recommendation.get("criteria_weights", build_criteria_weights()),
    }


__all__ = [
    "analyze_market_intelligence",
    "SupplyAnalysisService",
    "DemandForecastingService",
    "DemandBaselineService",
    "CropRecommendationService",
    "build_criteria_weights",
    "normalize_records",
    "load_transaction_records",
    "aggregate_supply",
]

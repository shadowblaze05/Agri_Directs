from __future__ import annotations
from typing import Any, Iterable
import numpy as np

from .criteria_builder import CriteriaBuilder
from .data_sources.price_data import get_crop_reference_prices


def topsis_method(dataset, weights, criterion_type, graph=True, verbose=True):
    """Compute TOPSIS scores without importing the full pyDecision library."""
    dataset = np.asarray(dataset, dtype=float)
    weights = np.asarray(weights, dtype=float)
    criterion_type = list(criterion_type)

    if dataset.shape[1] != len(weights):
        raise ValueError("TOPSIS weights count must match the number of criteria")

    column_norms = np.linalg.norm(dataset, axis=0)
    column_norms[column_norms == 0] = 1.0
    weighted = dataset / column_norms * weights

    positive_ideal = []
    negative_ideal = []
    for idx in range(weighted.shape[1]):
        if criterion_type[idx] == "max":
            positive_ideal.append(np.max(weighted[:, idx]))
            negative_ideal.append(np.min(weighted[:, idx]))
        else:
            positive_ideal.append(np.min(weighted[:, idx]))
            negative_ideal.append(np.max(weighted[:, idx]))

    positive_ideal = np.asarray(positive_ideal)
    negative_ideal = np.asarray(negative_ideal)

    positive_distance = np.linalg.norm(weighted - positive_ideal, axis=1)
    negative_distance = np.linalg.norm(weighted - negative_ideal, axis=1)
    distance_sum = positive_distance + negative_distance
    scores = np.divide(
        negative_distance,
        distance_sum,
        out=np.full_like(distance_sum, 0.5),
        where=distance_sum > 0,
    )
    return scores


class CropRecommendationService:
    """Rank crops using weighted multi-criteria scoring with AHP-constrained weights."""

    def __init__(self):
        self.criteria_builder = CriteriaBuilder()

    @staticmethod
    def _metric_row(
        crop_name,
        records,
        supply_summary,
        forecast_summary,
        price_opportunity,
    ):
        demand = 0.0
        stability = 0.0
        seasonal = 0.0
        risk = 0.0

        crop_rows = [row for row in records or [] if (row or {}).get("crop_name") == crop_name]
        if crop_rows:
            quantity_values = [float((row or {}).get("quantity") or 0) for row in crop_rows]
            total_quantity = sum(quantity_values)
            average_quantity = sum(quantity_values) / max(len(quantity_values), 1)
            demand = min(1.0, total_quantity / max(average_quantity * 2, 1.0))
            stability = max(0.0, 1.0 - (max(quantity_values) - min(quantity_values)) / max(max(quantity_values), 1.0, average_quantity))
            risk = max(0.0, 1.0 - (abs(total_quantity - average_quantity) / max(total_quantity, average_quantity, 1.0)))
        else:
            demand = 0.0
            stability = 0.0
            risk = 0.0

        forecast_entry = next((item for item in forecast_summary if item["crop"] == crop_name), None)
        if forecast_entry:
            forecast_quantity = float(forecast_entry["forecast_quantity"])
            seasonal = min(1.0, forecast_quantity / max(sum(item["forecast_quantity"] for item in forecast_summary if item["crop"] != crop_name) + 1, 1.0))
        else:
            seasonal = 0.5

        supply_total = supply_summary.get(crop_name, 0.0)
        supply_score = min(1.0, supply_total / max(supply_summary.values() or [1.0])) if supply_summary else 0.0
        return np.array(
            [
                demand,
                stability,
                seasonal,
                price_opportunity,
                1.0 - max(0.0, abs(supply_score - risk)),
            ],
            dtype=float,
        )

    def recommend(self, records: Iterable[dict[str, Any]], supply_summary=None, forecast_summary=None):
        records = list(records or [])
        supply_summary = supply_summary or {}
        forecast_summary = forecast_summary or []
        crop_names = sorted({(row or {}).get("crop_name") for row in records if (row or {}).get("crop_name")})
        matrix = []
        reference_prices = get_crop_reference_prices(records)
        known_prices = [
            reference_prices[crop]["price"]
            for crop in crop_names
            if crop in reference_prices
        ]
        minimum_price = min(known_prices) if known_prices else None
        maximum_price = max(known_prices) if known_prices else None
        price_opportunities = {}
        for crop_name in crop_names:
            crop_price = reference_prices.get(crop_name)
            if crop_price is None or minimum_price is None or maximum_price is None:
                price_opportunity = 0.5
            elif maximum_price == minimum_price:
                price_opportunity = 0.5
            else:
                price_opportunity = (
                    crop_price["price"] - minimum_price
                ) / (maximum_price - minimum_price)
            price_opportunities[crop_name] = price_opportunity
            matrix.append(
                self._metric_row(
                    crop_name,
                    records,
                    supply_summary,
                    forecast_summary,
                    price_opportunity,
                )
            )
        if not matrix:
            return {"recommendations": [], "criteria_weights": self.criteria_builder.as_dict()}

        weights = self.criteria_builder.as_array()
        scores = topsis_method(np.asarray(matrix), weights, self.criteria_builder.criterion_types, graph=False, verbose=False)
        ranked = sorted(
            [
                {
                    "crop": crop_name,
                    "score": round(float(score), 4),
                    "reason": "Strong demand and favorable market conditions.",
                    "reference_price": (
                        round(reference_prices[crop_name]["price"], 2)
                        if crop_name in reference_prices
                        else None
                    ),
                    "price_basis": (
                        reference_prices[crop_name]["basis"]
                        if crop_name in reference_prices
                        else None
                    ),
                    "price_opportunity": round(price_opportunities[crop_name], 4),
                }
                for crop_name, score in zip(crop_names, scores)
            ],
            key=lambda item: item["score"],
            reverse=True,
        )
        for item in ranked:
            if item["reference_price"] is None:
                price_context = "No catalog price is configured, so the price criterion is neutral."
            elif item["price_basis"] == "bounds_midpoint":
                price_context = (
                    f"The price criterion uses an estimated bounds midpoint of "
                    f"₱{item['reference_price']:.2f}/kg."
                )
            else:
                price_context = (
                    f"The price criterion uses a catalog reference of "
                    f"₱{item['reference_price']:.2f}/kg."
                )
            item["reason"] = (
                f"Weighted multi-criteria score indicates {item['crop']} remains "
                f"competitive in the current cycle. {price_context}"
            )
        return {"recommendations": ranked, "criteria_weights": self.criteria_builder.as_dict()}

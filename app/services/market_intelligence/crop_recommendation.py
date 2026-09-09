"""Crop recommendation service combining AHP and TOPSIS scoring."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from .criteria_builder import CriteriaBuilder


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
    scores = negative_distance / (positive_distance + negative_distance)
    scores = np.nan_to_num(scores, nan=0.0)
    return scores


class CropRecommendationService:
    """Rank crops using weighted multi-criteria scoring with AHP-constrained weights."""

    def __init__(self):
        self.criteria_builder = CriteriaBuilder()

    @staticmethod
    def _metric_row(crop_name, records, supply_summary, forecast_summary):
        demand = 0.0
        stability = 0.0
        seasonal = 0.0
        price = 0.0
        risk = 0.0

        crop_rows = [row for row in records or [] if (row or {}).get("crop_name") == crop_name]
        if crop_rows:
            quantity_values = [float((row or {}).get("quantity") or 0) for row in crop_rows]
            total_quantity = sum(quantity_values)
            average_quantity = sum(quantity_values) / max(len(quantity_values), 1)
            demand = min(1.0, total_quantity / max(average_quantity * 2, 1.0))
            stability = max(0.0, 1.0 - (max(quantity_values) - min(quantity_values)) / max(max(quantity_values), 1.0, average_quantity))
            price = min(1.0, (max(quantity_values) / max(total_quantity, 1.0)) + 0.25)
            risk = max(0.0, 1.0 - (abs(total_quantity - average_quantity) / max(total_quantity, average_quantity, 1.0)))
        else:
            demand = 0.0
            stability = 0.0
            price = 0.0
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
            [demand, stability, seasonal, price, 1.0 - max(0.0, abs(supply_score - risk))],
            dtype=float,
        )

    def recommend(self, records: Iterable[dict[str, Any]], supply_summary=None, forecast_summary=None):
        supply_summary = supply_summary or {}
        forecast_summary = forecast_summary or []
        crop_names = sorted({(row or {}).get("crop_name") for row in records or [] if (row or {}).get("crop_name")})
        matrix = []
        for crop_name in crop_names:
            matrix.append(self._metric_row(crop_name, records, supply_summary, forecast_summary))
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
                }
                for crop_name, score in zip(crop_names, scores)
            ],
            key=lambda item: item["score"],
            reverse=True,
        )
        for item in ranked:
            item["reason"] = f"Weighted multi-criteria score indicates {item['crop']} remains highly competitive in the current cycle."
        return {"recommendations": ranked, "criteria_weights": self.criteria_builder.as_dict()}

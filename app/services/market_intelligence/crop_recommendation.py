from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
import numpy as np

from .criteria_builder import CriteriaBuilder
from .data_sources.price_data import get_crop_reference_prices

_CLIMATE_SEASONS = (
    ("Cool dry season", "Dec-Feb", {12, 1, 2}),
    ("Hot dry season", "Mar-May", {3, 4, 5}),
    ("Rainy season", "Jun-Nov", {6, 7, 8, 9, 10, 11}),
)
_PHILIPPINE_TIMEZONE = timezone(timedelta(hours=8))
_YEAR_ROUND_TOLERANCE = 0.20


def _seasonal_fit(records, crop_name, month=None):
    month = month or datetime.now(_PHILIPPINE_TIMEZONE).month
    current_season = next(
        index
        for index, (_, _, months) in enumerate(_CLIMATE_SEASONS)
        if month in months
    )
    season_year_totals = {}

    for row in records or []:
        if (row or {}).get("crop_name") != crop_name:
            continue
        date_value = (row or {}).get("date_received")
        if not date_value:
            continue
        try:
            record_date = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if record_date.tzinfo is not None:
            record_date = record_date.astimezone(_PHILIPPINE_TIMEZONE)
        quantity = float((row or {}).get("quantity") or 0)
        if quantity <= 0:
            continue
        season = next(
            index
            for index, (_, _, months) in enumerate(_CLIMATE_SEASONS)
            if record_date.month in months
        )
        season_year = record_date.year - int(season == 0 and record_date.month != 12)
        key = (season, season_year)
        season_year_totals[key] = season_year_totals.get(key, 0.0) + quantity

    season_name, month_range, _ = _CLIMATE_SEASONS[current_season]
    label_prefix = f"{season_name} ({month_range})"
    observed_seasons = {season for season, _ in season_year_totals}
    if len(observed_seasons) < len(_CLIMATE_SEASONS):
        return 0.5, f"{label_prefix} - Insufficient history"

    season_monthly_averages = [[] for _ in _CLIMATE_SEASONS]
    for (season, _), total in season_year_totals.items():
        months_in_season = len(_CLIMATE_SEASONS[season][2])
        season_monthly_averages[season].append(total / months_in_season)
    seasonal_averages = [
        sum(year_values) / len(year_values)
        for year_values in season_monthly_averages
    ]
    average_seasonal_quantity = sum(seasonal_averages) / len(_CLIMATE_SEASONS)
    fit_score = min(
        1.0,
        seasonal_averages[current_season] / (2 * average_seasonal_quantity),
    )
    is_year_round = average_seasonal_quantity > 0 and all(
        abs(seasonal_average - average_seasonal_quantity)
        <= average_seasonal_quantity * _YEAR_ROUND_TOLERANCE
        for seasonal_average in seasonal_averages
    )
    fit_label = (
        "Year-round availability"
        if is_year_round
        else "Favorable"
        if fit_score >= 0.5
        else "Watch"
    )
    return fit_score, f"{label_prefix} - {fit_label}"


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
        price_opportunity,
        seasonal_fit_score,
    ):
        demand = 0.0
        stability = 0.0
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

        supply_total = supply_summary.get(crop_name, 0.0)
        supply_score = min(1.0, supply_total / max(supply_summary.values() or [1.0])) if supply_summary else 0.0
        return np.array(
            [
                demand,
                stability,
                seasonal_fit_score,
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
        seasonal_fits = {
            crop_name: _seasonal_fit(records, crop_name)
            for crop_name in crop_names
        }
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
                    price_opportunity,
                    seasonal_fits[crop_name][0],
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
                    "seasonal_fit": seasonal_fits[crop_name][1],
                    "seasonal_fit_score": round(seasonal_fits[crop_name][0], 4),
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

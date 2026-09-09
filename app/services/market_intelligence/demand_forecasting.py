"""Demand forecasting service using ARIMA with linear fallback."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
from statsmodels.tsa.arima.model import ARIMA


class DemandForecastingService:
    """Forecast crop demand trends from the historical inventory series."""

    @staticmethod
    def _series_for_crop(records, crop_name):
        history = []
        for row in records or []:
            if (row or {}).get("crop_name") != crop_name:
                continue
            value = float((row or {}).get("quantity") or 0)
            if value > 0:
                history.append(value)
        return history

    @staticmethod
    def _forecast_single(values):
        values = [float(value) for value in values if value is not None]
        if not values:
            return 0.0, "insufficient-data"
        if len(values) == 1:
            return float(values[-1]), "fallback-linear"

        try:
            series = pd.Series(values, dtype=float)
            model = ARIMA(series, order=(1, 0, 0))
            result = model.fit()
            forecast_value = float(result.forecast(steps=1)[0])
            return max(0.0, forecast_value), "arima"
        except Exception:
            slope = 0.0
            if len(values) > 1:
                slope = (values[-1] - values[-2]) / max(1.0, abs(values[-2]))
            forecast_value = values[-1] + slope * max(1.0, len(values) / 2)
            return max(0.0, float(forecast_value)), "fallback-linear"

    def forecast(self, records):
        crop_names = sorted({(row or {}).get("crop_name") for row in records or [] if (row or {}).get("crop_name")})
        items = []
        for crop_name in crop_names:
            values = self._series_for_crop(records, crop_name)
            forecast_value, method = self._forecast_single(values)
            items.append(
                {
                    "crop": crop_name,
                    "forecast_quantity": round(forecast_value, 2),
                    "method": method,
                    "latest_value": round(float(values[-1]), 2) if values else 0.0,
                }
            )
        return {"forecast": sorted(items, key=lambda item: item["forecast_quantity"], reverse=True)}

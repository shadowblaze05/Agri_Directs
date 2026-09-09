"""Baseline demand comparison based on ordinary least squares."""

from __future__ import annotations

from typing import Iterable

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score


class DemandBaselineService:
    """Build OLS baselines to compare the ARIMA forecast against simple trend behavior."""

    @staticmethod
    def calculate(series: Iterable[float]):
        values = [float(value) for value in series if value is not None]
        if not values:
            return {"baseline_quantity": 0.0, "slope": 0.0, "r_squared": 0.0}
        if len(values) == 1:
            return {"baseline_quantity": float(values[-1]), "slope": 0.0, "r_squared": 1.0}

        x_values = np.arange(len(values), dtype=float).reshape(-1, 1)
        y_values = np.asarray(values, dtype=float)
        model = LinearRegression()
        model.fit(x_values, y_values)
        next_point = np.array([[len(values)]])
        baseline_quantity = float(max(0.0, model.predict(next_point)[0]))
        return {
            "baseline_quantity": baseline_quantity,
            "slope": float(model.coef_[0]),
            "r_squared": float(r2_score(y_values, model.predict(x_values))),
        }

    def evaluate(self, records):
        crop_series = {}
        for row in records or []:
            crop = (row or {}).get("crop_name") or ""
            quantity = float((row or {}).get("quantity") or 0)
            if not crop or quantity <= 0:
                continue
            crop_series.setdefault(crop, []).append(quantity)

        baseline = {}
        for crop, values in sorted(crop_series.items()):
            baseline[crop] = self.calculate(values)
        return {"baseline": baseline}

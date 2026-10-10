import warnings

import numpy as np
import pytest
from statsmodels.tools.sm_exceptions import ConvergenceWarning, EstimationWarning

from app.services.market_intelligence import crop_recommendation, demand_forecasting
from app.services.market_intelligence.crop_recommendation import topsis_method
from app.services.market_intelligence.demand_forecasting import DemandForecastingService


def test_topsis_identical_candidates_receive_neutral_scores_without_warnings():
    dataset = np.array([[0.5, 0.5], [0.5, 0.5]])

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        scores = topsis_method(dataset, [0.5, 0.5], ["max", "max"])

    np.testing.assert_array_equal(scores, [0.5, 0.5])


@pytest.mark.parametrize("warning_type", [EstimationWarning, ConvergenceWarning])
def test_arima_warnings_use_linear_fallback_without_leaking_warning(
    monkeypatch, warning_type
):
    class WarningModel:
        def fit(self):
            warnings.warn("ARIMA fit is not reliable", warning_type)

    monkeypatch.setattr(
        demand_forecasting,
        "ARIMA",
        lambda *_args, **_kwargs: WarningModel(),
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        forecast, method = DemandForecastingService._forecast_single([1, 3, 2, 5])

    assert method == "fallback-linear"
    assert forecast == 8.0


def test_constant_demand_uses_linear_fallback_without_arima(monkeypatch):
    monkeypatch.setattr(
        demand_forecasting,
        "ARIMA",
        lambda *_args, **_kwargs: pytest.fail("ARIMA should not fit constant data"),
    )

    assert DemandForecastingService._forecast_single([4, 4, 4]) == (4.0, "fallback-linear")


def test_crop_recommendations_remain_finite_for_identical_crop_metrics():
    service = crop_recommendation.CropRecommendationService()
    records = [
        {"crop_name": "Rice", "quantity": 5},
        {"crop_name": "Corn", "quantity": 5},
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = service.recommend(records)

    assert [item["score"] for item in result["recommendations"]] == [0.5, 0.5]

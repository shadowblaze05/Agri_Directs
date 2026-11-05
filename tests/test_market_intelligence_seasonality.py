import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import home as home_routes
from app.services.market_intelligence import crop_recommendation
from app.services.market_intelligence.crop_recommendation import (
    CropRecommendationService,
)


def seasonal_records(current_season, current_quantity):
    season_for_month = {
        12: 0,
        1: 0,
        2: 0,
        3: 1,
        4: 1,
        5: 1,
        6: 2,
        7: 2,
        8: 2,
        9: 2,
        10: 2,
        11: 2,
    }
    records = []
    for offset in range(12):
        year = 2024 if offset == 0 else 2025
        month = 12 if offset == 0 else offset
        season = season_for_month[month]
        records.append({
            "crop_name": "Rice",
            "quantity": current_quantity if season == current_season else 10,
            "date_received": f"{year}-{month:02d}-15",
        })
    return records


def test_current_climate_season_fit_uses_observed_crop_history(monkeypatch):
    current_month = datetime.now().month
    current_season = 0 if current_month in {12, 1, 2} else 1 if current_month in {3, 4, 5} else 2
    records = seasonal_records(current_season, 100)

    fit_score, label = crop_recommendation._seasonal_fit(
        records,
        "Rice",
        month=current_month,
    )

    assert fit_score == 1.0
    assert label.startswith(crop_recommendation._CLIMATE_SEASONS[current_season][0])
    assert label.endswith("Favorable")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, current_month, 1)

    monkeypatch.setattr(crop_recommendation, "datetime", FixedDateTime)
    recommendation = CropRecommendationService().recommend(records)["recommendations"][0]

    assert recommendation["seasonal_fit"] == label
    assert recommendation["seasonal_fit_score"] == 1.0


def test_seasonal_fit_is_neutral_without_all_climate_season_history():
    fit_score, label = crop_recommendation._seasonal_fit(
        [
            {"crop_name": "Rice", "quantity": 10, "date_received": "2025-01-15"},
            {"crop_name": "Rice", "quantity": 20, "date_received": "2025-11-15"},
        ],
        "Rice",
        month=12,
    )

    assert fit_score == 0.5
    assert label == "Cool dry season (Dec-Feb) - Insufficient history"


def test_similar_monthly_supply_across_seasons_is_labeled_year_round():
    records = [
        {
            "crop_name": "Chicken",
            "quantity": 100,
            "date_received": (
                "2024-12-15"
                if offset == 0
                else f"2025-{offset:02d}-15"
            ),
        }
        for offset in range(12)
    ]

    fit_score, label = crop_recommendation._seasonal_fit(
        records,
        "Chicken",
        month=12,
    )

    assert fit_score == 0.5
    assert label == "Cool dry season (Dec-Feb) - Year-round availability"


def test_year_round_classification_uses_twenty_percent_threshold():
    records = []
    for offset in range(12):
        year = 2024 if offset == 0 else 2025
        month = 12 if offset == 0 else offset
        season = (
            0 if month in {12, 1, 2}
            else 1 if month in {3, 4, 5}
            else 2
        )
        quantity = (85, 100, 115)[season]
        records.append({
            "crop_name": "Chicken",
            "quantity": quantity,
            "date_received": f"{year}-{month:02d}-15",
        })

    _, label = crop_recommendation._seasonal_fit(records, "Chicken", month=4)
    assert label.endswith("Year-round availability")

    for row in records:
        month = int(row["date_received"][5:7])
        season = (
            0 if month in {12, 1, 2}
            else 1 if month in {3, 4, 5}
            else 2
        )
        row["quantity"] = (70, 100, 130)[season]
    _, label = crop_recommendation._seasonal_fit(records, "Chicken", month=4)
    assert label.endswith("Favorable")


def test_recommendations_page_shows_seasonal_fit_not_overall_score(monkeypatch):
    monkeypatch.setattr(
        home_routes,
        "_market_analysis_context",
        lambda: {
            "recommendations": [
                {
                    "crop": "Rice",
                    "score": 0.95,
                    "seasonal_fit": "Rainy season (Jun-Nov) - Watch",
                }
            ]
        },
    )
    monkeypatch.setattr(
        home_routes,
        "get_active_user_role",
        lambda *_args: "admin",
    )

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"
        response = client.get("/market-intelligence/crop-recommendations")

    assert response.status_code == 200
    assert b"Rainy season (Jun-Nov) - Watch" in response.data


def test_pagasa_season_month_boundaries():
    expected_seasons = {
        12: "Cool dry season",
        1: "Cool dry season",
        2: "Cool dry season",
        3: "Hot dry season",
        4: "Hot dry season",
        5: "Hot dry season",
        6: "Rainy season",
        7: "Rainy season",
        8: "Rainy season",
        9: "Rainy season",
        10: "Rainy season",
        11: "Rainy season",
    }
    for month, expected_name in expected_seasons.items():
        _, label = crop_recommendation._seasonal_fit([], "Rice", month=month)
        assert label.startswith(expected_name)


def test_timestamp_season_uses_philippine_local_month():
    fit_score, label = crop_recommendation._seasonal_fit(
        [
            {"crop_name": "Rice", "quantity": 10, "date_received": "2025-11-30T16:30:00+00:00"},
            {"crop_name": "Rice", "quantity": 10, "date_received": "2025-03-31T16:30:00+00:00"},
            {"crop_name": "Rice", "quantity": 10, "date_received": "2025-05-31T16:30:00+00:00"},
        ],
        "Rice",
        month=12,
    )

    assert fit_score == 0.6
    assert label == "Cool dry season (Dec-Feb) - Favorable"

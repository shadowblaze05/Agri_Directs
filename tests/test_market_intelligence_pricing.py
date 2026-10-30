import app as app_module
from app.routes import home as home_routes
from app.services.market_intelligence.crop_recommendation import (
    CropRecommendationService,
)
from app.services.market_intelligence.data_sources.price_data import (
    build_price_snapshot,
    get_crop_reference_prices,
)
from app.services.market_intelligence import analyze_market_intelligence


def test_price_snapshot_uses_catalog_reference_and_bounds_midpoint():
    records = [
        {
            "crop_name": "Rice",
            "quantity": 10,
            "pricing_mode": "range",
            "reference_price": 20,
            "price_range": 3,
            "price_unit": "kg",
        },
        {
            "crop_name": "Corn",
            "quantity": 10,
            "pricing_mode": "bounds",
            "minimum_price": 30,
            "maximum_price": 50,
            "price_unit": "kg",
        },
        {"crop_name": "Beans", "quantity": 10},
    ]

    snapshot = {item["crop"]: item for item in build_price_snapshot(records)}

    assert snapshot["Rice"]["current_price"] == 20
    assert snapshot["Rice"]["price_basis"] == "catalog_reference"
    assert snapshot["Corn"]["current_price"] == 40
    assert snapshot["Corn"]["price_basis"] == "bounds_midpoint"
    assert snapshot["Beans"]["current_price"] is None
    assert snapshot["Beans"]["signal"] == "No catalog price"
    assert snapshot["Rice"]["price_index"] == 66.67
    assert snapshot["Corn"]["price_index"] == 133.33


def test_bounds_reference_price_takes_precedence_over_midpoint():
    prices = get_crop_reference_prices(
        [
            {
                "crop_name": "Tomato",
                "pricing_mode": "bounds",
                "reference_price": 25,
                "minimum_price": 20,
                "maximum_price": 40,
            }
        ]
    )

    assert prices["Tomato"] == {
        "price": 25,
        "basis": "catalog_reference",
        "label": "Catalog reference",
        "unit": "kg",
    }


def test_configured_price_changes_recommendation_price_criterion():
    records = [
        {
            "crop_name": "Rice",
            "quantity": 10,
            "pricing_mode": "range",
            "reference_price": 20,
        },
        {
            "crop_name": "Corn",
            "quantity": 10,
            "pricing_mode": "range",
            "reference_price": 40,
        },
    ]

    result = CropRecommendationService().recommend(records)
    recommendations = {item["crop"]: item for item in result["recommendations"]}

    assert recommendations["Corn"]["score"] > recommendations["Rice"]["score"]
    assert recommendations["Corn"]["reference_price"] == 40
    assert "₱40.00/kg" in recommendations["Corn"]["reason"]


def test_market_analysis_output_uses_catalog_prices():
    analysis = analyze_market_intelligence(
        [
            {
                "crop_name": "Rice",
                "quantity": 10,
                "pricing_mode": "range",
                "reference_price": 20,
            },
            {
                "crop_name": "Corn",
                "quantity": 10,
                "pricing_mode": "bounds",
                "minimum_price": 30,
                "maximum_price": 50,
            },
        ]
    )

    price_monitoring = {
        item["crop"]: item for item in analysis["price_monitoring"]
    }
    recommendations = {
        item["crop"]: item for item in analysis["recommendations"]
    }

    assert price_monitoring["Rice"]["current_price"] == 20
    assert price_monitoring["Corn"]["current_price"] == 40
    assert price_monitoring["Corn"]["price_basis"] == "bounds_midpoint"
    assert recommendations["Corn"]["score"] > recommendations["Rice"]["score"]


def test_missing_catalog_price_is_reported_as_neutral():
    result = CropRecommendationService().recommend(
        [
            {"crop_name": "Rice", "quantity": 10},
            {
                "crop_name": "Corn",
                "quantity": 10,
                "pricing_mode": "range",
                "reference_price": 40,
            },
        ]
    )
    rice = next(item for item in result["recommendations"] if item["crop"] == "Rice")

    assert rice["reference_price"] is None
    assert rice["price_opportunity"] == 0.5
    assert "price criterion is neutral" in rice["reason"]


def test_price_monitoring_page_displays_price_and_basis(monkeypatch):
    monkeypatch.setattr(
        home_routes,
        "_market_analysis_context",
        lambda: {
            "summary": {
                "total_quantity": 10,
                "active_crops": 1,
                "market_pressure": "balanced",
            },
            "price_monitoring": [
                {
                    "crop": "Corn",
                    "current_price": 40,
                    "price_unit": "kg",
                    "price_basis_label": "Bounds midpoint estimate",
                    "comparison_to_average_percent": 0.0,
                    "price_index": 100,
                    "signal": "At configured average",
                }
            ],
        },
    )
    monkeypatch.setattr(
        home_routes, "get_active_user_role", lambda *_args: "admin"
    )

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        response = client.get("/market-intelligence/price-monitoring")

    assert response.status_code == 200
    assert "₱40.00/kg".encode() in response.data
    assert b"Bounds midpoint estimate" in response.data

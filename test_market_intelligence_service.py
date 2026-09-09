from app.services.market_intelligence import analyze_market_intelligence
from app.services.market_intelligence.supply_analysis import SupplyAnalysisService


def test_service_layer_generates_market_analysis():
    records = [
        {"crop_name": "Rice", "quantity": 120, "date_received": "2024-01-15"},
        {"crop_name": "Rice", "quantity": 140, "date_received": "2024-02-15"},
        {"crop_name": "Corn", "quantity": 90, "date_received": "2024-01-15"},
        {"crop_name": "Corn", "quantity": 105, "date_received": "2024-02-15"},
        {"crop_name": "Tomato", "quantity": 80, "date_received": "2024-01-15"},
    ]

    payload = analyze_market_intelligence(records)

    assert "summary" in payload
    assert "risk_alerts" in payload
    assert "recommendations" in payload
    assert "forecast" in payload
    assert payload["summary"]["active_crops"] >= 2


def test_supply_analysis_marks_thresholds():
    records = [
        {"crop_name": "Rice", "quantity": 40, "date_received": "2024-01-05"},
        {"crop_name": "Rice", "quantity": 55, "date_received": "2024-02-05"},
        {"crop_name": "Rice", "quantity": 70, "date_received": "2024-03-05"},
        {"crop_name": "Tomato", "quantity": 10, "date_received": "2024-01-05"},
        {"crop_name": "Tomato", "quantity": 12, "date_received": "2024-02-05"},
    ]

    payload = SupplyAnalysisService().analyze(records)
    assert "summary" in payload
    assert payload["summary"]["total_quantity"] > 0
    assert len(payload["risk_alerts"]) >= 1

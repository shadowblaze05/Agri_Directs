import sqlite3

import app as app_module
import pytest
from app.routes import home as home_routes
from app.services.market_intelligence.data_sources import transaction_data


def _sample_market_analysis():
    return {
        "summary": {"active_crops": 2},
        "price_monitoring": [],
        "recommendations": [{"crop": "Rice", "score": 0.8}],
        "risk_alerts": [
            {
                "crop": "Tomato",
                "severity": "high",
                "message": "Tomato supply is above the usual range.",
            }
        ],
    }


def _inventory_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE crops (id INTEGER PRIMARY KEY, crops_name TEXT);
        CREATE TABLE inventory (
            crop_id INTEGER,
            quantity INTEGER,
            farmer TEXT,
            date_received TEXT,
            location TEXT,
            source TEXT
        );
        INSERT INTO crops VALUES (1, 'Rice');
        INSERT INTO inventory VALUES
            (1, 25, 'farmer-one', '2026-10-01', 'North', 'harvest'),
            (1, 40, 'farmer-two', '2026-10-02', 'South', 'harvest'),
            (1, 100, 'buyer-one', '2026-10-03', 'South', 'purchase'),
            (1, 80, 'farmer-three', '2026-10-04', 'West', 'trade'),
            (1, 10, 'legacy-farmer', '2026-09-30', 'East', NULL);
    """)
    return connection


def test_market_brief_inventory_query_aggregates_harvests_across_farmers(monkeypatch):
    monkeypatch.setattr(home_routes, "get_db", _inventory_connection)

    records = home_routes._market_records_from_db()

    assert {record["quantity"] for record in records} == {25, 40, 10}
    assert {record["location"] for record in records} == {"North", "South", "East"}
    assert sum(record["quantity"] for record in records) == 75


def test_market_intelligence_loader_aggregates_harvests_across_farmers(monkeypatch):
    monkeypatch.setattr(transaction_data, "get_db", _inventory_connection)

    records = transaction_data.load_transaction_records()

    assert {record["quantity"] for record in records} == {25.0, 40.0, 10.0}
    assert {record["location"] for record in records} == {"North", "South", "East"}
    assert sum(record["quantity"] for record in records) == 75


@pytest.mark.parametrize(
    ("endpoint", "expected_response_key"),
    [("/api/market-insights", "summary"), ("/api/forecast", "forecast")],
)
def test_market_intelligence_apis_use_the_shared_harvest_dataset(
    monkeypatch, endpoint, expected_response_key
):
    analyzed_records = []

    def analyze(records):
        analyzed_records.extend(records)
        return {"summary": {"total_quantity": 75}, "forecast": []}

    monkeypatch.setattr(home_routes, "get_db", _inventory_connection)
    monkeypatch.setattr(home_routes, "analyze_market_intelligence", analyze)

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get(endpoint)

    assert response.status_code == 200
    assert expected_response_key in response.get_json()
    assert sum(record["quantity"] for record in analyzed_records) == 75
    assert {record["location"] for record in analyzed_records} == {
        "North",
        "South",
        "East",
    }


class _DashboardCursor:
    def execute(self, query, params=()):
        self.rows = []
        self.row = (
            {"active_listings": 0, "crop_count": 0}
            if "COUNT(*) AS active_listings" in query
            else None
        )
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _DashboardConnection:
    def __init__(self):
        self._cursor = _DashboardCursor()

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def test_market_intelligence_page_is_admin_only(monkeypatch):
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get("/market-intelligence")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_market_brief_remains_visible_on_dashboard_for_regular_users(monkeypatch):
    monkeypatch.setattr(home_routes, "get_db", _DashboardConnection)
    monkeypatch.setattr(home_routes, "update_analytics", lambda: None)
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Your Market Brief" in response.data
    assert b"Tomato supply is above the usual range" in response.data
    assert b"View market insights" not in response.data


def test_dashboard_displays_the_market_brief(monkeypatch):
    monkeypatch.setattr(home_routes, "get_db", _DashboardConnection)
    monkeypatch.setattr(home_routes, "update_analytics", lambda: None)
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Your Market Brief" in response.data
    assert b"Rice currently ranks as a promising option" in response.data


def test_signed_in_home_displays_the_market_brief(monkeypatch):
    monkeypatch.setattr(home_routes, "get_db", _DashboardConnection)
    monkeypatch.setattr(home_routes, "_latest_updates", lambda limit=3: [])
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get("/home")

    assert response.status_code == 200
    assert b"Market Brief" in response.data
    assert b"Rice currently ranks as a promising option" in response.data
    assert b"Tomato supply is above the usual range" in response.data


def test_market_charts_remain_admin_only(monkeypatch):
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get("/market-intelligence/price-monitoring")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_admin_market_summary_keeps_the_detailed_chart(monkeypatch):
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        response = client.get("/market-intelligence")

    assert response.status_code == 200
    assert b"summaryPriceChart" in response.data

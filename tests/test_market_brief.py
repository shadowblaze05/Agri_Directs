import app as app_module
from app.routes import home as home_routes


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


def test_market_brief_is_available_to_regular_users_without_admin_charts(monkeypatch):
    monkeypatch.setattr(
        home_routes, "_market_analysis_context", _sample_market_analysis
    )
    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer"
            user_session["role"] = "user"

        response = client.get("/market-intelligence")

    assert response.status_code == 200
    assert b"Rice currently ranks as a promising option" in response.data
    assert b"Tomato supply is above the usual range" in response.data
    assert b"summaryPriceChart" not in response.data


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

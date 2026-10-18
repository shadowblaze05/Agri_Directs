import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import home as home_routes


class MetricsCursor:
    def __init__(self, current_period=3, previous_period=2):
        self.current_period = current_period
        self.previous_period = previous_period
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if "SELECT username AS buyer" in query:
            self.result = {"count": 1250}
        elif "profile_photo_captured_at IS NOT NULL" in query:
            self.result = {"count": 38}
        elif "SUM(CASE WHEN listing_date" in query:
            self.result = {
                "current_period": self.current_period,
                "previous_period": self.previous_period,
            }
        elif "status = 'available'" in query:
            self.result = {"count": 6}
        elif "FROM marketplace" in query and "listing_type" in query:
            self.result = {"count": 14}
        elif "knowledge_posts" in query:
            self.result = {"count": 9}
        else:
            self.result = {"count": 0}
        return self

    def fetchone(self):
        return self.result


class MetricsConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


def test_public_metrics_use_database_counts_and_comparable_listing_growth(monkeypatch):
    cursor = MetricsCursor()
    connection = MetricsConnection(cursor)
    monkeypatch.setattr(home_routes, "get_db", lambda: connection)
    monkeypatch.setattr(home_routes.time, "monotonic", lambda: home_routes._PROCESS_STARTED_MONOTONIC + 3600)

    metrics = home_routes._public_metrics(datetime(2026, 9, 26, 12, 30, 0))

    assert metrics["buyers"] == "1,250"
    assert metrics["farm_profiles"] == "38"
    assert metrics["product_listings"] == "14"
    assert metrics["market_listings"] == "6"
    assert metrics["growth"] == "+50%"
    assert metrics["knowledge_posts"] == "9"
    assert metrics["process_uptime"] == "1h 0m"
    assert connection.closed
    assert cursor.calls[-1][1] == (
        "2026-09-01 00:00:00",
        "2026-09-26 12:30:00",
        "2026-08-01 00:00:00",
        "2026-08-26 12:30:00",
    )


def test_public_metrics_render_on_landing_page_with_live_values(monkeypatch):
    cursor = MetricsCursor(current_period=0, previous_period=0)
    connection = MetricsConnection(cursor)
    monkeypatch.setattr(home_routes, "get_db", lambda: connection)

    def no_updates(limit=3):
        assert limit == 3
        return []

    monkeypatch.setattr(home_routes, "_latest_updates", no_updates)
    monkeypatch.setattr(home_routes.time, "monotonic", lambda: home_routes._PROCESS_STARTED_MONOTONIC)

    with app_module.app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert b"1,250" in response.data
    assert b"38" in response.data
    assert b"New listings vs same period last month" in response.data
    assert b"Process uptime" in response.data
    assert b"96%" not in response.data
    assert b"1.2K" not in response.data


def test_signed_in_mobile_stylesheet_keeps_navigation_visible_and_scrollable():
    with app_module.app.test_client() as test_client:
        response = test_client.get("/static/style.css")

    assert response.status_code == 200
    assert b"@media (max-width: 575.98px)" in response.data
    assert b"display: block !important" in response.data
    assert b"overflow-x: auto" in response.data
    assert b"safe-area-inset-bottom" in response.data


def test_dashboard_inventory_refresh_is_scoped_for_users_and_global_for_admins(monkeypatch):
    class InventoryCursor:
        def __init__(self):
            self.query = ""
            self.params = ()
            self.role = "user"

        def execute(self, query, params=()):
            self.query = query
            self.params = params
            return self

        def fetchone(self):
            return {"role": self.role, "is_active": 1}

        def fetchall(self):
            return []

    class InventoryConnection:
        def __init__(self):
            self.fake_cursor = InventoryCursor()

        def cursor(self):
            return self.fake_cursor

        def close(self):
            return None

    connection = InventoryConnection()
    monkeypatch.setattr(home_routes, "get_db", lambda: connection)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer-one"
            user_session["role"] = "user"
        response = client.get("/dashboard-data")
        assert response.status_code == 200
        assert "i.farmer = ?" in connection.fake_cursor.query
        assert connection.fake_cursor.params == ("farmer-one",)

        with client.session_transaction() as user_session:
            user_session["role"] = "admin"
        connection.fake_cursor.role = "admin"
        response = client.get("/dashboard-data")

    assert response.status_code == 200
    assert "i.farmer = ?" not in connection.fake_cursor.query
    assert connection.fake_cursor.params == ()


def test_stats_api_scopes_every_inventory_query_to_non_admin(monkeypatch):
    class StatsCursor:
        def __init__(self):
            self.calls = []
            self.current_query = ""

        def execute(self, query, params=()):
            self.calls.append((query, params))
            self.current_query = query
            return self

        def fetchone(self):
            if "SELECT role, is_active FROM users" in self.current_query:
                return {"role": "user", "is_active": 1}
            if "SUM(quantity)" in self.current_query:
                return {"total": 0}
            if "COUNT(DISTINCT location)" in self.current_query:
                return {"location_count": 0}
            return {"count": 0}

        def fetchall(self):
            return []

    class StatsConnection:
        def __init__(self):
            self.fake_cursor = StatsCursor()

        def cursor(self):
            return self.fake_cursor

        def close(self):
            return None

    connection = StatsConnection()
    monkeypatch.setattr(home_routes, "get_db", lambda: connection)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer-one"
            user_session["role"] = "user"
        response = client.get("/api/stats")

    assert response.status_code == 200
    inventory_queries = [
        (query, params) for query, params in connection.fake_cursor.calls
        if "FROM inventory" in query
    ]
    assert inventory_queries
    assert all("farmer = ?" in query for query, _ in inventory_queries)
    assert all("farmer-one" in params for _, params in inventory_queries)


def test_locations_map_only_includes_other_users_for_admins(monkeypatch):
    class LocationCursor:
        def __init__(self, role):
            self.calls = []
            self.role = role

        def execute(self, query, params=()):
            self.calls.append((query, params))
            return self

        def fetchone(self):
            return {"role": self.role, "is_active": 1}

        def fetchall(self):
            return []

    class LocationConnection:
        def __init__(self, role):
            self.fake_cursor = LocationCursor(role)

        def cursor(self):
            return self.fake_cursor

        def close(self):
            return None

    connections = []
    roles = iter(("user", "user", "admin", "admin"))

    def create_connection():
        connection = LocationConnection(next(roles))
        connections.append(connection)
        return connection

    monkeypatch.setattr(home_routes, "get_db", create_connection)
    monkeypatch.setattr(home_routes, "geocode_location", lambda _location: (0, 0))
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farmer-one"
            user_session["role"] = "user"
        response = client.get("/locations")
        assert response.status_code == 200
    user_query, user_params = connections[1].fake_cursor.calls[-1]
    assert "username = ?" in user_query
    assert user_params == ("farmer-one",)

    with app_module.app.test_client() as client:
        with client.session_transaction() as admin_session:
            admin_session["user"] = "admin"
            admin_session["role"] = "admin"
        response = client.get("/locations")
        assert response.status_code == 200
    admin_query, admin_params = connections[3].fake_cursor.calls[-1]
    assert "username = ?" not in admin_query
    assert admin_params == ()

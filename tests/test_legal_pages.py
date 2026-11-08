import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import home as home_routes


def test_legal_pages_are_public_and_linked_from_landing_page(monkeypatch):
    class FeaturedCursor:
        def execute(self, *_args):
            return self

        def fetchall(self):
            return []

    class FeaturedConnection:
        def cursor(self):
            return FeaturedCursor()

        def close(self):
            pass

    monkeypatch.setattr(home_routes, "get_db", FeaturedConnection)
    monkeypatch.setattr(home_routes, "_latest_updates", lambda limit=3: [])

    with app_module.app.test_client() as client:
        landing = client.get("/")
        pages = {
            "/terms": b"Terms of Service",
            "/privacy": b"Privacy Notice",
            "/cookies": b"Cookie Notice",
        }

        assert landing.status_code == 200
        assert b"/terms" in landing.data
        assert b"/privacy" in landing.data
        assert b"/cookies" in landing.data

        for path, expected_title in pages.items():
            response = client.get(path)
            assert response.status_code == 200
            assert expected_title in response.data
            assert b"Draft" in response.data

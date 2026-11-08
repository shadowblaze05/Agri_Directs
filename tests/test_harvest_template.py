import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import inventory as inventory_routes


def test_harvest_template_download_returns_import_columns(monkeypatch):
    role_lookup = lambda username, _connection_factory=None: (
        "seller" if username == "farmer" else None
    )
    monkeypatch.setattr(app_module, "get_active_user_role", role_lookup)
    monkeypatch.setattr(inventory_routes, "get_active_user_role", role_lookup)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "farmer"

        response = client.get("/upload/template")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "harvest-upload-template.csv" in response.headers[
        "Content-Disposition"
    ]
    lines = response.data.decode("utf-8").strip().splitlines()
    assert lines[0] == "crop_name,quantity(kg),date_received"
    assert lines[1].startswith("Rice,5,")


def test_harvest_template_download_requires_seller_access(monkeypatch):
    role_lookup = lambda _username, _connection_factory=None: "buyer"
    monkeypatch.setattr(app_module, "get_active_user_role", role_lookup)
    monkeypatch.setattr(inventory_routes, "get_active_user_role", role_lookup)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "buyer"
        response = client.get("/upload/template")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/marketplace")

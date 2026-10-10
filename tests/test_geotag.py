import importlib.util
from io import BytesIO
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from PIL import Image
from sqlalchemy import create_engine, inspect
from werkzeug.datastructures import FileStorage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.services.geotag_service import (
    EARTH_RADIUS_METERS,
    calculate_distance_meters,
    validate_coordinates,
    verify_crop_location,
)
from app.services import geotag_service
from app.routes import inventory as inventory_routes
from app.routes import admin as admin_routes
from app.routes import profile as profile_routes
from app.routes import marketplace as marketplace_routes
from app.routes import auth as auth_routes
from app.services.auth_service import generate_jwt_token
from app.services.profile_service import missing_harvest_profile_requirements


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 0), (-91, 0), (0, 181), (0, -181), (float("nan"), 0)],
)
def test_coordinate_validation_rejects_invalid_ranges(latitude, longitude):
    with pytest.raises(ValueError):
        validate_coordinates(latitude, longitude)


def test_haversine_distance_and_inclusive_maximum():
    exactly_fifteen_km_longitude = math.degrees(15_000 / EARTH_RADIUS_METERS)
    distance = calculate_distance_meters(0, 0, 0, exactly_fifteen_km_longitude)

    assert distance == pytest.approx(15_000)
    assert verify_crop_location(0, 0, 0, exactly_fifteen_km_longitude, distance) == (
        "within_range",
        distance,
    )
    assert verify_crop_location(0, 0, 0, math.degrees(15_100 / EARTH_RADIUS_METERS), 15_000)[0] == "outside_range"
    assert verify_crop_location(0, 0, 0, math.degrees(14_900 / EARTH_RADIUS_METERS), 15_000)[0] == "within_range"


def test_missing_coordinates_require_manual_review():
    assert verify_crop_location(0, 0, None, None, 15_000) == (
        "manual_review",
        None,
    )


def test_profile_completion_requires_camera_photo_and_gps_location():
    incomplete = {
        "first_name": "Farm",
        "last_name": "Owner",
        "email": "farmer@example.com",
        "profile_picture": "/static/uploads/profiles/old-photo.jpg",
        "profile_photo_captured_at": None,
        "location": None,
        "geotag_location": None,
        "location_latitude": None,
        "location_longitude": None,
        "location_verified": False,
    }

    assert missing_harvest_profile_requirements(incomplete) == [
        "profile photo GPS capture",
        "GPS-derived farm location",
        "verified profile GPS location",
    ]
    incomplete.update({
        "profile_photo_captured_at": "2026-09-26T12:00:00+00:00",
        "location": "Example City, Province",
        "geotag_location": "GPS place, Example City, Province",
        "location_latitude": 14.6,
        "location_longitude": 120.98,
        "location_verified": True,
    })
    assert missing_harvest_profile_requirements(incomplete) == []


def test_reverse_geocode_builds_place_name_from_address(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "address": {
                    "neighbourhood": "Central",
                    "city": "Sample City",
                    "state": "Sample Province",
                    "country": "Philippines",
                }
            }

    calls = []
    monkeypatch.setattr(geotag_service.requests, "get", lambda *args, **kwargs: (calls.append((args, kwargs)) or Response()))

    assert geotag_service.reverse_geocode_coordinates(14.6, 120.98) == (
        "Central, Sample City, Sample Province, Philippines"
    )
    assert calls[0][1]["params"]["lat"] == 14.6


def test_psgc_resolver_matches_reverse_geocoded_city_and_province(monkeypatch):
    def fake_get(url, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                if url.endswith("/cities-municipalities/"):
                    return [{
                        "code": "123",
                        "name": "City of Sample City",
                        "provinceCode": "456",
                        "regionCode": "789",
                    }, {
                        "code": "124",
                        "name": "Sample Province",
                        "provinceCode": "456",
                        "regionCode": "789",
                    }]
                if url.endswith("/provinces/"):
                    return [{"code": "456", "name": "Sample Province"}]
                if url.endswith("/regions/"):
                    return [{"code": "789", "name": "Sample Region"}]
                return []
        return Response()

    monkeypatch.setattr(geotag_service.requests, "get", fake_get)

    assert geotag_service.resolve_psgc_location(
        "Central, Sample City, Sample Province, Philippines"
    ) == "City of Sample City, Sample Province, Sample Region"


@pytest.fixture
def client():
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


def test_profile_location_rejects_invalid_coordinates_before_database_access(client):
    with client.session_transaction() as session:
        session["user"] = "farmer"

    response = client.post(
        "/profile/location",
        data={
            "profile_photo": (_png_bytes(), "profile.png", "image/png"),
            "latitude": "95",
            "longitude": "120",
            "captured_at": _recent_timestamp(),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "Latitude" in response.get_json()["error"]


def test_api_harvest_rejects_invalid_coordinates_before_database_access(client):
    token = generate_jwt_token("farmer")
    response = client.post(
        "/api/harvest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "crop_name": "Rice",
            "quantity": 10,
            "location": "Eastern Visayas",
            "latitude": 91,
            "longitude": 120,
        },
    )

    assert response.status_code == 400
    assert "Latitude" in response.get_json()["error"]


def test_profile_location_saves_validated_coordinates(client, tmp_path, monkeypatch):
    class FakeCursor:
        rowcount = 1

        def execute(self, query, params):
            self.query = query
            self.params = params
            return self

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            return None

        def close(self):
            return None

    connection = FakeConnection()
    monkeypatch.setattr(profile_routes, "get_db", lambda: connection)
    monkeypatch.setattr(profile_routes, "reverse_geocode_coordinates", lambda _lat, _lon: "Example City, Province")
    monkeypatch.setattr(profile_routes, "resolve_psgc_location", lambda _place: "PSGC City, Province")
    monkeypatch.setattr(app_module.app, "static_folder", str(tmp_path))
    with client.session_transaction() as session:
        session["user"] = "farmer"

    response = client.post(
        "/profile/location",
        data={
            "profile_photo": (_png_bytes(), "profile.png", "image/png"),
            "latitude": "14.6",
            "longitude": "120.98",
            "captured_at": _recent_timestamp(),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert connection.fake_cursor.params[2:5] == (
        "PSGC City, Province",
        "PSGC City, Province",
        "Example City, Province",
    )
    assert connection.fake_cursor.params[5:7] == (14.6, 120.98)
    assert response.get_json()["geotag_location"] == "Example City, Province"
    assert response.get_json()["psgc_location"] == "PSGC City, Province"
    assert connection.fake_cursor.params[-1] == "farmer"
    assert response.get_json()["status"] == "captured"
    assert response.get_json()["location"] == "PSGC City, Province"


def test_api_harvest_uses_token_owner_and_manual_review_without_photo(client, monkeypatch):
    class FakeCursor:
        rowcount = 1

        def __init__(self):
            self.inserted_values = None

        def execute(self, query, params=()):
            if "SELECT first_name" in query:
                self.profile = {
                    "first_name": "Farm",
                    "last_name": "Owner",
                    "email": "farmer@example.com",
                    "profile_picture": "/static/uploads/profiles/profile.jpg",
                    "profile_photo_captured_at": "2026-09-26T12:00:00+00:00",
                    "location": "Farm",
                    "geotag_location": "GPS Farm Place",
                    "location_latitude": 0,
                    "location_longitude": 0,
                    "location_verified": True,
                }
            elif "INSERT INTO inventory(" in query:
                self.inserted_values = params
            return self

        def fetchone(self):
            return getattr(self, "profile", None)

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            return None

        def close(self):
            return None

    connection = FakeConnection()
    monkeypatch.setattr(auth_routes, "get_db", lambda: connection)
    monkeypatch.setattr(auth_routes, "update_analytics", lambda: None)
    token = generate_jwt_token("farmer")
    longitude = math.degrees(1_000 / EARTH_RADIUS_METERS)

    response = client.post(
        "/api/harvest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "crop_name": "Rice",
            "quantity": 10,
            "location": "Farm",
            "farmer": "someone-else",
            "latitude": 0,
            "longitude": longitude,
            "gps_captured_at": "2026-09-26T12:00:00Z",
        },
    )

    assert response.status_code == 201
    assert connection.fake_cursor.inserted_values[1] == "farmer"
    assert connection.fake_cursor.inserted_values[7] == pytest.approx(1_000)
    assert connection.fake_cursor.inserted_values[8] == "manual_review"
    assert "API submissions do not include crop photo evidence" in connection.fake_cursor.inserted_values[9]
    assert response.get_json()["proximity_status"] == "within_range"


def test_admin_review_is_not_available_to_regular_users(client):
    with client.session_transaction() as session:
        session["user"] = "farmer"
        session["role"] = "user"

    response = client.post(
        "/admin/geotag/1/review",
        data={"decision": "approved"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_evidence_requires_authentication(client):
    response = client.get("/harvest-evidence/private.jpg")
    assert response.status_code == 401


def _png_bytes():
    stream = BytesIO()
    Image.new("RGB", (2, 2), color="green").save(stream, format="PNG")
    stream.seek(0)
    return stream


def _recent_timestamp():
    return datetime.now(timezone.utc).isoformat()


def _mock_inventory_database(monkeypatch, reference_location):
    class FakeCursor:
        inserted_values = None
        row = None

        def execute(self, query, params=()):
            if "SELECT first_name, last_name, email" in query:
                self.row = {
                    "first_name": "Farm",
                    "last_name": "Owner",
                    "email": "farmer@example.com",
                    "profile_picture": "/static/uploads/profiles/profile.jpg",
                    "profile_photo_captured_at": "2026-09-26T12:00:00+00:00",
                    "location": "Farm",
                    "geotag_location": "GPS Farm Place",
                    "location_latitude": reference_location[0],
                    "location_longitude": reference_location[1],
                    "location_verified": reference_location[2],
                }
            elif "SELECT id, crops_name" in query:
                self.row = None
            elif "INSERT INTO inventory(" in query:
                self.inserted_values = params
            return self

        def fetchone(self):
            return self.row

        def fetchall(self):
            return []

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            return None

        def close(self):
            return None

    connection = FakeConnection()
    monkeypatch.setattr(inventory_routes, "get_db", lambda: connection)
    monkeypatch.setattr(inventory_routes, "update_analytics", lambda: None)
    return connection.fake_cursor


def test_manual_harvest_saves_proximity_result_without_photo(client, monkeypatch):
    cursor = _mock_inventory_database(monkeypatch, (0, 0, True))
    with client.session_transaction() as session:
        session["user"] = "farmer"
        session["role"] = "user"

    capture_longitude = math.degrees(1_000 / EARTH_RADIUS_METERS)
    response = client.post(
        "/upload",
        data={
            "crop_id": "1",
            "manual_quantity": "4",
            "latitude": "0",
            "longitude": str(capture_longitude),
            "gps_captured_at": _recent_timestamp(),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert cursor.inserted_values[5] is None
    assert cursor.inserted_values[8] is not None
    assert cursor.inserted_values[9] == pytest.approx(1_000)
    assert cursor.inserted_values[10] == "within_range"
    assert cursor.inserted_values[11] is None


def test_harvest_without_gps_is_saved_for_manual_review(client, monkeypatch):
    cursor = _mock_inventory_database(monkeypatch, (12, 12, True))
    with client.session_transaction() as session:
        session["user"] = "farmer"
        session["role"] = "user"

    response = client.post(
        "/upload",
        data={"crop_id": "1", "manual_quantity": "4"},
    )

    assert response.status_code == 302
    assert cursor.inserted_values[9] is None
    assert cursor.inserted_values[10] == "manual_review"
    assert "GPS capture is missing" in cursor.inserted_values[11]


def test_upload_page_does_not_prompt_for_harvest_location(client, monkeypatch):
    _mock_inventory_database(monkeypatch, (0, 0, True))
    with client.session_transaction() as session:
        session["user"] = "farmer"
        session["role"] = "user"

    response = client.get("/upload")

    assert response.status_code == 200
    assert b"crop_photo" not in response.data
    assert b"Crop or harvest photo" not in response.data
    assert b"Capture harvest location" not in response.data
    assert b"navigator.geolocation" not in response.data
    assert b"gps_captured_at" not in response.data


def test_incomplete_profile_cannot_upload_harvest(client, monkeypatch):
    class FakeCursor:
        def execute(self, _query, _params=()):
            return self

        def fetchone(self):
            return {
                "first_name": "Farm",
                "last_name": "Owner",
                "email": "farmer@example.com",
                "profile_picture": None,
                "profile_photo_captured_at": None,
                "location": None,
                "geotag_location": None,
                "location_latitude": None,
                "location_longitude": None,
                "location_verified": False,
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(inventory_routes, "get_db", lambda: FakeConnection())
    with client.session_transaction() as session:
        session["user"] = "farmer"

    response = client.post(
        "/upload",
        data={"crop_id": "1", "manual_quantity": "10"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Complete your profile before uploading harvest" in response.data


def test_incomplete_profile_cannot_submit_jwt_harvest(client, monkeypatch):
    class FakeCursor:
        def execute(self, _query, _params=()):
            return self

        def fetchone(self):
            return {
                "first_name": "Farm",
                "last_name": "Owner",
                "email": "farmer@example.com",
                "profile_picture": None,
                "profile_photo_captured_at": None,
                "location": None,
                "location_latitude": None,
                "location_longitude": None,
                "location_verified": False,
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(auth_routes, "get_db", lambda: FakeConnection())
    token = generate_jwt_token("farmer")
    response = client.post(
        "/api/harvest",
        headers={"Authorization": f"Bearer {token}"},
        json={"crop_name": "Rice", "quantity": 10, "location": "Farm"},
    )

    assert response.status_code == 403
    assert "camera-captured profile photo" in response.get_json()["missing_profile_requirements"]


def test_profile_editor_uses_camera_capture_without_file_picker(client, monkeypatch):
    class FakeCursor:
        def execute(self, _query, _params=()):
            return self

        def fetchone(self):
            return {
                "username": "farmer",
                "first_name": "Farm",
                "last_name": "Owner",
                "email": "farmer@example.com",
                "phone_number": None,
                "bio": None,
                "profile_picture": None,
                "location": None,
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(profile_routes, "get_db", lambda: FakeConnection())
    with client.session_transaction() as session:
        session["user"] = "farmer"

    response = client.get("/profile/update")

    assert response.status_code == 200
    assert b"navigator.mediaDevices.getUserMedia" in response.data
    assert b"Camera permission timed out." in response.data
    assert b"cameraRequestTimedOut" in response.data
    assert b"await cameraPreview.play()" in response.data
    assert b"Location" in response.data
    assert b"GPS-derived place" not in response.data
    assert b'type="file"' not in response.data


def test_marketplace_seller_link_opens_contact_profile(client, monkeypatch):
    class FakeCursor:
        def execute(self, _query, _params=()):
            return self

        def fetchone(self):
            return {
                "username": "seller",
                "first_name": "Farm",
                "last_name": "Owner",
                "email": "seller@example.com",
                "phone_number": "+639123456789",
                "role": "farmer",
                "profile_picture": None,
                "location": None,
                "psgc_location": "Sample City",
                "geotag_location": "Sample City, Province",
                "bio": "Local grower",
                "location_verified": False,
                "profile_photo_captured_at": None,
                "is_verified": False,
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(profile_routes, "get_db", lambda: FakeConnection())
    with client.session_transaction() as session:
        session["user"] = "buyer"

    response = client.get("/profile/seller")

    assert response.status_code == 200
    assert b"Seller Profile" in response.data
    assert b"seller@example.com" in response.data
    assert b"mailto:seller@example.com" in response.data
    assert b"Email seller" in response.data
    assert b"Edit Profile" not in response.data
    assert b"Recent Inventory" not in response.data


def test_marketplace_thumbnail_requires_verified_profile_and_ten_km_radius(client):
    user = {
        "location_verified": True,
        "location_latitude": 0,
        "location_longitude": 0,
    }
    thumbnail = FileStorage(
        stream=_png_bytes(),
        filename="camera.png",
        content_type="image/png",
    )
    form = {
        "thumbnail_latitude": "0",
        "thumbnail_longitude": "0.08",
        "thumbnail_captured_at": _recent_timestamp(),
    }

    with app_module.app.test_request_context("/marketplace/add", method="POST"):
        extension, latitude, longitude, distance, captured_at = (
            marketplace_routes._validate_listing_thumbnail_capture(form, user, thumbnail)
        )

    assert extension == "png"
    assert latitude == 0
    assert longitude == pytest.approx(0.08)
    assert distance < 10_000
    assert captured_at.endswith("+00:00")

    form["thumbnail_longitude"] = "0.1"
    thumbnail.stream.seek(0)
    with app_module.app.test_request_context("/marketplace/add", method="POST"):
        with pytest.raises(ValueError, match="within 10 km"):
            marketplace_routes._validate_listing_thumbnail_capture(form, user, thumbnail)

    user["location_verified"] = False
    with app_module.app.test_request_context("/marketplace/add", method="POST"):
        with pytest.raises(ValueError, match="Verify your profile location"):
            marketplace_routes._validate_listing_thumbnail_capture(form, user, thumbnail)


def test_listing_form_uses_camera_for_thumbnail_and_upload_for_gallery(client, monkeypatch):
    class FakeCursor:
        def execute(self, query, _params=()):
            if "FROM inventory i JOIN crops c" in query:
                self.result = []
            elif query.startswith("SELECT id, crops_name FROM crops"):
                self.result = []
            elif query.startswith("SELECT location_verified FROM users"):
                self.result = {"location_verified": True}
            elif query.startswith("SELECT id FROM users"):
                self.result = {"id": 4}
            elif query.startswith("SELECT COALESCE(SUM(quantity), 0)"):
                self.result = {"total": 0}
            else:
                raise AssertionError(f"Unexpected SQL: {query}")
            return self

        def fetchall(self):
            return self.result

        def fetchone(self):
            return self.result

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(marketplace_routes, "get_db", FakeConnection)
    with client.session_transaction() as session:
        session["user"] = "farmer"

    response = client.get("/marketplace/add")

    assert response.status_code == 200
    assert b"navigator.mediaDevices.getUserMedia" in response.data
    assert b'name="thumbnail"' in response.data
    assert b'name="images"' in response.data
    assert b"Set as Thumbnail" not in response.data
    assert b"within 10 km" in response.data


def test_admin_marketplace_lists_and_creates_listings(client, monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.result = None
            self.inserted = None
            self.updated = None
            self.update_sql = None

        def execute(self, query, params=()):
            if "FROM marketplace m LEFT JOIN users" in query:
                self.result = [{
                    "id": 8,
                    "crop_id": 3,
                    "crop_name": "Rice",
                    "seller_name": "seller",
                    "username": "seller",
                    "amount": 25,
                    "price": 50.0,
                    "unit": "kg",
                    "status": "available",
                    "listing_type": "standard",
                    "buyer_username": None,
                    "available_date": None,
                    "description": "Fresh rice",
                }]
            elif query.startswith("SELECT id, username, location FROM users ORDER BY"):
                self.result = [{"id": 2, "username": "seller", "location": "Sample City"}]
            elif query.startswith("SELECT id, crops_name FROM crops ORDER BY"):
                self.result = [{"id": 3, "crops_name": "Rice"}]
            elif query.startswith("SELECT id, username, location FROM users WHERE"):
                self.result = {
                    "id": 3 if params[0] == "other" else 2,
                    "username": params[0],
                    "location": "Sample City",
                }
            elif query.startswith("SELECT id, crops_name FROM crops WHERE"):
                self.result = {"id": 3, "crops_name": "Rice"}
            elif query.startswith("INSERT INTO marketplace"):
                self.inserted = params
                self.result = None
            elif query.startswith("SELECT buyer_username, status, username FROM marketplace"):
                self.result = {"buyer_username": None, "status": "available", "username": "seller"}
            elif query.startswith("UPDATE marketplace"):
                self.updated = params
                self.update_sql = query
                self.result = None
            else:
                raise AssertionError(f"Unexpected SQL: {query}")
            return self

        def fetchall(self):
            return self.result

        def fetchone(self):
            return self.result

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(admin_routes, "get_db", FakeConnection)
    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"

    response = client.get("/admin/marketplace")
    assert response.status_code == 200
    assert b"Marketplace listings" in response.data
    assert b"Fresh rice" in response.data
    assert b"/admin/marketplace/create" in response.data

    response = client.post(
        "/admin/marketplace/create",
        data={
            "username": "seller",
            "crop_id": "3",
            "amount": "25",
            "price": "50",
            "unit": "kg",
            "listing_type": "standard",
            "status": "available",
            "expiry_days": "30",
            "description": "Fresh rice",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/marketplace")
    assert cursor.inserted[:8] == (2, "seller", 3, "Rice", 25, 50.0, "kg", "available")

    response = client.post(
        "/admin/marketplace/edit/8",
        data={
            "username": "seller",
            "crop_id": "3",
            "amount": "30",
            "price": "55",
            "unit": "kg",
            "listing_type": "standard",
            "status": "available",
            "description": "Updated rice listing",
        },
    )

    assert response.status_code == 302
    assert cursor.updated[:8] == (2, "seller", 3, "Rice", 30, 55.0, "kg", "available")
    assert "thumbnail_verified=0" not in cursor.update_sql

    response = client.post(
        "/admin/marketplace/edit/8",
        data={
            "username": "other",
            "crop_id": "3",
            "amount": "30",
            "price": "55",
            "unit": "kg",
            "listing_type": "standard",
            "status": "available",
            "description": "Updated rice listing",
        },
    )

    assert response.status_code == 302
    assert cursor.updated[:2] == (3, "other")
    assert "thumbnail_verified=0" in cursor.update_sql


def test_admin_marketplace_protects_ordered_listings_from_deletion(client, monkeypatch):
    class FakeCursor:
        deleted = False

        def execute(self, query, _params=()):
            if query.startswith("SELECT crop_name, buyer_username, status"):
                self.result = {
                    "crop_name": "Rice",
                    "buyer_username": "buyer",
                    "status": "sold",
                }
            elif query.startswith("DELETE FROM marketplace"):
                self.deleted = True
            else:
                raise AssertionError(f"Unexpected SQL: {query}")
            return self

        def fetchone(self):
            return self.result

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

        def close(self):
            return None

    monkeypatch.setattr(admin_routes, "get_db", FakeConnection)
    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"

    response = client.post("/admin/marketplace/delete/8")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/marketplace")
    assert not cursor.deleted


def test_admin_inventory_renders_review_interface(client, monkeypatch):
    record = {
        "id": 1,
        "crop_name": "Rice",
        "quantity": 4,
        "date_received": "2026-09-26",
        "farmer": "farmer",
        "source": "harvest",
        "photo_path": None,
        "verification_status": "manual_review",
        "distance_from_user": None,
        "capture_time": None,
        "verification_notes": "GPS missing",
        "reviewed_by": None,
    }

    class FakeCursor:
        def execute(self, _query, _params=None):
            self.last_query = (_query, _params)
            return self

        def fetchall(self):
            return [record]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(admin_routes, "get_db", lambda: FakeConnection())
    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"

    response = client.get("/admin/inventory")

    assert response.status_code == 200
    assert b"Inventory and geotag review" in response.data
    assert b"GPS missing" in response.data
    assert b"Approve" in response.data


def test_profile_location_panel_does_not_render_exact_coordinates(client, monkeypatch):
    class FakeCursor:
        current_query = ""

        def execute(self, query, _params=()):
            self.current_query = query
            self.current_params = _params
            return self

        def fetchone(self):
            if "COUNT(DISTINCT crop_id)" in self.current_query:
                return {"crop_count": 1, "total_quantity": 4}
            return {
                "username": "farmer",
                "first_name": "Farm",
                "last_name": "Owner",
                "role": "user",
                "profile_picture": "/static/uploads/profiles/profile.jpg",
                "profile_photo_captured_at": "2026-09-26T12:00:00+00:00",
                "location": "Farm",
                "psgc_location": "Example City, Province",
                "geotag_location": "GPS Farm Place",
                "location_latitude": 12.34,
                "location_longitude": 56.78,
                "location_verified": 1,
                "location_verified_at": "2026-09-26T12:00:00+00:00",
                "profile_photo_captured_at": "2026-09-26T12:00:00+00:00",
                "email": "farmer@example.com",
                "phone_number": None,
                "bio": None,
                "is_verified": False,
            }

        def fetchall(self):
            return []

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(profile_routes, "get_db", lambda: FakeConnection())
    with client.session_transaction() as session:
        session["user"] = "farmer"

    response = client.get("/profile")

    assert response.status_code == 200
    assert b"Location" in response.data
    assert b"Example City, Province" in response.data
    assert b"GPS Farm Place" not in response.data
    assert b"PSGC Location" not in response.data
    assert b"GPS-derived Place" not in response.data
    assert b"Update profile photo and location" in response.data
    assert b"12.34" not in response.data
    assert b"56.78" not in response.data


def test_admin_can_record_geotag_review(client, monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.executed = []

        def execute(self, query, params=()):
            self.executed.append((query, params))
            return self

        def fetchone(self):
            return {"verification_notes": "GPS missing", "source": "harvest"}

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()

        def cursor(self):
            return self.fake_cursor

        def commit(self):
            return None

        def close(self):
            return None

    connection = FakeConnection()
    monkeypatch.setattr(admin_routes, "get_db", lambda: connection)
    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"

    response = client.post(
        "/admin/geotag/1/review",
        data={"decision": "approved", "review_note": "Photo inspected"},
    )

    assert response.status_code == 302
    update_values = connection.fake_cursor.executed[-1][1]
    assert update_values[0] == "approved"
    assert update_values[1] == "admin"
    assert "GPS missing" in update_values[3]
    assert "Photo inspected" in update_values[3]


def test_crop_photo_is_validated_and_saved_outside_static(tmp_path, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(tmp_path))
    uploaded = FileStorage(stream=_png_bytes(), filename="../../field-photo.png")

    with app_module.app.app_context():
        filename = inventory_routes._save_crop_photo(uploaded)

    assert Path(filename).name == filename
    assert (tmp_path / "crop_evidence" / filename).is_file()
    assert not (Path(app_module.app.static_folder) / "uploads" / filename).exists()


def test_crop_photo_rejects_mismatched_content_and_oversize(tmp_path, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(tmp_path))
    uploaded = FileStorage(stream=_png_bytes(), filename="field-photo.jpg")

    with app_module.app.app_context(), pytest.raises(ValueError, match="does not match"):
        inventory_routes._save_crop_photo(uploaded)

    monkeypatch.setitem(app_module.app.config, "MAX_CROP_PHOTO_SIZE_BYTES", 1)
    uploaded = FileStorage(stream=_png_bytes(), filename="field-photo.png")
    with app_module.app.app_context(), pytest.raises(ValueError, match="or smaller"):
        inventory_routes._save_crop_photo(uploaded)


def test_evidence_is_limited_to_owner_and_admin(client, tmp_path, monkeypatch):
    filename = "private-evidence.png"
    evidence_dir = tmp_path / "crop_evidence"
    evidence_dir.mkdir()
    image = _png_bytes()
    (evidence_dir / filename).write_bytes(image.read())
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(tmp_path))

    class FakeCursor:
        def execute(self, _query, _params):
            self.last_call = (_query, _params)
            return self

        def fetchone(self):
            return {"farmer": "owner"}

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(inventory_routes, "get_db", lambda: FakeConnection())

    with client.session_transaction() as session:
        session["user"] = "other-farmer"
        session["role"] = "user"
    assert client.get(f"/harvest-evidence/{filename}").status_code == 404

    with client.session_transaction() as session:
        session["user"] = "owner"
        session["role"] = "user"
    assert client.get(f"/harvest-evidence/{filename}").status_code == 200

    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"
    assert client.get(f"/harvest-evidence/{filename}").status_code == 200


def test_geotag_migration_adds_nullable_fields_and_can_downgrade():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "b72c946fa310_add_geotag_verification.py"
    )
    spec = importlib.util.spec_from_file_location("geotag_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE inventory (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
        inventory_columns = {
            column["name"] for column in inspect(connection).get_columns("inventory")
        }
        assert {
            "location_latitude",
            "location_longitude",
            "location_verified",
            "profile_photo_captured_at",
        } <= user_columns
        assert {
            "photo_path",
            "latitude",
            "longitude",
            "capture_time",
            "distance_from_user",
            "verification_status",
            "verification_notes",
            "reviewed_by",
            "reviewed_at",
        } <= inventory_columns

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "location_latitude" not in {
            column["name"] for column in inspect(connection).get_columns("users")
        }

    engine.dispose()


def test_profile_location_migration_preserves_existing_location_and_can_downgrade():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "c84a1f6b2d90_add_separate_profile_location_labels.py"
    )
    spec = importlib.util.spec_from_file_location("profile_location_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, location VARCHAR(255))"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id, location) VALUES (1, 'Legacy PSGC location')"
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        user = connection.exec_driver_sql(
            "SELECT psgc_location, geotag_location FROM users WHERE id=1"
        ).one()
        assert user == (None, "Legacy PSGC location")

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "psgc_location" not in {
            column["name"] for column in inspect(connection).get_columns("users")
        }

    engine.dispose()

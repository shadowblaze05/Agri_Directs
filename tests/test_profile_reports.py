import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.listing_photo_location_alert import ListingPhotoLocationAlert
from app.models.profile_report import ProfileReport
from sqlalchemy import text


def make_profile_report_app(tmp_path):
    database_uri = f"sqlite:///{(tmp_path / 'profile-reports.db').as_posix()}"
    application = app_module.create_app(
        {"TESTING": True, "SQLALCHEMY_DATABASE_URI": database_uri}
    )
    with application.app_context():
        db.metadata.create_all(
            bind=db.engine,
            tables=[
                AuditEvent.__table__,
                ListingPhotoLocationAlert.__table__,
                ProfileReport.__table__,
            ],
        )
        with db.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE, first_name TEXT,
                    last_name TEXT, email TEXT, phone_number TEXT,
                    profile_picture TEXT, bio TEXT, role TEXT, is_verified BOOLEAN,
                    location_latitude FLOAT, location_longitude FLOAT,
                    location_verified BOOLEAN, profile_photo_captured_at DATETIME,
                    psgc_location TEXT, geotag_location TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT 1
                )
            """))
            connection.execute(text("""
                INSERT INTO users (id, username, first_name, role)
                VALUES (1, 'buyer', 'Buyer', 'user'), (2, 'seller', 'Seller', 'user')
            """))
            connection.execute(text("""
                CREATE TABLE marketplace (
                    id INTEGER PRIMARY KEY, username TEXT, buyer_rating INTEGER
                )
            """))
            connection.execute(text("""
                CREATE TABLE inventory (
                    id INTEGER PRIMARY KEY, crop_id INTEGER, crop_name TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE crops (
                    id INTEGER PRIMARY KEY, crops_name TEXT
                )
            """))
            connection.execute(text("""
                CREATE TABLE knowledge_posts (
                    post_id INTEGER PRIMARY KEY, title TEXT, content TEXT
                )
            """))
    return application


def test_public_profile_can_be_reported_and_admin_can_review_it(tmp_path):
    application = make_profile_report_app(tmp_path)

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "seller"
            user_session["role"] = "user"

        response = client.get("/profile/buyer")
        assert response.status_code == 200
        assert b"Report this profile" in response.data
        assert b"buyer/report" in response.data

        response = client.post(
            "/profile/buyer/report",
            data={"description": "short"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"between 10 and 2,000 characters" in response.data

        response = client.post(
            "/profile/buyer/report",
            data={"description": "Buyer did not follow the agreed transaction terms."},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Your report has been sent" in response.data

        with application.app_context():
            report = db.session.query(ProfileReport).one()
            assert report.reporter_username == "seller"
            assert report.reported_username == "buyer"
            assert report.status == "open"
            report_id = report.id

        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        response = client.get("/admin/profile-reports")
        assert response.status_code == 200
        assert b"Buyer did not follow the agreed transaction terms." in response.data
        response = client.post(f"/admin/profile-reports/{report_id}/review")
        assert response.status_code == 302

        with application.app_context():
            report = db.session.get(ProfileReport, report_id)
            assert report.status == "reviewed"
            assert report.reviewed_by == "admin"


def test_out_of_range_listing_photo_alert_is_visible_and_reviewable_by_admin(tmp_path):
    application = make_profile_report_app(tmp_path)
    with application.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("""
                UPDATE users SET location_latitude=0, location_longitude=0,
                    location_verified=1 WHERE username='seller'
            """))

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "seller"
            user_session["role"] = "user"

        response = client.post(
            "/marketplace/validate-thumbnail-location",
            json={
                "thumbnail_latitude": "0",
                "thumbnail_longitude": "0.1",
                "thumbnail_captured_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        assert response.status_code == 400
        assert "within 10 km" in response.json["error"]

        with application.app_context():
            alert = db.session.query(ListingPhotoLocationAlert).one()
            assert alert.username == "seller"
            assert alert.distance_meters > 10_000
            assert alert.status == "open"
            alert_id = alert.id

        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        response = client.get("/admin")
        assert response.status_code == 200
        assert b"Listing photo alerts" in response.data
        assert b">1</div>" in response.data

        response = client.get("/admin/listing-photo-alerts")
        assert response.status_code == 200
        assert b"@seller" in response.data
        assert b"11.12 km" in response.data

        response = client.post(
            f"/admin/listing-photo-alerts/{alert_id}/review"
        )
        assert response.status_code == 302

        with application.app_context():
            alert = db.session.get(ListingPhotoLocationAlert, alert_id)
            assert alert.status == "reviewed"
            assert alert.reviewed_by == "admin"

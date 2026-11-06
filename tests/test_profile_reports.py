import io
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.listing_photo_location_alert import ListingPhotoLocationAlert
from app.models.profile_report import ProfileReport
from app.services import admin_notification_service
from sqlalchemy import text


def make_profile_report_app(tmp_path):
    database_uri = f"sqlite:///{(tmp_path / 'profile-reports.db').as_posix()}"
    application = app_module.create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": database_uri,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
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
                VALUES
                    (1, 'buyer', 'Buyer', 'user'),
                    (2, 'seller', 'Seller', 'user'),
                    (3, 'admin', 'Admin', 'admin')
            """))
            connection.execute(text("""
                CREATE TABLE marketplace (
                    id INTEGER PRIMARY KEY, username TEXT, buyer_rating INTEGER,
                    status TEXT, buyer_username TEXT, order_status TEXT,
                    preorder_status TEXT
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


def test_public_profile_can_be_reported_and_admin_can_review_it(tmp_path, monkeypatch):
    application = make_profile_report_app(tmp_path)
    application.config.update(
        MAIL_SUPPRESS_SEND=False,
        MAIL_DEFAULT_SENDER="noreply@example.test",
        AGRI_DIRECT_OFFICIAL_EMAIL="official@example.test",
    )
    outbox = []
    monkeypatch.setattr(admin_notification_service.mail, "send", outbox.append)

    with application.app_context():
        with db.engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET email='admin@example.test' WHERE username='admin'")
            )

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
            data={
                "description": "Buyer did not follow the agreed transaction terms.",
                "evidence": (io.BytesIO(b"evidence contents"), "proof.txt"),
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Your report has been sent" in response.data
        assert len(outbox) == 1
        assert outbox[0].recipients == ["official@example.test"]
        assert "Buyer did not follow the agreed transaction terms." in outbox[0].body
        assert "/admin/profile-reports" in outbox[0].body

        with application.app_context():
            report = db.session.query(ProfileReport).one()
            assert report.reporter_username == "seller"
            assert report.reported_username == "buyer"
            assert report.status == "open"
            assert report.evidence_original_name == "proof.txt"
            report_id = report.id

        response = client.get(
            f"/admin/profile-reports/{report_id}/evidence"
        )
        assert response.status_code == 302

        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        response = client.get("/admin/profile-reports")
        assert response.status_code == 200
        assert b"Buyer did not follow the agreed transaction terms." in response.data
        assert b"proof.txt" in response.data
        response = client.get(
            f"/admin/profile-reports/{report_id}/evidence"
        )
        assert response.status_code == 200
        assert response.data == b"evidence contents"
        assert "attachment" in response.headers["Content-Disposition"]
        response = client.post(f"/admin/profile-reports/{report_id}/review")
        assert response.status_code == 302

        with application.app_context():
            report = db.session.get(ProfileReport, report_id)
            assert report.status == "reviewed"
            assert report.reviewed_by == "admin"


def test_report_notification_uses_official_email_when_admin_has_no_email(
    tmp_path, monkeypatch
):
    application = make_profile_report_app(tmp_path)
    application.config.update(
        MAIL_SUPPRESS_SEND=False,
        MAIL_DEFAULT_SENDER="noreply@example.test",
        AGRI_DIRECT_OFFICIAL_EMAIL="official@example.test",
    )
    outbox = []
    monkeypatch.setattr(admin_notification_service.mail, "send", outbox.append)

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "seller"
            user_session["role"] = "user"

        response = client.post(
            "/profile/buyer/report",
            data={"description": "This profile needs administrator review."},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"Your report has been sent" in response.data
        assert len(outbox) == 1
        assert outbox[0].recipients == ["official@example.test"]


def test_report_stays_submitted_when_email_notification_fails(tmp_path, monkeypatch):
    application = make_profile_report_app(tmp_path)
    application.config.update(
        MAIL_SUPPRESS_SEND=False,
        MAIL_DEFAULT_SENDER="noreply@example.test",
        AGRI_DIRECT_OFFICIAL_EMAIL="official@example.test",
    )

    def fail_delivery(_message):
        raise OSError("SMTP unavailable")

    monkeypatch.setattr(admin_notification_service.mail, "send", fail_delivery)

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "seller"
            user_session["role"] = "user"

        response = client.post(
            "/profile/buyer/report",
            data={"description": "This profile needs administrator review."},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"email notification could not be sent" in response.data

    with application.app_context():
        assert db.session.query(ProfileReport).count() == 1


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

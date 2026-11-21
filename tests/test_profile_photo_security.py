import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

import app as app_module
from app.routes import profile as profile_routes


def _new_png():
    image = BytesIO()
    Image.new("RGB", (8, 8), "green").save(image, format="PNG")
    image.seek(0)
    return image


def _create_database(path):
    connection = sqlite3.connect(path)
    connection.execute("""
        CREATE TABLE users (
            username TEXT PRIMARY KEY,
            profile_picture TEXT,
            profile_picture_public BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            profile_photo_captured_at TEXT,
            location TEXT,
            psgc_location TEXT,
            geotag_location TEXT,
            location_latitude REAL,
            location_longitude REAL,
            location_verified BOOLEAN NOT NULL DEFAULT FALSE,
            location_verified_at TEXT,
            updated_at TEXT,
            profile_photo_scan_verified_at TEXT,
            role TEXT,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            phone_number TEXT,
            bio TEXT,
            is_verified BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    connection.execute("""
        CREATE TABLE profile_photo_challenges (
            challenge_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL,
            movement_sequence TEXT NOT NULL DEFAULT '[]',
            current_stage INTEGER NOT NULL DEFAULT 0,
            last_stage_at TEXT,
            failed_attempts INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.execute("""
        CREATE TABLE marketplace (
            username TEXT,
            buyer_rating REAL
        )
    """)
    connection.executemany(
        "INSERT INTO users (username, role, first_name, location) VALUES (?, ?, ?, ?)",
        [
            ("owner", "seller", "Photo Owner", "Existing location"),
            ("other", "seller", "Other User", "Other location"),
            ("admin", "admin", "Administrator", "Admin location"),
        ],
    )
    connection.commit()
    connection.close()


@pytest.fixture
def photo_client(tmp_path, monkeypatch):
    database_path = tmp_path / "profile-security.sqlite"
    _create_database(database_path)
    static_folder = tmp_path / "static"
    upload_folder = tmp_path / "uploads"
    static_folder.mkdir()
    upload_folder.mkdir()

    def dict_row(cursor, row):
        return {
            column[0]: row[index]
            for index, column in enumerate(cursor.description)
        }

    def get_test_db():
        connection = sqlite3.connect(database_path)
        connection.row_factory = dict_row
        return connection

    def active_role(username, _connection_factory=None):
        return {"owner": "seller", "other": "seller", "admin": "admin"}.get(username)

    monkeypatch.setattr(profile_routes, "get_db", get_test_db)
    monkeypatch.setattr(profile_routes, "ensure_face_scanner_ready", lambda: None)
    monkeypatch.setattr(profile_routes, "validate_face_frame", lambda *_args: None)
    monkeypatch.setattr(profile_routes, "get_active_user_role", active_role)
    monkeypatch.setattr(app_module, "get_active_user_role", active_role)
    monkeypatch.setattr(app_module, "should_audit_request", lambda *_args: False)
    monkeypatch.setattr(profile_routes, "reverse_geocode_coordinates", lambda *_args: "Example City")
    monkeypatch.setattr(profile_routes, "resolve_psgc_location", lambda *_args: "Example City, Province")
    monkeypatch.setattr(app_module.app, "static_folder", str(static_folder))
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(upload_folder))
    monkeypatch.setitem(app_module.app.config, "MAX_PROFILE_PHOTO_SIZE_BYTES", 5 * 1024 * 1024)
    monkeypatch.setitem(app_module.app.config, "CSRF_ENFORCE_IN_TESTS", False)
    monkeypatch.setitem(app_module.app.config, "RATELIMIT_ENABLED", False)
    monkeypatch.setattr(profile_routes, "PROFILE_PHOTO_SCAN_MIN_STAGE_SECONDS", 0)

    test_client = app_module.app.test_client()
    test_client.environ_base["REMOTE_ADDR"] = str(uuid.uuid4())
    return test_client, database_path, static_folder, upload_folder


def _login(client, username):
    with client.session_transaction() as session:
        session["user"] = username
        session["role"] = {"admin": "admin"}.get(username, "seller")


def _issue_challenge(client):
    response = client.post("/profile/photo/challenge")
    assert response.status_code == 201
    return response.get_json()["challenge"]


def _advance_scan(client, database_path, challenge):
    connection = sqlite3.connect(database_path)
    sequence = connection.execute(
        "SELECT movement_sequence FROM profile_photo_challenges"
    ).fetchone()[0]
    connection.close()

    for _movement in json.loads(sequence):
        response = client.post(
            "/profile/photo/scan-stage",
            data={
                "challenge": challenge,
                "frame": (_new_png(), "scan-frame.jpg", "image/jpeg"),
            },
        )
        assert response.status_code == 200


def _capture_data(challenge):
    return {
        "challenge": challenge,
        "profile_photo": (_new_png(), "camera.png", "image/png"),
        "latitude": "14.6",
        "longitude": "120.98",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "public_photo_consent": "yes",
        "username": "other",
    }


def _fetch_user(database_path, username):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM users WHERE username=?", (username,)
    ).fetchone()
    connection.close()
    return row


def test_capture_challenge_is_random_hashed_user_bound_expiring_and_one_time(photo_client):
    client, database_path, _static_folder, upload_folder = photo_client
    _login(client, "owner")
    old_photo = upload_folder / "profile_photos" / "old.png"
    old_photo.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(old_photo, format="PNG")
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE users SET profile_picture='old.png', profile_picture_public=TRUE "
        "WHERE username='owner'"
    )
    connection.commit()
    connection.close()

    challenge = _issue_challenge(client)
    assert len(challenge) >= 40
    connection = sqlite3.connect(database_path)
    stored = connection.execute(
        "SELECT challenge_hash, username, expires_at, consumed_at "
        "FROM profile_photo_challenges"
    ).fetchone()
    assert stored[0] == hashlib.sha256(challenge.encode("utf-8")).hexdigest()
    assert stored[1] == "owner"
    assert stored[2] > datetime.now(timezone.utc).isoformat()
    assert stored[3] is None
    connection.close()

    with client.session_transaction() as session:
        session["user"] = "other"
    cross_user = client.post("/profile/location", data=_capture_data(challenge))
    assert cross_user.status_code == 409

    _login(client, "owner")
    _advance_scan(client, database_path, challenge)
    saved = client.post("/profile/location", data=_capture_data(challenge))
    assert saved.status_code == 200
    assert saved.get_json()["status"] == "captured"
    assert "coordinates" not in saved.get_json()

    replay = client.post("/profile/location", data=_capture_data(challenge))
    assert replay.status_code == 409
    user = _fetch_user(database_path, "owner")
    assert user["profile_picture_public"] == 1
    assert user["profile_photo_scan_verified_at"] is not None
    assert user["location"] == "Example City, Province"
    assert user["location_latitude"] == pytest.approx(14.6)
    assert not old_photo.exists()
    saved_photo = upload_folder / "profile_photos" / user["profile_picture"]
    assert saved_photo.is_file()
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/profile/photo/owner").status_code == 200
    assert not list((upload_folder / "profile_photos").glob("*.tmp"))
    assert not list((_static_folder / "uploads" / "profiles").glob("*"))


def test_expired_challenge_is_rejected(photo_client):
    client, database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    challenge = _issue_challenge(client)

    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE profile_photo_challenges SET expires_at=?",
        ("2000-01-01T00:00:00+00:00",),
    )
    connection.commit()
    connection.close()

    response = client.post(
        "/profile/location",
        data={"challenge": challenge, "public_photo_consent": "yes"},
    )
    assert response.status_code == 409
    stage_response = client.post(
        "/profile/photo/scan-stage",
        data={
            "challenge": challenge,
            "frame": (_new_png(), "scan-frame.jpg"),
        },
    )
    assert stage_response.status_code == 409


def test_profile_photo_cannot_be_saved_until_server_scan_is_complete(photo_client, monkeypatch):
    client, database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    challenge = _issue_challenge(client)
    connection = sqlite3.connect(database_path)
    sequence = json.loads(connection.execute(
        "SELECT movement_sequence FROM profile_photo_challenges"
    ).fetchone()[0])
    connection.close()

    premature_save = client.post(
        "/profile/location",
        data=_capture_data(challenge),
    )
    assert premature_save.status_code == 409

    observed_movements = []

    def observe_movement(frame_bytes, expected_movement):
        observed_movements.append(expected_movement)

    monkeypatch.setattr(profile_routes, "validate_face_frame", observe_movement)
    for submitted_movement in sequence:
        response = client.post(
            "/profile/photo/scan-stage",
            data={
                "challenge": challenge,
                "movement": "client-selected-value-is-ignored",
                "frame": (BytesIO(submitted_movement.encode("ascii")), "frame.jpg"),
            },
        )
        assert response.status_code == 200

    assert observed_movements == sequence
    assert response.get_json()["complete"] is True
    connection = sqlite3.connect(database_path)
    assert connection.execute(
        "SELECT current_stage FROM profile_photo_challenges"
    ).fetchone()[0] == len(sequence)
    connection.close()


def test_profile_details_require_a_successful_scan_and_public_photo_consent(photo_client):
    client, database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE users SET first_name=NULL, last_name=NULL, email=NULL WHERE username='owner'"
    )
    connection.commit()
    connection.close()

    update_data = {
        "first_name": "Updated",
        "last_name": "Owner",
        "email": "updated@example.com",
    }

    page = client.get("/profile/update")
    assert page.status_code == 200
    assert b"public profile" in page.data
    assert b"Profile photo privacy" not in page.data

    blocked = client.post("/profile/update", data=update_data)
    assert blocked.status_code == 302
    assert blocked.headers["Location"].endswith("/profile/update")
    assert _fetch_user(database_path, "owner")["first_name"] is None

    challenge = _issue_challenge(client)
    _advance_scan(client, database_path, challenge)
    missing_consent = _capture_data(challenge)
    missing_consent.pop("public_photo_consent")
    rejected = client.post("/profile/location", data=missing_consent)
    assert rejected.status_code == 400
    assert _fetch_user(database_path, "owner")["profile_picture"] is None

    saved_photo = client.post("/profile/location", data=_capture_data(challenge))
    assert saved_photo.status_code == 200
    edit_page = client.get("/profile/update")
    assert b"View public profile" in edit_page.data
    public_profile = client.get("/profile/owner")
    assert public_profile.status_code == 200
    assert b"owner" in public_profile.data
    assert b"Example City, Province" in public_profile.data

    completed = client.post("/profile/update", data=update_data)
    assert completed.status_code == 302
    assert completed.headers["Location"].endswith("/profile")
    assert _fetch_user(database_path, "owner")["first_name"] == "Updated"


def test_failed_scan_attempts_are_bounded_and_do_not_advance_stage(photo_client, monkeypatch):
    client, database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    old_photo = _upload_folder / "profile_photos" / "old.png"
    old_photo.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(old_photo, format="PNG")
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE users SET profile_picture=?, profile_picture_public=TRUE, "
        "profile_photo_captured_at=?, profile_photo_scan_verified_at=? "
        "WHERE username='owner'",
        ("old.png", datetime.now(timezone.utc).isoformat(),
         datetime.now(timezone.utc).isoformat()),
    )
    connection.commit()
    connection.close()
    challenge = _issue_challenge(client)

    def reject_pose(*_args):
        raise ValueError("Face the camera straight on.")

    monkeypatch.setattr(profile_routes, "validate_face_frame", reject_pose)
    for attempt in range(profile_routes.PROFILE_PHOTO_SCAN_MAX_ATTEMPTS):
        response = client.post(
            "/profile/photo/scan-stage",
            data={
                "challenge": challenge,
                "frame": (BytesIO(b"frame"), "frame.jpg"),
            },
        )
        assert response.status_code == 400
        assert response.get_json()["challenge_expired"] == (
            attempt + 1 == profile_routes.PROFILE_PHOTO_SCAN_MAX_ATTEMPTS
        )
    assert response.get_json()["profile_photo_cleared"] is True

    connection = sqlite3.connect(database_path)
    stage, consumed_at = connection.execute(
        "SELECT current_stage, consumed_at FROM profile_photo_challenges"
    ).fetchone()
    profile_picture, scan_verified_at = connection.execute(
        "SELECT profile_picture, profile_photo_scan_verified_at FROM users "
        "WHERE username='owner'"
    ).fetchone()
    connection.close()
    assert stage == 0
    assert consumed_at is not None
    assert profile_picture is None
    assert scan_verified_at is None
    assert not old_photo.exists()
    assert client.get("/profile/photo/owner").status_code == 404
    replay = client.post(
        "/profile/photo/scan-stage",
        data={
            "challenge": challenge,
            "frame": (BytesIO(b"frame"), "frame.jpg"),
        },
    )
    assert replay.status_code == 409


def test_invalid_image_consumes_challenge_without_changing_existing_photo(photo_client):
    client, database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE users SET profile_picture='existing.png' WHERE username='owner'"
    )
    connection.commit()
    connection.close()

    challenge = _issue_challenge(client)
    _advance_scan(client, database_path, challenge)
    data = _capture_data(challenge)
    data["profile_photo"] = (BytesIO(b"not an image"), "photo.png", "image/png")
    response = client.post("/profile/location", data=data)

    assert response.status_code == 400
    assert _fetch_user(database_path, "owner")["profile_picture"] == "existing.png"
    connection = sqlite3.connect(database_path)
    consumed_at = connection.execute(
        "SELECT consumed_at FROM profile_photo_challenges"
    ).fetchone()[0]
    connection.close()
    assert consumed_at is not None
    assert client.post("/profile/location", data=_capture_data(challenge)).status_code == 409


def test_legacy_private_photos_remain_private_without_visibility_controls(photo_client):
    client, database_path, static_folder, _upload_folder = photo_client
    legacy_directory = static_folder / "uploads" / "profiles"
    legacy_directory.mkdir(parents=True)
    legacy_image = legacy_directory / "legacy.jpg"
    Image.new("RGB", (8, 8), "blue").save(legacy_image, format="JPEG")

    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE users SET profile_picture=? WHERE username='owner'",
        ("/static/uploads/profiles/legacy.jpg",),
    )
    connection.commit()
    connection.close()

    direct_legacy_url = client.get("/static/uploads/profiles/legacy.jpg")
    assert direct_legacy_url.status_code == 404
    assert client.get("/profile/photo/owner").status_code == 404

    _login(client, "owner")
    owner_access = client.get("/profile/photo/owner")
    assert owner_access.status_code == 200
    assert "private" in owner_access.headers["Cache-Control"]
    assert "no-store" in owner_access.headers["Cache-Control"]

    with client.session_transaction() as session:
        session["user"] = "other"
    assert client.get("/profile/photo/owner").status_code == 404

    _login(client, "admin")
    assert client.get("/profile/photo/owner").status_code == 200

    _login(client, "owner")
    removed_control = client.post(
        "/profile/photo-visibility",
        data={"visibility": "public", "username": "owner"},
        follow_redirects=False,
    )
    assert removed_control.status_code == 405
    assert _fetch_user(database_path, "owner")["profile_picture_public"] == 0

    with client.session_transaction() as session:
        session.clear()
    assert client.get("/profile/photo/owner").status_code == 404
    assert client.get("/static/uploads/profiles/legacy.jpg").status_code == 404



def test_failed_photo_update_preserves_previous_photo_and_location(photo_client, monkeypatch):
    client, database_path, _static_folder, upload_folder = photo_client
    _login(client, "owner")
    old_photo = upload_folder / "profile_photos" / "old.png"
    old_photo.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(old_photo, format="PNG")
    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE users SET profile_picture=?, location='Old place', "
        "profile_picture_public=TRUE WHERE username='owner'",
        ("old.png",),
    )
    connection.commit()
    connection.close()

    real_get_db = profile_routes.get_db

    class TrackedCursor:
        def __init__(self, owner, cursor):
            self.owner = owner
            self.cursor = cursor

        def execute(self, query, parameters=()):
            result = self.cursor.execute(query, parameters)
            if query.startswith("UPDATE users SET profile_picture="):
                self.owner.fail_commit = True
            return self

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    class FailingCommitConnection:
        def __init__(self, connection):
            self.connection = connection
            self.fail_commit = False

        def cursor(self):
            return TrackedCursor(self, self.connection.cursor())

        def commit(self):
            if self.fail_commit:
                raise SQLAlchemyError("simulated update failure")
            self.connection.commit()

        def close(self):
            self.connection.close()

    monkeypatch.setattr(
        profile_routes,
        "get_db",
        lambda: FailingCommitConnection(real_get_db()),
    )
    challenge = _issue_challenge(client)
    _advance_scan(client, database_path, challenge)
    response = client.post("/profile/location", data=_capture_data(challenge))

    assert response.status_code == 500
    user = _fetch_user(database_path, "owner")
    assert user["profile_picture"] == "old.png"
    assert user["profile_picture_public"] == 1
    assert user["location"] == "Old place"
    assert old_photo.is_file()
    assert len(list((upload_folder / "profile_photos").glob("*.png"))) == 1


def test_capture_routes_require_same_origin(photo_client, monkeypatch):
    client, _database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    monkeypatch.setitem(app_module.app.config, "CSRF_ENFORCE_IN_TESTS", True)

    rejected = client.post("/profile/photo/challenge")
    assert rejected.status_code == 403
    rejected_stage = client.post(
        "/profile/photo/scan-stage",
        data={
            "challenge": "not-used",
            "frame": (_new_png(), "scan-frame.jpg"),
        },
    )
    assert rejected_stage.status_code == 403
    accepted = client.post(
        "/profile/photo/challenge",
        headers={"Origin": app_module.app.config["APP_BASE_URL"]},
    )
    assert accepted.status_code == 201


def test_profile_photo_challenge_issuance_is_rate_limited(photo_client, monkeypatch):
    client, _database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    monkeypatch.setitem(app_module.app.config, "RATELIMIT_ENABLED", True)

    results = [client.post("/profile/photo/challenge") for _ in range(11)]
    assert [response.status_code for response in results[:10]] == [201] * 10
    assert results[10].status_code == 429


def test_scan_stage_rate_limit_returns_json(photo_client, monkeypatch):
    client, _database_path, _static_folder, _upload_folder = photo_client
    _login(client, "owner")
    monkeypatch.setitem(app_module.app.config, "RATELIMIT_ENABLED", True)

    responses = [
        client.post("/profile/photo/scan-stage", data={})
        for _ in range(31)
    ]

    assert [response.status_code for response in responses[:30]] == [400] * 30
    assert responses[30].status_code == 429
    assert responses[30].is_json
    assert "Too many profile-photo requests" in responses[30].get_json()["error"]

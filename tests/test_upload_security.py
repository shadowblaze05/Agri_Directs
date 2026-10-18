from io import BytesIO
from pathlib import Path
import sys
from datetime import datetime, timezone

from PIL import Image
import pytest
from werkzeug.datastructures import FileStorage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import inventory as inventory_routes
from app.services.upload_service import save_sanitized_public_image, save_video_upload


def test_public_image_reencoding_strips_exif(tmp_path):
    source = BytesIO()
    exif = Image.Exif()
    exif[270] = "private location metadata"
    Image.new("RGB", (8, 8), "green").save(source, format="JPEG", exif=exif)
    source.seek(0)
    uploaded = FileStorage(stream=source, filename="farm.jpg", content_type="image/jpeg")
    destination = tmp_path / "sanitized.jpg"

    save_sanitized_public_image(uploaded, destination, "JPEG", 1024 * 1024)

    with Image.open(destination) as saved:
        assert saved.format == "JPEG"
        assert saved.getexif().get(270) is None


def test_public_image_rejects_extension_content_mismatch(tmp_path):
    source = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(source, format="PNG")
    source.seek(0)
    uploaded = FileStorage(stream=source, filename="photo.jpg", content_type="image/jpeg")

    with pytest.raises(ValueError, match="does not match"):
        save_sanitized_public_image(uploaded, tmp_path / "photo.jpg", "JPEG", 1024)


def test_video_signature_and_size_are_validated(tmp_path):
    uploaded = FileStorage(
        stream=BytesIO(b"\x00\x00\x00\x18ftypmp42video-data"),
        filename="clip.mp4",
        content_type="video/mp4",
    )
    destination = tmp_path / "clip.mp4"
    save_video_upload(uploaded, destination, "mp4", 1024)
    assert destination.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")

    invalid = FileStorage(
        stream=BytesIO(b"not a video"),
        filename="clip.mp4",
        content_type="video/mp4",
    )
    with pytest.raises(ValueError, match="does not match"):
        save_video_upload(invalid, tmp_path / "invalid.mp4", "mp4", 1024)

    oversized = FileStorage(
        stream=BytesIO(b"\x00\x00\x00\x18ftypmp42video-data"),
        filename="large.mp4",
        content_type="video/mp4",
    )
    with pytest.raises(ValueError, match="exceeds the allowed size"):
        save_video_upload(oversized, tmp_path / "large.mp4", "mp4", 4)


def test_csv_upload_uses_temporary_server_filename_and_cleans_file(monkeypatch, tmp_path):
    class FakeCursor:
        rowcount = 1

        def __init__(self):
            self.query = ""

        def execute(self, query, _params=()):
            self.query = query
            return self

        def fetchone(self):
            if "SELECT first_name" in self.query:
                return {
                    "first_name": "Farm",
                    "last_name": "Owner",
                    "email": "farmer@example.test",
                    "profile_picture": "/profile.jpg",
                    "profile_photo_captured_at": datetime.now(timezone.utc).isoformat(),
                    "location": "Example City",
                    "psgc_location": "Example City",
                    "geotag_location": "Example City",
                    "location_latitude": 14.6,
                    "location_longitude": 120.98,
                    "location_verified": 1,
                }
            if "SELECT id FROM crops" in self.query:
                return (1,)
            return None

        def fetchall(self):
            return [{"id": 1, "crops_name": "Rice"}]

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
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(tmp_path))
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "farmer"

        response = client.post(
            "/upload",
            data={
                "file": (
                    BytesIO(b"crop_name,quantity,date_received\nRice,5,2026-10-13\n"),
                    "../../harvest.csv",
                )
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    assert list(tmp_path.iterdir()) == []
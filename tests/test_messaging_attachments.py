import io
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.routes import home as home_routes


class FakeCursor:
    def __init__(self):
        self.statements = []

    def execute(self, query, params=()):
        self.statements.append((query, params))
        return self

    def fetchone(self):
        query, params = self.statements[-1]
        if "SELECT id FROM messages" in query:
            return {"id": 1} if params[1] in {"sender", "recipient"} else None
        return {"username": "recipient"}


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        return None

    def close(self):
        return None


def test_send_chat_message_stores_sanitized_image_and_protects_access(monkeypatch, tmp_path):
    image_data = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(image_data, format="JPEG")
    image_bytes = image_data.getvalue()
    connection = FakeConnection()
    monkeypatch.setattr(home_routes, "get_db", lambda: connection)
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(tmp_path))
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "sender"

        response = client.post(
            "/messages/send",
            data={
                "recipient": "recipient",
                "message": "Fresh harvest",
                "attachment": (io.BytesIO(image_bytes), "harvest.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert response.json["status"] == "success"
    insert_query, insert_values = next(
        statement for statement in connection.fake_cursor.statements
        if "INSERT INTO messages" in statement[0]
    )
    assert "attachment_url" in insert_query
    assert insert_values[1:3] == ("recipient", "Fresh harvest")
    assert insert_values[4].startswith("/messages/attachments/")
    assert insert_values[5] == "image"

    saved_image = tmp_path / "messages" / insert_values[4].rsplit("/", 1)[-1]
    with Image.open(saved_image) as image:
        assert image.format == "JPEG"
        assert image.size == (4, 4)
        assert not image.getexif()

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "stranger"
        assert client.get(insert_values[4]).status_code == 404

        with client.session_transaction() as session:
            session["user"] = "sender"
        attachment_response = client.get(insert_values[4])
        assert attachment_response.status_code == 200
        with Image.open(io.BytesIO(attachment_response.data)) as image:
            assert image.format == "JPEG"
            assert not image.getexif()


def test_send_chat_message_rejects_non_media_attachment(monkeypatch):
    monkeypatch.setattr(
        home_routes,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be used")),
    )
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "sender"

        response = client.post(
            "/messages/send",
            data={
                "recipient": "recipient",
                "attachment": (io.BytesIO(b"not media"), "payload.exe", "application/octet-stream"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 400
    assert response.json["status"] == "error"

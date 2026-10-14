import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.database import get_db, init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    application = app_module.create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'knowledge-hub.db').as_posix()}",
        "INITIAL_ADMIN_USERNAME": "admin",
        "INITIAL_ADMIN_PASSWORD": "Test!GardenBloom9",
    })
    with application.app_context():
        init_db()
        db.metadata.create_all(bind=db.engine, tables=[AuditEvent.__table__])
    with application.test_client() as client:
        yield client


def test_admin_can_create_publish_post_and_users_can_interact(client):
    login = client.post("/login", data={"username": "admin", "password": "Test!GardenBloom9"}, follow_redirects=True)
    assert login.status_code == 200

    create_response = client.post(
        "/admin/knowledge/create",
        data={
            "title": "Rice disease guide",
            "category_id": "1",
            "content": "A complete guide to rice disease management.",
            "status": "Published",
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200

    feed_response = client.get("/knowledge")
    assert feed_response.status_code == 200
    assert b"Rice disease guide" in feed_response.data
    assert b"Latest Updates" in feed_response.data

    like_response = client.post("/knowledge/like/1")
    assert like_response.status_code == 200
    assert like_response.get_json()["status"] == "liked"

    comment_response = client.post(
        "/knowledge/comment/1",
        data={"comment": "This is very helpful"},
        follow_redirects=True,
    )
    assert comment_response.status_code == 200

    reply_response = client.post(
        "/knowledge/reply/1",
        data={"reply": "Thank you for reading"},
        follow_redirects=True,
    )
    assert reply_response.status_code == 200


def test_pinning_published_update_notifies_users_once(client):
    application = client.application
    with application.app_context():
        connection = get_db()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("farmer-one", "unused", "user"),
        )
        connection.commit()
        connection.close()

    client.post("/login", data={"username": "admin", "password": "Test!GardenBloom9"})
    response = client.post(
        "/admin/knowledge/create",
        data={
            "title": "Weather advisory",
            "category_id": "1",
            "content": "Heavy rainfall is expected.",
            "status": "Published",
            "is_pinned": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with application.app_context():
        connection = get_db()
        cursor = connection.cursor()
        post = cursor.execute(
            "SELECT post_id, is_pinned FROM knowledge_posts WHERE title=?",
            ("Weather advisory",),
        ).fetchone()
        notification_count = cursor.execute(
            "SELECT COUNT(*) AS count FROM notifications WHERE username=? AND type=?",
            ("farmer-one", "announcement"),
        ).fetchone()["count"]
        connection.close()
    assert post["is_pinned"] == 1
    assert notification_count == 1

    response = client.post(
        f"/admin/knowledge/edit/{post['post_id']}",
        data={
            "title": "Updated weather advisory",
            "category_id": "1",
            "content": "Heavy rainfall is expected this week.",
            "status": "Published",
            "is_pinned": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with application.app_context():
        connection = get_db()
        cursor = connection.cursor()
        notification_count = cursor.execute(
            "SELECT COUNT(*) AS count FROM notifications WHERE username=? AND type=?",
            ("farmer-one", "announcement"),
        ).fetchone()["count"]
        connection.close()
    assert notification_count == 1

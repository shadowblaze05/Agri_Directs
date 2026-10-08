import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))
    app_module.init_db()
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        yield client


def test_admin_can_create_publish_post_and_users_can_interact(client):
    login = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=True)
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
    connection = app_module.get_db()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
        ("farmer-one", "unused", "user"),
    )
    connection.commit()
    connection.close()

    client.post("/login", data={"username": "admin", "password": "admin"})
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

    connection = app_module.get_db()
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

    connection = app_module.get_db()
    cursor = connection.cursor()
    notification_count = cursor.execute(
        "SELECT COUNT(*) AS count FROM notifications WHERE username=? AND type=?",
        ("farmer-one", "announcement"),
    ).fetchone()["count"]
    connection.close()
    assert notification_count == 1

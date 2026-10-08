import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent


def make_audit_app(database_uri):
    application = app_module.create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": database_uri,
        }
    )
    with application.app_context():
        db.metadata.create_all(bind=db.engine, tables=[AuditEvent.__table__])

    @application.route("/audit-test/mutate", methods=["POST"])
    def audit_test_mutate():
        return "created", 201

    @application.route("/audit-test/failure", methods=["POST"])
    def audit_test_failure():
        return "denied", 403

    return application


def test_audit_events_capture_writes_without_form_secrets_and_search(tmp_path):
    application = make_audit_app(f"sqlite:///{(tmp_path / 'audit.sqlite').as_posix()}")

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farm-admin"
            user_session["role"] = "admin"

        response = client.post(
            "/audit-test/mutate",
            data={"password": "do-not-store-this", "field": "value"},
        )

        assert response.status_code == 201
        with application.app_context():
            event = db.session.query(AuditEvent).one()
            assert event.actor == "farm-admin"
            assert event.role == "admin"
            assert event.action == "Post audit test mutate"
            assert event.status_code == 201
            assert event.details == "{}"
            assert "do-not-store-this" not in event.details
            assert "password" not in event.details

        response = client.get("/admin/audit-logs?q=farm-admin&method=POST")
        assert response.status_code == 200
        assert b"Post audit test mutate" in response.data
        assert b"Showing 1" in response.data


def test_audit_log_filters_failures_and_exports_filtered_csv(tmp_path):
    application = make_audit_app(f"sqlite:///{(tmp_path / 'audit.sqlite').as_posix()}")

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"

        client.post("/audit-test/mutate")
        client.post("/audit-test/failure")

        response = client.get("/admin/audit-logs?result=failure&category=Application")
        assert response.status_code == 200
        assert b"403" in response.data
        assert b"201" not in response.data

        response = client.get("/admin/audit-logs?result=failure&export=csv")
        assert response.status_code == 200
        assert response.mimetype == "text/csv"
        assert b"Post audit test failure" in response.data
        assert b"Post audit test mutate" not in response.data


def test_audit_log_requires_admin_and_rejects_invalid_date_filter(tmp_path):
    application = make_audit_app(f"sqlite:///{(tmp_path / 'audit.sqlite').as_posix()}")

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "ordinary-user"
            user_session["role"] = "user"
        assert client.get("/admin/audit-logs").status_code == 302

        with client.session_transaction() as user_session:
            user_session["role"] = "admin"
        assert client.get("/admin/audit-logs?start_date=not-a-date").status_code == 400


def test_admin_access_and_logout_are_logged_with_the_original_actor(tmp_path):
    application = make_audit_app(f"sqlite:///{(tmp_path / 'audit.sqlite').as_posix()}")

    @application.route("/admin/audit-test")
    def audit_test_admin_page():
        return "admin page"

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "farm-admin"
            user_session["role"] = "admin"

        assert client.get("/admin/audit-test").status_code == 200
        assert client.get("/logout").status_code == 302

    with application.app_context():
        events = db.session.query(AuditEvent).order_by(AuditEvent.id).all()
        assert [(event.actor, event.action, event.category) for event in events] == [
            ("farm-admin", "Viewed audit test admin page", "Administration"),
            ("farm-admin", "Signed out", "Authentication"),
        ]

from sqlalchemy import select, text

import app as app_module
from app.extensions import db
from app.models.audit import AuditEvent
from app.models.slow_query import SlowQueryStat
from app.services import slow_query_monitor


def test_slow_query_capture_normalizes_sql_and_tracks_cost(tmp_path, monkeypatch):
    database_uri = f"sqlite:///{(tmp_path / 'slow-query.sqlite').as_posix()}"
    application = app_module.create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": database_uri,
            "SLOW_QUERY_THRESHOLD_MS": 500,
        }
    )
    with application.app_context():
        db.metadata.create_all(
            bind=db.engine,
            tables=[SlowQueryStat.__table__, AuditEvent.__table__],
        )

    clock = iter((0.0, 1.0))
    monkeypatch.setattr(slow_query_monitor.time, "perf_counter", lambda: next(clock))
    with application.app_context():
        with db.engine.begin() as connection:
            result = connection.execute(text("SELECT 'sensitive-value'"))
            assert result.scalar_one() == "sensitive-value"

    monkeypatch.undo()
    with application.app_context():
        stat = db.session.scalars(select(SlowQueryStat)).one()
        assert stat.statement == "SELECT ?"
        assert "sensitive-value" not in stat.statement
        assert stat.call_count == 1
        assert stat.total_time_ms == 1000
        assert stat.max_time_ms == 1000

    with application.test_client() as client:
        with client.session_transaction() as user_session:
            user_session["user"] = "admin"
            user_session["role"] = "admin"
        response = client.get("/admin/slow-queries")

    assert response.status_code == 200
    assert b"SELECT ?" in response.data
    assert b"500 ms" in response.data
    assert b"1000.0 ms" in response.data


def test_statement_normalization_keeps_placeholders_stable():
    assert slow_query_monitor.normalize_statement(
        "SELECT *  FROM users WHERE id = 42 AND username = 'farmer''s data'"
    ) == "SELECT * FROM users WHERE id = ? AND username = ?"

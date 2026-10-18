import hashlib
import logging
import re
import time
from datetime import datetime, timezone

from sqlalchemy import case, event
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from ..models.slow_query import SlowQueryStat

_TELEMETRY_OPTION = "slow_query_telemetry"


def normalize_statement(statement):
    """Return a value-redacted, stable representation of a SQL statement."""
    normalized = re.sub(r"'(?:''|[^'])*'", "?", statement)
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "?", normalized)
    return " ".join(normalized.split())


def _before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
    if context.execution_options.get(_TELEMETRY_OPTION):
        return
    context._slow_query_started_at = time.perf_counter()


def _after_cursor_execute(
    threshold_ms,
    logger,
    connection,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    started_at = getattr(context, "_slow_query_started_at", None)
    if started_at is None:
        return

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    if elapsed_ms < threshold_ms:
        return

    normalized = normalize_statement(statement)
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    logger.warning(
        "Slow SQL execution: %.1f ms (threshold %.1f ms): %s",
        elapsed_ms,
        threshold_ms,
        normalized,
    )
    table = SlowQueryStat.__table__
    values = {
        "fingerprint": fingerprint,
        "statement": normalized,
        "call_count": 1,
        "total_time_ms": elapsed_ms,
        "max_time_ms": elapsed_ms,
        "last_seen_at": datetime.now(timezone.utc),
    }

    try:
        if connection.dialect.name == "postgresql":
            insert_statement = postgresql_insert(table).values(**values)
        elif connection.dialect.name == "sqlite":
            insert_statement = sqlite_insert(table).values(**values)
        else:
            logger.error(
                "Slow-query telemetry does not support database dialect %s",
                connection.dialect.name,
            )
            return

        excluded = insert_statement.excluded
        insert_statement = insert_statement.on_conflict_do_update(
            index_elements=[table.c.fingerprint],
            set_={
                "statement": excluded.statement,
                "call_count": table.c.call_count + 1,
                "total_time_ms": table.c.total_time_ms + excluded.total_time_ms,
                "max_time_ms": case(
                    (excluded.max_time_ms > table.c.max_time_ms, excluded.max_time_ms),
                    else_=table.c.max_time_ms,
                ),
                "last_seen_at": excluded.last_seen_at,
            },
        ).execution_options(**{_TELEMETRY_OPTION: True})

        previous_option = connection.get_execution_options().get(_TELEMETRY_OPTION, False)
        connection.execution_options(**{_TELEMETRY_OPTION: True})
        try:
            with connection.begin_nested():
                connection.execute(insert_statement)
        finally:
            connection.execution_options(
                **{_TELEMETRY_OPTION: previous_option}
            )
    except SQLAlchemyError:
        logger.exception("Unable to persist slow-query telemetry")


def install_slow_query_monitor(engine, threshold_ms, logger=None):
    """Record slow SQL execution time and frequency for the admin dashboard."""
    if event.contains(engine, "before_cursor_execute", _before_cursor_execute):
        return

    logger = logger or logging.getLogger(__name__)
    after_callback = lambda *args: _after_cursor_execute(
        threshold_ms, logger, *args
    )
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_callback)

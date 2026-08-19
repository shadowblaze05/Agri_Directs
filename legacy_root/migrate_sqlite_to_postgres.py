"""Copy the existing database.db data into the configured PostgreSQL database."""

import os
import sqlite3

import psycopg2

import app


TABLES = (
    "crops",
    "users",
    "inventory",
    "harvest",
    "analytics",
    "marketplace",
    "messages",
    "notifications",
    "knowledge_categories",
    "knowledge_posts",
    "knowledge_likes",
    "knowledge_comments",
    "knowledge_replies",
)


def _postgres_dsn():
    database_url = app.app.config["SQLALCHEMY_DATABASE_URI"]
    return database_url.replace("postgresql+psycopg2://", "postgresql://", 1)


def _postgres_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    return [row[0] for row in cur.fetchall()]


def main():
    sqlite_path = os.path.join(app.BASE_DIR, "database.db")
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    # Create the PostgreSQL schema before copying rows so new columns are available.
    app.init_db()

    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    destination = psycopg2.connect(_postgres_dsn())

    try:
        with destination:
            with destination.cursor() as target:
                for table_name in TABLES:
                    source_tables = source.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table_name,),
                    ).fetchone()
                    if not source_tables:
                        continue

                    target_columns = _postgres_columns(target, table_name)
                    source_columns = [
                        row[1]
                        for row in source.execute(f"PRAGMA table_info({table_name})").fetchall()
                    ]
                    columns = [column for column in source_columns if column in target_columns]
                    if not columns:
                        continue

                    quoted_columns = ", ".join(f'"{column}"' for column in columns)
                    placeholders = ", ".join(["%s"] * len(columns))
                    insert_sql = (
                        f'INSERT INTO "{table_name}" ({quoted_columns}) '
                        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                    )
                    rows = source.execute(
                        f'SELECT {quoted_columns} FROM "{table_name}"'
                    ).fetchall()
                    target.executemany(
                        insert_sql,
                        [tuple(row[column] for column in columns) for row in rows],
                    )
                    print(f"Copied {len(rows)} rows from {table_name}")
    finally:
        source.close()
        destination.close()


if __name__ == "__main__":
    main()

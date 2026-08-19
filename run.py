"""Run the Agri Directs development server."""

import sys

from sqlalchemy.exc import OperationalError

from app import app, init_db


if __name__ == "__main__":
    try:
        init_db()
    except OperationalError as exc:
        print(
            "\nUnable to connect to PostgreSQL.\n"
            "Set DATABASE_URL before starting the app, for example:\n\n"
            '$env:DATABASE_URL = "postgresql://postgres:Shadow12345@localhost:5432/AgriDirects"\n'
            "py run.py\n\n"
            f"PostgreSQL error: {exc}\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
    app.run(debug=True)

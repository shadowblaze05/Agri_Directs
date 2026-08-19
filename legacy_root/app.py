"""Compatibility entry point for the reorganized Agri Directs application.

The full implementation now lives in ``app/legacy.py`` while the package
structure is being split into route, service, algorithm, and model modules.
This file keeps older commands such as ``python app.py`` and imports working.
Use ``python run.py`` for the normal development server.
"""

from app import *  # noqa: F401,F403
from app import app, init_db


if __name__ == "__main__":
    init_db()
    app.run(debug=True)

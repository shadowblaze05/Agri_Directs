import sys
from pathlib import Path

from werkzeug.security import check_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from app.models.database import get_db


def test_init_db_cli_bootstraps_the_configured_initial_admin(tmp_path):
    application = app_module.create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'bootstrap.sqlite').as_posix()}",
        "INITIAL_ADMIN_USERNAME": "launch-admin",
        "INITIAL_ADMIN_PASSWORD": "StrongGarden9",
        "SUPERADMIN_USERNAME": "launch-admin",
    })

    result = application.test_cli_runner().invoke(args=["init-db"])

    assert result.exit_code == 0, result.output
    with application.app_context():
        connection = get_db()
        user = connection.cursor().execute(
            "SELECT username, password, role FROM users WHERE username=?",
            ("launch-admin",),
        ).fetchone()
        connection.close()

    assert user["username"] == "launch-admin"
    assert user["role"] == "admin"
    assert check_password_hash(user["password"], "StrongGarden9")

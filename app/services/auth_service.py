import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import (
    current_app,
    g,
    has_app_context,
    has_request_context,
    jsonify,
    request,
    session,
)

from ..config import Config

logger = logging.getLogger(__name__)


def get_active_user_role(username, connection_factory=None):
    if not username:
        return None
    if connection_factory is None:
        from ..models.database import get_db
        connection_factory = get_db

    connection = connection_factory()
    try:
        user = connection.cursor().execute(
            "SELECT role, is_active FROM users WHERE username=?",
            (username,),
        ).fetchone()
    finally:
        connection.close()

    if not user or not user["is_active"]:
        return None
    if has_request_context():
        session_version = session.get("auth_version", 0)
        current_version = get_active_user_auth_version(username, connection_factory)
        if (
            type(session_version) is not int
            or current_version is None
            or session_version != current_version
        ):
            return None
    return user["role"] or "user"


def get_active_user_auth_version(username, connection_factory=None):
    if not username:
        return None
    if connection_factory is None:
        from ..models.database import get_db
        connection_factory = get_db

    connection = connection_factory()
    try:
        user = connection.cursor().execute(
            "SELECT auth_version FROM users WHERE username=? AND is_active=TRUE",
            (username,),
        ).fetchone()
    finally:
        connection.close()

    if not user:
        return None
    version = user["auth_version"]
    return version if type(version) is int and version >= 0 else None


def _jwt_secret():
    return current_app.config["JWT_SECRET"] if has_app_context() else Config.JWT_SECRET


def generate_jwt_token(username, auth_version=0):
    """Generate JWT token for API authentication"""
    if type(auth_version) is not int or auth_version < 0:
        return None
    try:
        payload = {
            "user": username,
            "auth_version": auth_version,
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, _jwt_secret(), algorithm="HS256")
        return token
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        return None


def _decode_jwt_token(token):
    if not isinstance(token, str) or not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None

    username = payload.get("user")
    auth_version = payload.get("auth_version")
    if (
        not isinstance(username, str)
        or not username
        or type(auth_version) is not int
        or auth_version < 0
    ):
        return None
    return payload


def verify_jwt_token(token):
    payload = _decode_jwt_token(token)
    if not payload or not has_app_context():
        return None
    current_version = get_active_user_auth_version(payload["user"])
    return (
        payload["user"]
        if current_version == payload["auth_version"]
        else None
    )


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Missing authorization token"}), 401

        payload = _decode_jwt_token(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401
        username = payload["user"]
        current_version = get_active_user_auth_version(username)
        if current_version is None or current_version != payload["auth_version"]:
            return jsonify({"error": "Invalid or expired token"}), 401

        g.jwt_auth_version = payload["auth_version"]
        g.audit_actor = username
        g.audit_role = "api"
        return f(*args, **kwargs)
    return decorated

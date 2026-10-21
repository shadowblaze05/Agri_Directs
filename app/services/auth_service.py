import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, has_app_context, jsonify, request

from ..config import Config

logger = logging.getLogger(__name__)


def get_active_user_role(username, connection_factory=None):
    """Return the current active role for a username, or None if unavailable."""
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
    return user["role"] or "user"


def _jwt_secret():
    return current_app.config["JWT_SECRET"] if has_app_context() else Config.JWT_SECRET

def generate_jwt_token(username):
    """Generate JWT token for API authentication"""
    try:
        payload = {
            "user": username,
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, _jwt_secret(), algorithm="HS256")
        return token
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        return None


def verify_jwt_token(token):
    try:
        if not isinstance(token, str) or not token:
            return None
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        return payload.get("user")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """Decorator to protect API endpoints with JWT"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Missing authorization token"}), 401
        
        username = verify_jwt_token(token)
        if not username:
            return jsonify({"error": "Invalid or expired token"}), 401
        g.audit_actor = username
        g.audit_role = "api"
        return f(*args, **kwargs)
    return decorated

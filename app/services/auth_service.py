"""Authentication token helpers shared by API routes."""

import os
import logging
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import jsonify, request

logger = logging.getLogger(__name__)
JWT_SECRET = os.environ.get("JWT_SECRET", "jwt_secret_key_agridirect")

def generate_jwt_token(username):
    """Generate JWT token for API authentication"""
    try:
        payload = {
            "user": username,
            "exp": datetime.utcnow() + timedelta(hours=24),
            "iat": datetime.utcnow()
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return token
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        return None


def verify_jwt_token(token):
    """Verify JWT token and return username if valid"""
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
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
        
        return f(*args, **kwargs)
    return decorated

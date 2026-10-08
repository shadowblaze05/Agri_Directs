import json
import re

from flask import request
from sqlalchemy import insert

from ..extensions import db
from ..models.audit import AuditEvent

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_AUTH_ENDPOINTS = {"login", "logout", "register", "get_token"}
_ACTION_VERBS = {
    "create": "Created",
    "edit": "Updated",
    "update": "Updated",
    "delete": "Deleted",
    "remove": "Removed",
    "review": "Reviewed",
    "upload": "Uploaded",
    "like": "Liked",
    "comment": "Commented on",
    "reply": "Replied to",
    "buy": "Purchased",
    "confirm": "Confirmed",
    "approve": "Approved",
    "reject": "Rejected",
    "mark": "Updated",
}


def should_audit_request(endpoint, method, path):
    """Capture writes, authentication attempts, and admin-console access."""
    if not endpoint or endpoint == "static" or endpoint == "admin_audit_logs":
        return False
    return (
        method in _MUTATING_METHODS
        or endpoint in _AUTH_ENDPOINTS
        or path == "/admin"
        or path.startswith("/admin/")
    )


def _event_category(endpoint, path):
    if path == "/admin" or path.startswith("/admin/"):
        return "Administration"
    if endpoint in _AUTH_ENDPOINTS:
        return "Authentication"
    if endpoint.startswith("api_") or endpoint in {"get_token", "api_harvest"}:
        return "API"
    for category in ("inventory", "marketplace", "knowledge", "profile", "messages", "notifications"):
        if category in endpoint or category in path:
            return category.title()
    return "Application"


def _event_action(endpoint, method, category):
    special_actions = {
        "login": "Signed in",
        "logout": "Signed out",
        "register": "Created account",
        "get_token": "Requested API token",
        "api_harvest": "Submitted harvest via API",
    }
    if endpoint in special_actions:
        return special_actions[endpoint]

    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", endpoint).replace("_", " ").split()
    if words and words[0] in _ACTION_VERBS:
        verb = _ACTION_VERBS[words.pop(0)]
        if words and words[0] == "admin":
            words.pop(0)
        target = " ".join(words) or "record"
        return f"{verb} {target}"
    if words and words[0] == "admin":
        words.pop(0)
    target = " ".join(words) or category.lower()
    if method == "GET":
        return f"Viewed {target}"
    return f"{method.title()} {target}"


def record_request_event(status_code, duration_ms, actor, role):
    """Persist request context without collecting submitted fields or secrets."""
    endpoint = request.endpoint or "unknown"
    details = json.dumps(request.view_args or {}, sort_keys=True, separators=(",", ":"))
    category = _event_category(endpoint, request.path)
    event = {
        "actor": actor,
        "role": role,
        "action": _event_action(endpoint, request.method, category),
        "category": category,
        "method": request.method,
        "endpoint": endpoint,
        "path": request.path[:512],
        "ip_address": request.remote_addr,
        "user_agent": request.user_agent.string[:1000] if request.user_agent else None,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        "details": details,
    }
    with db.engine.begin() as connection:
        connection.execute(insert(AuditEvent.__table__).values(**event))

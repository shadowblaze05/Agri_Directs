"""Domain route registration for the Agri Directs Flask application."""

from . import admin, auth, home, inventory, knowledge, marketplace, profile


def register_routes(application):
    """Register all domain handlers on *application* without changing URLs."""
    if getattr(application, "_agri_routes_registered", False):
        return application
    for module in (auth, home, inventory, knowledge, marketplace, profile, admin):
        module.register(application)
    application._agri_routes_registered = True
    return application


__all__ = ["register_routes"]

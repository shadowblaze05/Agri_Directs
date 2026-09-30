"""Profile readiness checks shared by harvest submission routes."""

from ..services.geotag_service import validate_coordinates


def missing_harvest_profile_requirements(user):
    """Return the required profile items missing before harvest submissions."""
    if not user:
        return ["account"]

    missing = []
    for field, label in (
        ("first_name", "first name"),
        ("last_name", "last name"),
        ("email", "email address"),
        ("profile_picture", "camera-captured profile photo"),
        ("profile_photo_captured_at", "profile photo GPS capture"),
        ("geotag_location", "GPS-derived farm location"),
    ):
        if not user.get(field):
            missing.append(label)

    coordinates_valid = False
    if user.get("location_verified"):
        try:
            validate_coordinates(
                user.get("location_latitude"),
                user.get("location_longitude"),
            )
            coordinates_valid = True
        except ValueError:
            pass
    if not coordinates_valid:
        missing.append("verified profile GPS location")
    return missing

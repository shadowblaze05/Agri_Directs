from ..services.geotag_service import validate_coordinates


def missing_harvest_profile_requirements(user):
    if not user:
        return ["account"]

    missing = []
    for field, label in (
        ("first_name", "first name"),
        ("last_name", "last name"),
        ("email", "email address"),
        ("profile_picture", "profile photo"),
        ("profile_photo_captured_at", "profile photo timestamp"),
        ("geotag_location", "GPS-derived place name"),
    ):
        if not user.get(field):
            missing.append(label)

    coordinates_valid = False
    try:
        validate_coordinates(
            user.get("location_latitude"),
            user.get("location_longitude"),
        )
        coordinates_valid = True
    except ValueError:
        pass
    if not coordinates_valid:
        missing.append("profile GPS coordinates")
    return missing

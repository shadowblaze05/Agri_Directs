"""Validation and proximity checks for farm and harvest coordinates."""

import math
import re
import unicodedata

import requests


EARTH_RADIUS_METERS = 6_371_008.8
PSGC_API = "https://psgc.gitlab.io/api"


def validate_coordinates(latitude, longitude):
    """Return finite latitude/longitude floats or raise ``ValueError``."""
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        raise ValueError("Latitude and longitude must be valid numbers.") from None

    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("Latitude and longitude must be finite numbers.")
    if not -90 <= lat <= 90:
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not -180 <= lon <= 180:
        raise ValueError("Longitude must be between -180 and 180 degrees.")
    return lat, lon


def calculate_distance_meters(latitude_a, longitude_a, latitude_b, longitude_b):
    """Calculate great-circle distance between two coordinate pairs."""
    lat_a, lon_a = validate_coordinates(latitude_a, longitude_a)
    lat_b, lon_b = validate_coordinates(latitude_b, longitude_b)

    lat_a, lon_a, lat_b, lon_b = map(
        math.radians, (lat_a, lon_a, lat_b, lon_b)
    )
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    central_angle = 2 * math.asin(math.sqrt(min(1.0, haversine)))
    return EARTH_RADIUS_METERS * central_angle


def verify_crop_location(
    user_latitude,
    user_longitude,
    crop_latitude,
    crop_longitude,
    max_distance_meters,
):
    """Return a proximity status and distance, or manual review if unavailable."""
    values = (user_latitude, user_longitude, crop_latitude, crop_longitude)
    if any(value is None or value == "" for value in values):
        return "manual_review", None

    distance = calculate_distance_meters(
        user_latitude, user_longitude, crop_latitude, crop_longitude
    )
    status = "within_range" if distance <= max_distance_meters else "outside_range"
    return status, distance
def reverse_geocode_coordinates(latitude, longitude):
    """Resolve coordinates to a human-readable place using OpenStreetMap Nominatim."""
    lat, lon = validate_coordinates(latitude, longitude)
    response = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "zoom": 14,
            "addressdetails": 1,
        },
        headers={"User-Agent": "Agri-Direct/1.0"},
        timeout=8,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or not isinstance(result.get("address"), dict):
        raise ValueError("No address could be resolved for this location.")

    address = result["address"]
    locality = (
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("village")
        or address.get("county")
    )
    parts = [
        address.get("neighbourhood")
        or address.get("suburb")
        or address.get("village"),
        locality,
        address.get("state_district") or address.get("province") or address.get("state"),
        address.get("country"),
    ]
    location = ", ".join(dict.fromkeys(part.strip() for part in parts if part and part.strip()))
    if not location:
        location = result.get("display_name", "").strip()
    if not location:
        raise ValueError("No address could be resolved for this location.")
    return location[:255]


def _normalize_location_name(value):
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    normalized = re.sub(r"^(city|municipality) of ", "", normalized)
    normalized = re.sub(r" (city|municipality)$", "", normalized)
    return normalized


def _psgc_records(path):
    response = requests.get(f"{PSGC_API}/{path}/", timeout=8)
    response.raise_for_status()
    records = response.json()
    if not isinstance(records, list) or any(
        not isinstance(record, dict)
        or not isinstance(record.get("code"), str)
        or not isinstance(record.get("name"), str)
        for record in records
    ):
        raise ValueError("The PSGC API returned an invalid location list.")
    return records


def resolve_psgc_location(geotag_location):
    """Match a reverse-geocoded place to PSGC's official location hierarchy."""
    parts = [part.strip() for part in geotag_location.split(",") if part.strip()]
    candidates = {
        _normalize_location_name(part)
        for part in parts
        if _normalize_location_name(part) and _normalize_location_name(part) != "philippines"
    }
    if not candidates:
        return None

    provinces = _psgc_records("provinces")
    regions = _psgc_records("regions")
    province_names = {
        province.get("code"): province.get("name", "")
        for province in provinces
    }
    region_names = {
        region.get("code"): region.get("name", "")
        for region in regions
    }
    locality_candidates = candidates - {
        _normalize_location_name(name)
        for name in (*province_names.values(), *region_names.values())
    }
    cities = _psgc_records("cities-municipalities")
    matched_cities = [
        city for city in cities
        if _normalize_location_name(city["name"]) in locality_candidates
    ]
    if not matched_cities:
        return None

    matching_province_codes = {
        code for code, name in province_names.items()
        if _normalize_location_name(name) in candidates
    }
    if matching_province_codes:
        matched_cities = [
            city for city in matched_cities
            if city.get("provinceCode") in matching_province_codes
        ]
        if not matched_cities:
            return None
    if len(matched_cities) != 1:
        return None
    city = matched_cities[0]

    location_parts = [city["name"]]
    province = province_names.get(city.get("provinceCode"))
    region = region_names.get(city.get("regionCode"))

    barangay_names = candidates - {
        _normalize_location_name(city["name"]),
        _normalize_location_name(province or ""),
        _normalize_location_name(region or ""),
    }
    if barangay_names:
        barangays = _psgc_records(f"cities-municipalities/{city['code']}/barangays")
        barangay = next(
            (
                record["name"] for record in barangays
                if _normalize_location_name(record.get("name", "")) in barangay_names
            ),
            None,
        )
        if barangay:
            location_parts.insert(0, barangay)
    if province:
        location_parts.append(province)
    if region:
        location_parts.append(region)
    return ", ".join(location_parts)[:255]

"""Geocoding service used by location-aware routes."""

import os
import logging

logger = logging.getLogger(__name__)

def geocode_location(location):
    """Geocode a location string to lat/lng using Google Maps API or a fallback."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        # fallback coordinates if no API key is configured
        lat = 14.5995 + (hash(location) % 100 - 50) / 100.0
        lng = 120.9842 + (hash(location + 'salt') % 100 - 50) / 100.0
        return lat, lng

    try:
        if location and not location.lower().endswith('philippines'):
            location_query = f"{location}, Philippines"
        else:
            location_query = location

        try:
            import requests
        except ImportError:
            logger.warning("requests is not installed; geocoding will use fallback coordinates")
            raise

        if api_key:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(location_query)}&key={api_key}"
            response = requests.get(url, timeout=5)
            data = response.json()
            if data.get('status') == 'OK' and data.get('results'):
                loc = data['results'][0]['geometry']['location']
                return loc['lat'], loc['lng']
        else:
            nominatim_url = "https://nominatim.openstreetmap.org/search"
            response = requests.get(
                nominatim_url,
                params={"q": location_query, "format": "json", "limit": 1},
                headers={"User-Agent": "Agri-Direct/1.0"},
                timeout=5
            )
            if response.ok:
                results = response.json()
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
    except ImportError:
        logger.warning("Geocode skipped because requests is not installed")
    except Exception as e:
        logger.warning(f"Geocode lookup failed for '{location}': {e}")

    if not location:
        return 14.5995, 120.9842

    lat = 14.5995 + (hash(location) % 100 - 50) / 100.0
    lng = 120.9842 + (hash(location + 'salt') % 100 - 50) / 100.0
    return lat, lng

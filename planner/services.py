from __future__ import annotations

from typing import Any

import requests

USER_AGENT = "truck-planner-assessment/1.0"


class MapServiceError(Exception):
    pass


def geocode_location(query: str) -> dict[str, Any]:
    clean_query = query.strip()
    if not clean_query:
        raise MapServiceError("Location value cannot be empty.")
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": clean_query, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MapServiceError("Geocoding service unavailable.") from exc
    items = response.json()
    if not items:
        raise MapServiceError(f"Could not geocode location: {clean_query}")
    item = items[0]
    return {
        "label": item.get("display_name", clean_query),
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
    }


def route_between_points(start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
    coordinates = f'{start["lon"]},{start["lat"]};{end["lon"]},{end["lat"]}'
    try:
        response = requests.get(
            f"https://router.project-osrm.org/route/v1/driving/{coordinates}",
            params={"overview": "full", "geometries": "geojson", "steps": "true"},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MapServiceError("Routing service unavailable.") from exc
    payload = response.json()
    routes = payload.get("routes", [])
    if not routes:
        raise MapServiceError("Unable to build route from map service.")
    route = routes[0]
    return {
        "distance_meters": route["distance"],
        "duration_seconds": route["duration"],
        "geometry": route["geometry"]["coordinates"],
        "steps": route["legs"][0].get("steps", []),
    }

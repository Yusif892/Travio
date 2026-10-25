from __future__ import annotations

import math

from app.planner.config import (
    DEFAULT_TRAVEL_MINUTES,
    TRAVEL_BUFFER_MINUTES,
)
from app.planner.models import GeoPoint

EARTH_RADIUS_KM = 6371.0


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lon1 = math.radians(a.lat), math.radians(a.lng)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lng)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def travel_minutes(
    a: GeoPoint | None,
    b: GeoPoint | None,
    speed_kmh: float,
) -> int:
    if a is None or b is None:
        return DEFAULT_TRAVEL_MINUTES
    if speed_kmh <= 0:
        return DEFAULT_TRAVEL_MINUTES
    raw = haversine_km(a, b) / speed_kmh * 60
    return math.ceil(raw + TRAVEL_BUFFER_MINUTES)

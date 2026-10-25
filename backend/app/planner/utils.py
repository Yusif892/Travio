from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.planner.models import GeoPoint


def get_value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enum_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    enum_member = getattr(value, "value", value)
    return str(enum_member).lower()


def as_geo_point(value: Any) -> GeoPoint | None:
    if value is None:
        return None
    if isinstance(value, GeoPoint):
        return value
    if isinstance(value, Mapping):
        lat, lng = value.get("lat"), value.get("lng")
    else:
        lat, lng = getattr(value, "lat", None), getattr(value, "lng", None)
    if lat is None or lng is None:
        return None
    return GeoPoint(lat=float(lat), lng=float(lng))


def to_geo(lat: Any, lng: Any) -> GeoPoint | None:
    if lat is None or lng is None:
        return None
    return GeoPoint(lat=float(lat), lng=float(lng))

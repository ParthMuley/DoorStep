"""Geometry helpers (Shapely). GeoJSON coordinates are [lon, lat]."""

from __future__ import annotations

import math
from typing import Any, Optional

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def polygon(geometry: dict[str, Any]) -> Optional[BaseGeometry]:
    """Valid, non-empty (Multi)Polygon or None."""
    try:
        geom = shape(geometry)
    except Exception:
        return None
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid:
        return None
    return geom


def covers(geom: BaseGeometry, lat: float, lon: float) -> bool:
    """Inside OR on the boundary (``covers``, not ``contains``)."""
    return geom.covers(Point(lon, lat))


def distance_to_km(geom: BaseGeometry, lat: float, lon: float) -> float:
    """Great-circle distance from a point to the nearest point of a geometry (0 if inside)."""
    pt = Point(lon, lat)
    if geom.covers(pt):
        return 0.0
    nearest = nearest_points(geom, pt)[0]
    return haversine_km(lat, lon, nearest.y, nearest.x)

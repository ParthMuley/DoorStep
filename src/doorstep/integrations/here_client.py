"""HERE Routing v8 client for the Route agent. DOORSTEP DEMO.

Verified from HERE docs (2026-10-17, see docs/integration-decisions.md):
- `avoid[areas]=polygon:lat,lng;lat,lng;...` (latitude first), several areas joined by `|`;
- at most 20 polygons per request (we refuse beyond the limit; never truncate);
- a route that can't avoid an area carries a critical notice `violatedBlockedRoad`;
- `via=lat,lng` adds a stop; each leg is a `section`; `return=polyline` gives HERE's
  flexible polyline (decoded with the official `flexpolyline` package).

Safety: avoid areas only ever ENLARGE when simplified (buffer outward, then convex hull,
then the minimum rotated rectangle), so a simplified order zone always covers the real
one. Cost: one call per accepted assignment, cached, and a daily cap (free tier).
"""

import math
import os
from dataclasses import dataclass, field
from typing import Any

import flexpolyline
import httpx
from shapely.geometry import LineString, Polygon, shape
from shapely.geometry.base import BaseGeometry

ROUTER_URL = "https://router.hereapi.com/v8/routes"
MAX_POLYGONS = int(os.getenv("HERE_MAX_AVOID_POLYGONS", "20"))
MAX_VERTICES = int(os.getenv("HERE_MAX_POLYGON_VERTICES", "20"))
AVOID_MARGIN_M = float(os.getenv("HERE_AVOID_MARGIN_M", "30"))
MAX_DIRECTIONS = 6


class RouteRefused(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


@dataclass
class HereRoute:
    coordinates: list[tuple[float, float]]  # (lon, lat), GeoJSON order
    distance_m: int
    duration_s: int
    leg_durations_s: list[int]
    directions: list[str]
    notices: list[dict[str, Any]] = field(default_factory=list)

    @property
    def violated(self) -> bool:
        return any(str(n.get("code", "")).startswith("violated") or n.get("severity") == "critical"
                   for n in self.notices)

    def geojson(self) -> dict[str, Any]:
        return {"type": "LineString", "coordinates": [list(c) for c in self.coordinates]}


def _to_local(geom: BaseGeometry, lat0: float):
    ky, kx = 110_540.0, 111_320.0 * math.cos(math.radians(lat0))  # metres per degree
    from shapely.ops import transform
    to_m = lambda x, y, z=None: (x * kx, y * ky)  # noqa: E731
    from_m = lambda x, y, z=None: (x / kx, y / ky)  # noqa: E731
    return transform(to_m, geom), (lambda g: transform(from_m, g))


def enlarge_only(polygon: BaseGeometry, margin_m: float = AVOID_MARGIN_M,
                 max_vertices: int = MAX_VERTICES) -> Polygon:
    """Outward-buffered polygon with <= max_vertices that always COVERS the input."""
    lat0 = polygon.centroid.y
    local, back = _to_local(polygon, lat0)
    grown = local.buffer(margin_m, quad_segs=2)
    for candidate in (grown, grown.convex_hull, grown.minimum_rotated_rectangle):
        if candidate.geom_type == "Polygon" and len(candidate.exterior.coords) - 1 <= max_vertices:
            out = back(candidate)
            if not out.buffer(1e-9).covers(polygon):  # safety invariant; never skipped (not an assert)
                raise RouteRefused("AVOID_AREA_TOO_COMPLEX", "simplified area would not cover the zone")
            return out
    raise RouteRefused("AVOID_AREA_TOO_COMPLEX", "could not reduce an avoid area safely")


def avoid_param(avoid_areas: list[dict[str, Any]]) -> str | None:
    """B's avoid areas (GeoJSON Polygon/MultiPolygon) -> HERE `avoid[areas]` value."""
    polygons: list[Polygon] = []
    for area in avoid_areas:
        geom = shape(area["geometry"])
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        polygons += [enlarge_only(p) for p in parts]
    if len(polygons) > MAX_POLYGONS:
        raise RouteRefused("TOO_MANY_AVOID_AREAS", f"{len(polygons)} > {MAX_POLYGONS}")
    if not polygons:
        return None
    return "|".join("polygon:" + ";".join(f"{lat:.6f},{lon:.6f}" for lon, lat in list(p.exterior.coords)[:-1])
                    for p in polygons)


def _latlng(stop: dict[str, Any]) -> str:
    return f"{stop['lat']:.6f},{stop['lon']:.6f}"


class HereRouter:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 20.0):
        self.api_key = api_key if api_key is not None else os.getenv("HERE_API_KEY", "").strip()
        self._transport, self._timeout = transport, timeout

    async def route(self, stops: list[dict[str, Any]], avoid_areas: list[dict[str, Any]]) -> HereRoute | None:
        """stops: [VOLUNTEER_START, PICKUP, SHELTER] as {lat, lon}. None = HERE found no route."""
        if not self.api_key:
            raise RouteRefused("HERE_NOT_CONFIGURED", "HERE_API_KEY not set")
        params: dict[str, Any] = {
            "transportMode": "car", "origin": _latlng(stops[0]), "destination": _latlng(stops[-1]),
            "via": [_latlng(s) for s in stops[1:-1]],
            "return": "polyline,summary,actions,instructions", "lang": "en-US", "apiKey": self.api_key}
        avoid = avoid_param(avoid_areas)
        if avoid:
            params["avoid[areas]"] = avoid
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            resp = await client.get(ROUTER_URL, params=params)
        if resp.status_code != 200:
            raise RouteRefused(f"HERE_HTTP_{resp.status_code}", "HERE request failed")
        body = resp.json()
        routes = body.get("routes") or []
        if not routes:
            return None
        sections = routes[0]["sections"]
        coords: list[tuple[float, float]] = []
        for s in sections:
            pts = [(lng, lat) for lat, lng, *_ in flexpolyline.decode(s["polyline"])]
            coords += pts if not coords else pts[1:]
        notices = [n for s in sections for n in s.get("notices", [])] + body.get("notices", [])
        directions = [a["instruction"] for s in sections for a in s.get("actions", []) if a.get("instruction")]
        return HereRoute(coordinates=coords,
                         distance_m=sum(s["summary"]["length"] for s in sections),
                         duration_s=sum(s["summary"]["duration"] for s in sections),
                         leg_durations_s=[s["summary"]["duration"] for s in sections],
                         directions=directions[:MAX_DIRECTIONS], notices=notices)


def line(coords: list[tuple[float, float]]) -> LineString:
    return LineString(coords)

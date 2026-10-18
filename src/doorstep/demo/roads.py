"""Fictional road gazetteer for the demo (contract v2.1 §5.9). ILLUSTRATIVE ONLY.
Road names map to synthetic segments; unknown names stay unmapped (shown, never routed)."""

from __future__ import annotations

import re
from typing import Any, Optional

ROADS: dict[str, dict[str, Any]] = {
    "seg_ridge_ave": {"name": "Ridge Ave", "aliases": ["ridge avenue", "ridge ave", "ridge"],
                      "geometry": {"type": "LineString", "coordinates": [[-118.090, 34.100], [-118.075, 34.095]]}},
    "seg_canyon_rd": {"name": "Canyon Rd", "aliases": ["canyon road", "canyon rd", "canyon"],
                      "geometry": {"type": "LineString", "coordinates": [[-118.100, 34.090], [-118.085, 34.088]]}},
    "seg_valley_blvd": {"name": "Valley Blvd", "aliases": ["valley boulevard", "valley blvd"],
                        "geometry": {"type": "LineString", "coordinates": [[-118.110, 34.095], [-118.096, 34.101]]}},
    "seg_civic_way": {"name": "Civic Way", "aliases": ["civic way"],
                      "geometry": {"type": "LineString", "coordinates": [[-118.080, 34.092], [-118.070, 34.089]]}},
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", name.lower())).strip()


def resolve(road_name: str) -> Optional[str]:
    n = _norm(road_name)
    for seg_id, road in ROADS.items():
        if n == _norm(road["name"]) or n in {_norm(a) for a in road["aliases"]}:
            return seg_id
    return None

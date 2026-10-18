"""Route map images hosted by B (plan rev 6 §000.7). DOORSTEP DEMO.

A's Route agent renders the PNG with HERE (key stays in A's process) and uploads it here;
ASI:One loads `hero_image` straight from the viewer's browser, so GET is public.
* `map_id` is chosen by A, unguessable (>= 24 url-safe chars). No listing endpoint.
* The image shows the pickup point: A sends the URL only to the assigned volunteer.
* Expires after MAP_TTL_HOURS (24) or when the linked assignment is completed/canceled.
* Never log the map id together with personal data.
"""

from __future__ import annotations

import os
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional

from bson import Binary

from . import deadlines
from .errors import Conflict, NotFound

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

MAP_ID = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_BYTES = 300 * 1024
ENDED = {"COMPLETED", "CANCELED", "DECLINED", "UNRESOLVED"}


def ttl_hours() -> float:
    return float(os.environ.get("MAP_TTL_HOURS", "24"))


def public_base_url(fallback: str) -> str:
    """PUBLIC_BASE_URL, else Render's RENDER_EXTERNAL_URL (https), else the request's own base URL."""
    return (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or fallback).rstrip("/")


class MapService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store

    def put(self, map_id: str, data: bytes, *, assignment_id: Optional[str], base_url: str) -> dict[str, Any]:
        if not MAP_ID.match(map_id or ""):
            raise Conflict("map_id must be 24-64 url-safe characters (unguessable)", code="VALIDATION_ERROR")
        if len(data) > MAX_BYTES:
            raise Conflict(f"Image larger than {MAX_BYTES // 1024} KB", code="IMAGE_TOO_LARGE")
        if not data.startswith(PNG_MAGIC):
            raise Conflict("Body must be a PNG image", code="VALIDATION_ERROR")
        if assignment_id:
            self.store.get_assignment(assignment_id)  # 404 if unknown
        expires = deadlines.iso(deadlines.now() + timedelta(hours=ttl_hours()))
        self.db.coll("maps").replace_one({"_id": map_id}, {"_id": map_id, "png": Binary(data), "bytes": len(data),
                                                           "assignment_id": assignment_id, "expires_at": expires,
                                                           "created_at": deadlines.iso(deadlines.now())}, upsert=True)
        self.engine.events.append("ROUTE_MAP_STORED", case_id=None, data={"bytes": len(data)})  # no map id logged
        return {"schema_version": "2.0", "url": f"{public_base_url(base_url)}/maps/{map_id}.png",
                "expires_at": expires, "bytes": len(data)}

    def get(self, map_id: str) -> bytes:
        d = self.db.coll("maps").find_one({"_id": map_id}) if MAP_ID.match(map_id or "") else None
        if not d or deadlines.passed(d.get("expires_at")):
            raise NotFound("Map not found or expired")
        if d.get("assignment_id"):
            a = self.db.coll("assignments").find_one({"_id": d["assignment_id"]})
            if a is None or a.get("status") in ENDED:
                raise NotFound("Map not found or expired")
        return bytes(d["png"])

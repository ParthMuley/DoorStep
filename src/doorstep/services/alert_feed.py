"""B's synthetic evacuation feed, rendered in the EXACT Cal OES GeoJSON shape so
the Calamity agent and ``/alerts/ingest`` use one code path for synthetic and
real data. Demo control: ``POST /demo/alerts/trigger``. Everything is fictional.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from doorstep.models import IncidentPoint, SyntheticFeature, SyntheticFeedState

from .db import Database
from .errors import Conflict, NotFound

FEED_DOC_ID = "synthetic_caloes"


def now_ms() -> int:
    return int(time.time() * 1000)


def _rect(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": [[[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat],
                                                [min_lon, max_lat], [min_lon, min_lat]]]}


# Fictional polygons (see demo/seed.py for resident coordinates).
ZONE_3_SECTOR_B = _rect(-118.100, 34.098, -118.090, 34.104)  # WARNING, covers Maria
ZONE_3_SECTOR_A = _rect(-118.100, 34.104, -118.090, 34.110)  # ORDER, covers David (shares an edge with B)

PRESETS: dict[str, dict[str, Any]] = {
    "ZONE_3_WARNING": {"features": [("sim-0001", "zone_3_sector_b", "DEMO Zone 3 Sector B", "Evacuation Warning",
                                     ZONE_3_SECTOR_B)]},
    "ZONE_3_ORDER": {"features": [("sim-0002", "zone_3_sector_a", "DEMO Zone 3 Sector A", "Evacuation Order",
                                   ZONE_3_SECTOR_A)]},
}
PRESETS["ZONE_3_WILDFIRE"] = {
    "features": PRESETS["ZONE_3_WARNING"]["features"] + PRESETS["ZONE_3_ORDER"]["features"],
    "incidents": [IncidentPoint(incident_id="inc_001", calamity_type="WILDFIRE", lat=34.1120, lon=-118.0850,
                                radius_km=5.0, label="DEMO fire origin (synthetic)")],
}


class SyntheticFeed:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- state
    def state(self) -> SyntheticFeedState:
        doc = self.db.coll("synthetic_feed").find_one({"_id": FEED_DOC_ID})
        if not doc:
            return SyntheticFeedState()
        return SyntheticFeedState.model_validate({k: v for k, v in doc.items() if not k.startswith("_")})

    def _save(self, st: SyntheticFeedState) -> None:
        self.db.coll("synthetic_feed").update_one({"_id": FEED_DOC_ID}, {"$set": st.model_dump(mode="json")},
                                                  upsert=True)

    # -------------------------------------------------------------- control
    def trigger(self, action: str, *, preset: Optional[str] = None, zone_id: Optional[str] = None,
                status: Optional[str] = None, event_type: Optional[str] = None,
                geometry: Optional[dict] = None, expires_in_minutes: Optional[int] = None,
                freeze_age_minutes: int = 0) -> SyntheticFeedState:
        st = self.state()
        action = action.upper()
        ts = now_ms()
        if action in ("ISSUE", "UPDATE"):
            specs = []
            if preset:
                if preset not in PRESETS:
                    raise NotFound(f"Unknown preset {preset!r}; options: {sorted(PRESETS)}")
                specs = PRESETS[preset]["features"]
                for inc in PRESETS[preset].get("incidents", []):
                    st.incidents = [i for i in st.incidents if i.incident_id != inc.incident_id] + [inc]
            elif zone_id and status:
                existing = next((f for f in st.features if f.zone_id == zone_id), None)
                geom = geometry or (existing.geometry if existing else None)
                if geom is None:
                    raise Conflict("geometry required for a new zone", code="VALIDATION_ERROR")
                gid = existing.global_id if existing else f"sim-{zone_id}"
                specs = [(gid, zone_id, existing.zone_name if existing else f"DEMO {zone_id}", status, geom)]
            else:
                raise Conflict("Provide a preset, or zone_id + status", code="VALIDATION_ERROR")
            for gid, zid, name, raw_status, geom in specs:
                feats = [f for f in st.features if f.global_id != gid]
                obj_id = next((f.object_id for f in st.features if f.global_id == gid), len(st.features) + 1)
                feats.append(SyntheticFeature(object_id=obj_id, global_id=gid, zone_id=zid, zone_name=name,
                                              status=status if (not preset and status) else raw_status,
                                              event_type=event_type or "Wildfire (SIMULATED)",
                                              geometry=geom, edit_date_ms=ts,
                                              expires_in_minutes=expires_in_minutes))
                st.features = sorted(feats, key=lambda f: f.object_id)
        elif action == "CANCEL":
            # Explicit lift: the record stays in the feed with STATUS "Normal" (inactive).
            targets = self._targets(st, preset, zone_id)
            for f in st.features:
                if f.global_id in targets:
                    f.status, f.edit_date_ms = "Normal", ts
            st.incidents = [] if preset or not zone_id else st.incidents
        elif action == "EXPIRE":
            # The record disappears from the feed (canceled only after 2 consecutive misses).
            targets = self._targets(st, preset, zone_id)
            st.features = [f for f in st.features if f.global_id not in targets]
        elif action == "FREEZE_FEED":
            st.frozen_at_ms = ts - max(0, freeze_age_minutes) * 60_000
        elif action == "UNFREEZE_FEED":
            st.frozen_at_ms = None
        else:
            raise Conflict(f"Unknown action {action!r}", code="VALIDATION_ERROR")
        st.version += 1
        self._save(st)
        return st

    @staticmethod
    def _targets(st: SyntheticFeedState, preset: Optional[str], zone_id: Optional[str]) -> set[str]:
        if preset:
            if preset not in PRESETS:
                raise NotFound(f"Unknown preset {preset!r}")
            return {spec[0] for spec in PRESETS[preset]["features"]}
        if zone_id:
            return {f.global_id for f in st.features if f.zone_id == zone_id}
        return {f.global_id for f in st.features}

    # --------------------------------------------------------------- render
    def render_caloes(self) -> dict[str, Any]:
        """Cal OES CA_EVACUATIONS layer, f=geojson shape."""
        st = self.state()
        statewide = st.frozen_at_ms if st.frozen_at_ms is not None else now_ms()
        features = []
        for f in st.features:
            features.append({
                "type": "Feature", "id": f.object_id, "geometry": f.geometry,
                "properties": {
                    "OBJECTID": f.object_id, "COUNTY": "Los Angeles (SIMULATED)", "CITY": "Demo City",
                    "ZONE_NAME": f.zone_name, "ZONE_ID": f.zone_id, "STATUS": f.status, "EVENT_TYPE": f.event_type,
                    "CRITICAL_INFO": "SIMULATION ONLY", "PUBLIC_INFO": "SIMULATION ONLY - not a real evacuation",
                    "EDIT_DATE": min(f.edit_date_ms, statewide), "STATEWIDE_LAST_UPDATED": statewide,
                    "NOTES": "DOORSTEP DEMO", "GlobalID": f.global_id,
                },
            })
        return {"type": "FeatureCollection", "features": features}

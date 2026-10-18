"""Alerts, geofencing, check-ins and volunteer outreach (contract v2.0 §5.3–§5.4).

Rules:
* Only ``OFFICIAL_SIMULATION`` alerts can trigger check-ins and outreach; live
  ``REAL_WORLD`` data is display-only.
* STATUS is mapped case-insensitively; unknown strings are rejected, never guessed.
* A record is canceled only by an explicit inactive status or after it is
  missing from 2 consecutive successful ingests (Cal OES rebuild gap).
* Zones: polygon ``covers`` (edge = inside); ORDER > SHELTER_IN_PLACE > WARNING >
  OUTSIDE_KNOWN_ZONES; stale feed → STALE; no data / uncertain geocode → UNKNOWN.
  Never "safe". A radius around an incident is awareness only.
* Nothing is triggered from stale data.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from doorstep.demo import seed
from doorstep.models import (
    AlertStatus,
    AvailabilityState,
    Case,
    CommunicationStatus as C,
    FeedState,
    ResidentProfile,
    SourceType,
    Verification,
    VolunteerAvailability,
    ZoneAlert,
    ZoneStatus,
    utc_now_iso,
)

from . import geo, intake, templates
from .alert_feed import SyntheticFeed
from .errors import Conflict, FeedInvalid, NotFound

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

SYNTHETIC_SOURCE_ID = "SYNTHETIC_CALOES"
ACTIVE_FOR_CHECKIN = (AlertStatus.WARNING.value, AlertStatus.ORDER.value)
DOMINANCE = [AlertStatus.ORDER.value, AlertStatus.SHELTER_IN_PLACE.value, AlertStatus.WARNING.value]
CANCEL_AFTER_MISSES = 2

STATUS_MAP = {
    "evacuation order": AlertStatus.ORDER, "evacuation warning": AlertStatus.WARNING,
    "shelter in place": AlertStatus.SHELTER_IN_PLACE, "normal": AlertStatus.INACTIVE,
    "clear to repopulate": AlertStatus.INACTIVE,
}


def normalize_status(raw: Optional[str]) -> Optional[AlertStatus]:
    if not raw:
        return None
    key = re.sub(r"[\s_\-]+", " ", raw).strip().lower()
    return STATUS_MAP.get(key)


def normalize_event_type(raw: Optional[str]) -> str:
    if not raw:
        return "UNKNOWN"
    low = raw.lower()
    for words, kind in ((("fire", "wildfire"), "WILDFIRE"), (("flood",), "FLOOD"), (("earthquake", "quake"), "EARTHQUAKE"),
                        (("storm", "wind", "hurricane", "tornado"), "STORM"), (("heat",), "HEAT")):
        if any(w in low for w in words):
            return kind
    return "OTHER"


def _ms_to_iso(ms: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _iso_age_seconds(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _strip(doc: Optional[dict]) -> dict:
    return {k: v for k, v in (doc or {}).items() if not k.startswith("_")}


class AlertService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store
        self.events = engine.events
        self.feed = SyntheticFeed(engine.db)

    # ------------------------------------------------------------ settings
    @staticmethod
    def stale_after_seconds() -> int:
        return int(os.environ.get("ALERT_STALE_AFTER_SECONDS", "900"))

    @staticmethod
    def outreach_max_orgs() -> int:
        return int(os.environ.get("OUTREACH_MAX_ORGS", "3"))

    # --------------------------------------------------------------- storage
    def _alerts(self, query: Optional[dict] = None) -> list[ZoneAlert]:
        return [ZoneAlert.model_validate(_strip(d))
                for d in self.db.coll("zone_alerts").find(query or {}).sort("_ord", 1)]

    def _save_alert(self, a: ZoneAlert) -> None:
        self.db.coll("zone_alerts").update_one(
            {"_id": a.alert_id},
            {"$set": {**a.model_dump(mode="json"), "_source_key": f"{a.source_id}:{a.source_record_id}"},
             "$setOnInsert": {"_ord": self.db.next_ord()}}, upsert=True)

    def _alert_by_source(self, source_id: str, record_id: str) -> Optional[ZoneAlert]:
        d = self.db.coll("zone_alerts").find_one({"_source_key": f"{source_id}:{record_id}"})
        return ZoneAlert.model_validate(_strip(d)) if d else None

    def get_alert(self, alert_id: str) -> ZoneAlert:
        d = self.db.coll("zone_alerts").find_one({"_id": alert_id})
        if not d:
            raise NotFound(f"Alert {alert_id!r} not found")
        return ZoneAlert.model_validate(_strip(d))

    def _feed_state(self, source_id: str) -> Optional[FeedState]:
        d = self.db.coll("feeds").find_one({"_id": source_id})
        return FeedState.model_validate(_strip(d)) if d else None

    def _save_feed(self, f: FeedState) -> None:
        self.db.coll("feeds").update_one({"_id": f.source_id}, {"$set": f.model_dump(mode="json")}, upsert=True)

    # ------------------------------------------------------------- freshness
    def freshness(self, source_id: str) -> str:
        f = self._feed_state(source_id)
        if f is None or not f.last_success_at:
            return "NO_DATA"
        limit = self.stale_after_seconds()
        for iso in (f.source_updated_at, f.last_success_at):
            age = _iso_age_seconds(iso)
            if age is not None and age > limit:
                return "STALE"
        return "FRESH"

    def simulated_freshness(self) -> str:
        states = [_strip(d) for d in self.db.coll("feeds").find({"source_type": SourceType.OFFICIAL_SIMULATION.value})]
        if not states:
            return "NO_DATA"
        values = {self.freshness(s["source_id"]) for s in states}
        return "STALE" if "STALE" in values else ("NO_DATA" if values == {"NO_DATA"} else "FRESH")

    # -------------------------------------------------------------- geofence
    def zone_for(self, profile: ResidentProfile) -> dict[str, Any]:
        """Zone status for a resident from ACTIVE SIMULATED alerts. Never 'safe'."""
        if profile.address.geocode_confidence != "HIGH":
            return {"zone_status": ZoneStatus.UNKNOWN.value, "zone_sources": [], "reason": "UNCERTAIN_GEOCODE"}
        fresh = self.simulated_freshness()
        if fresh == "NO_DATA":
            return {"zone_status": ZoneStatus.UNKNOWN.value, "zone_sources": [], "reason": "NO_FEED_DATA"}
        covering = []
        for a in self._alerts({"active": True, "source_type": SourceType.OFFICIAL_SIMULATION.value}):
            geom = geo.polygon(a.geometry)
            if geom is not None and geo.covers(geom, profile.address.lat, profile.address.lon):
                covering.append(a)
        sources = [{"alert_id": a.alert_id, "status": a.status, "source_id": a.source_id,
                    "freshness": self.freshness(a.source_id)} for a in covering]
        if fresh == "STALE":
            return {"zone_status": ZoneStatus.STALE.value, "zone_sources": sources, "reason": "FEED_STALE"}
        for status in DOMINANCE:
            if any(a.status == status for a in covering):
                return {"zone_status": status, "zone_sources": sources, "reason": None}
        return {"zone_status": ZoneStatus.OUTSIDE_KNOWN_ZONES.value, "zone_sources": sources, "reason": None}

    def same_event_alert_ids(self, alert_id: Optional[str]) -> set[str]:
        """Active simulated alerts of the same calamity type as ``alert_id`` (one wildfire can have several
        zone records). Volunteer availability given for any of them counts for all of them."""
        if not alert_id:
            return set()
        try:
            base = self.get_alert(alert_id)
        except NotFound:
            return set()
        return {a.alert_id for a in self._alerts({"active": True, "source_type": SourceType.OFFICIAL_SIMULATION.value})
                if a.calamity_type == base.calamity_type} | ({alert_id} if base.active else set())

    def zone_status_label(self, profile: ResidentProfile) -> str:
        return self.zone_for(profile)["zone_status"]

    def _residents_in(self, alert: ZoneAlert) -> list[ResidentProfile]:
        geom = geo.polygon(alert.geometry)
        if geom is None:
            return []
        return [p for p in self.store.list_resident_profiles()
                if p.address.geocode_confidence == "HIGH" and geo.covers(geom, p.address.lat, p.address.lon)]

    # ---------------------------------------------------------------- ingest
    def ingest(self, *, source_id: str, source_type: str, url: Optional[str], fetched_at: Optional[str],
               fetch_ok: bool, http_status: Optional[int], error: Optional[str], payload: Optional[dict],
               idempotency_key: Optional[str], correlation_id: str = "") -> dict[str, Any]:
        source_type = SourceType(source_type).value
        fetched_at = fetched_at or utc_now_iso()
        key = idempotency_key or f"{source_id}:{fetched_at}"
        prior = self.db.coll("ingests").find_one({"_id": key})
        if prior:
            return {**_strip(prior), "duplicate": True}

        feed = self._feed_state(source_id) or FeedState(source_id=source_id, source_type=source_type, url=url)
        feed.url, feed.last_ingest_at = url or feed.url, fetched_at

        if not fetch_ok:
            feed.consecutive_failures += 1
            self._save_feed(feed)
            self.events.append("ALERT_FEED_FETCH_FAILED", case_id=None, correlation_id=correlation_id,
                               data={"source_id": source_id, "http_status": http_status, "error": (error or "")[:200]})
            return self._finish(key, {"source_id": source_id, "fetch_ok": False, "feed_freshness": self.freshness(source_id),
                                      "records_received": 0, "records_rejected": [], "new_alerts": [],
                                      "changed_alerts": [], "canceled_alerts": [], "pending_cancellation": [],
                                      "affected_cases": [], "checkins_sent": [], "outreach_orgs": [],
                                      "notify_coordinator": False})

        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection" \
                or not isinstance(payload.get("features"), list):
            feed.consecutive_failures += 1
            self._save_feed(feed)
            raise FeedInvalid("Payload is not a GeoJSON FeatureCollection")

        is_sim = source_type == SourceType.OFFICIAL_SIMULATION.value
        rejected, new, changed, canceled, pending = [], [], [], [], []
        seen: set[str] = set()
        source_updated_ms = 0
        with self.db.tx():
            for feature in payload["features"]:
                props = (feature or {}).get("properties") or {}
                record_id = str(props.get("GlobalID") or f"{props.get('ZONE_ID')}:{props.get('OBJECTID')}")
                raw_status = props.get("STATUS")
                status = normalize_status(raw_status)
                zone_id = props.get("ZONE_ID")
                geom = geo.polygon((feature or {}).get("geometry") or {})
                if status is None:
                    rejected.append({"source_record_id": record_id, "reason": f"UNKNOWN_STATUS:{raw_status}"})
                    continue
                if not zone_id:
                    rejected.append({"source_record_id": record_id, "reason": "MISSING_ZONE_ID"})
                    continue
                if geom is None:
                    rejected.append({"source_record_id": record_id, "reason": "INVALID_GEOMETRY"})
                    continue
                seen.add(record_id)
                edit_ms = int(props.get("EDIT_DATE") or 0)
                source_updated_ms = max(source_updated_ms, int(props.get("STATEWIDE_LAST_UPDATED") or edit_ms or 0))
                existing = self._alert_by_source(source_id, record_id)

                if status == AlertStatus.INACTIVE:
                    if existing and existing.active:
                        self._cancel(existing, "EXPLICIT_INACTIVE", fetched_at, raw_status)
                        canceled.append(existing.alert_id)
                    continue

                fields = dict(status=status.value, raw_status=raw_status, version=edit_ms,
                              calamity_type=normalize_event_type(props.get("EVENT_TYPE")),
                              raw_event_type=props.get("EVENT_TYPE"), zone_id=zone_id,
                              zone_name=props.get("ZONE_NAME") or "", county=props.get("COUNTY") or "",
                              geometry=feature["geometry"], public_info=props.get("PUBLIC_INFO") or "",
                              updated_at=_ms_to_iso(edit_ms), fetched_at=fetched_at, source_url=url)
                if existing is None:
                    alert = ZoneAlert(alert_id=self.db.next_id("alert"), source_id=source_id, source_type=source_type,
                                      source_record_id=record_id, issued_at=_ms_to_iso(edit_ms),
                                      verification=Verification.OFFICIAL_SIMULATION if is_sim
                                      else Verification.OFFICIAL_LIVE_DISPLAY_ONLY,
                                      is_simulation=is_sim, **fields)
                    self._save_alert(alert)
                    new.append(alert)
                else:
                    differs = (not existing.active or existing.status != status.value
                               or existing.geometry != feature["geometry"])
                    alert = existing.model_copy(update={**fields, "active": True, "missed_polls": 0,
                                                        "canceled_at": None, "cancel_reason": None})
                    self._save_alert(alert)
                    if differs:
                        changed.append(alert)

            # Records missing from this successful ingest: cancel only after 2 misses in a row.
            for a in self._alerts({"source_id": source_id, "active": True}):
                if a.source_record_id in seen:
                    continue
                a.missed_polls += 1
                if a.missed_polls >= CANCEL_AFTER_MISSES:
                    self._cancel(a, "MISSING_FROM_FEED", fetched_at)
                    canceled.append(a.alert_id)
                else:
                    self._save_alert(a)
                    pending.append(a.alert_id)

            feed.last_success_at = fetched_at
            feed.consecutive_failures = 0
            feed.source_updated_at = _ms_to_iso(source_updated_ms) if source_updated_ms else fetched_at
            self._save_feed(feed)

        freshness = self.freshness(source_id)
        affected, checkins, outreach = [], [], []
        if is_sim:
            touched = new + changed
            affected = self._affected(touched)
            if freshness == "FRESH":  # nothing is triggered from stale data
                # All active simulated zones, not only touched ones: residents who registered after the alert
                # still get one check-in. The (alert, status, resident) record prevents repeats.
                active_sim = self._alerts({"active": True, "source_type": SourceType.OFFICIAL_SIMULATION.value})
                checkins = self._send_checkins(active_sim, correlation_id)
                outreach = self._outreach_orgs([a for a in touched if self._residents_in(a)])

        self.events.append("ALERT_FEED_INGESTED", case_id=None, correlation_id=correlation_id,
                           data={"source_id": source_id, "source_type": source_type, "new": len(new),
                                 "changed": len(changed), "canceled": len(canceled), "rejected": len(rejected),
                                 "freshness": freshness})
        result = {
            "source_id": source_id, "fetch_ok": True, "source_updated_at": feed.source_updated_at,
            "feed_freshness": freshness, "records_received": len(payload["features"]), "records_rejected": rejected,
            "new_alerts": [self._alert_brief(a) for a in new], "changed_alerts": [self._alert_brief(a) for a in changed],
            "canceled_alerts": canceled, "pending_cancellation": pending, "affected_cases": affected,
            "checkins_sent": checkins, "outreach_orgs": outreach,
            "network_agent_address": self.store.partners.agent_address("volunteer_network"),
            "notify_coordinator": bool(new or changed or canceled or checkins),
        }
        return self._finish(key, result)

    def _finish(self, key: str, result: dict[str, Any]) -> dict[str, Any]:
        result = {"ingest_id": self.db.next_id("ingest"), **result}
        self.db.coll("ingests").update_one({"_id": key}, {"$set": result}, upsert=True)
        return {**result, "duplicate": False}

    def _cancel(self, a: ZoneAlert, reason: str, at: str, raw_status: Optional[str] = None) -> None:
        a.active, a.canceled_at, a.cancel_reason = False, at, reason
        if raw_status:
            a.raw_status = raw_status
        self._save_alert(a)
        self.events.append("ALERT_CANCELED", case_id=None, data={"alert_id": a.alert_id, "reason": reason})

    @staticmethod
    def _alert_brief(a: ZoneAlert) -> dict[str, Any]:
        return {"alert_id": a.alert_id, "status": a.status, "zone_id": a.zone_id, "calamity_type": a.calamity_type}

    def _case_id_for(self, resident_id: str) -> str:
        return seed.CASE_IDS.get(resident_id, f"case_{resident_id}")

    def _affected(self, alerts: list[ZoneAlert]) -> list[dict[str, Any]]:
        out, done = [], set()
        for a in alerts:
            for p in self._residents_in(a):
                if p.resident_id in done:
                    continue
                done.add(p.resident_id)
                zone = self.zone_for(p)
                out.append({"case_id": self._case_id_for(p.resident_id), "resident_id": p.resident_id,
                            "zone_status": zone["zone_status"], "alert_id": a.alert_id})
        return out

    # -------------------------------------------------------------- check-ins
    def _send_checkins(self, alerts: list[ZoneAlert], correlation_id: str) -> list[dict[str, Any]]:
        """One DEMO check-in per (alert, status, resident). 10 identical ingests -> 1 check-in."""
        sent = []
        for a in alerts:
            if a.status not in ACTIVE_FOR_CHECKIN:
                continue
            for p in self._residents_in(a):
                if not p.wants_help_contact or not p.consents.get("CHECKIN"):
                    continue
                key = f"{a.alert_id}:{a.status}:{p.resident_id}"
                if self.db.coll("checkins").find_one({"_id": key}):
                    continue
                message_id = self._checkin(a, p, correlation_id)
                self.db.coll("checkins").insert_one({"_id": key, "alert_id": a.alert_id, "resident_id": p.resident_id,
                                                     "message_id": message_id, "at": utc_now_iso()})
                sent.append({"case_id": self._case_id_for(p.resident_id), "message_id": message_id})
        return sent

    def _checkin(self, a: ZoneAlert, profile: ResidentProfile, correlation_id: str) -> str:
        eng = self.engine
        resident = self.store.get_resident(profile.resident_id)  # v1 view until the switch-over
        case_id = self._case_id_for(profile.resident_id)
        with self.db.tx():
            case = self.store.find_case(case_id)
            if case is None:
                case = Case(case_id=case_id, resident_id=resident.resident_id, zone_id=resident.zone_id,
                            sector_id=resident.sector_id, needs=resident.needs, consent=resident.consent,
                            alert_id=a.alert_id, correlation_id=correlation_id or f"corr_{case_id}",
                            created_at=utc_now_iso())
                self.events.append("CASE_CREATED", case_id=case_id, correlation_id=case.correlation_id,
                                   data={"alert_id": a.alert_id})
            case.alert_id = a.alert_id
            self.events.append("ALERT_VERIFIED", case_id=case_id, correlation_id=case.correlation_id,
                               data={"alert_id": a.alert_id, "evidence": Verification.OFFICIAL_SIMULATION.value,
                                     "zone_status": a.status})
            msg = eng._message_resident(case, "checkin")
            eng._set_comm_status(case, C.SENT, reason="simulated check-in sent")
            case.next_step = "Awaiting resident reply. Silence is not evidence of danger or safety."
            eng._save_case(case)
        return msg.message_id

    # ------------------------------------------------------- outreach orgs
    def _max_radius_km(self) -> float:
        radii = [o.service_radius_km for o in self.store.partners.list_orgs() if o.approved]
        return max(radii) if radii else 0.0

    def select_outreach(self, alert: ZoneAlert, max_orgs: Optional[int] = None) -> list[dict[str, Any]]:
        """Plan decision 6: regions nearest the zone first; approved TRANSPORT orgs handling the calamity type
        whose region is within the org's own service radius; closest ``max_orgs`` orgs. An org's far-away
        regions (e.g. SF for an LA fire) are never included."""
        geom = geo.polygon(alert.geometry)
        if geom is None:
            return []
        best: dict[str, dict[str, Any]] = {}
        for region, km in self.store.partners.regions_near(geom, self._max_radius_km()):
            for entry in region.orgs:
                if not entry.approved or "TRANSPORT" not in entry.services or not entry.volunteers:
                    continue
                if alert.calamity_type != "UNKNOWN" and "ANY" not in entry.calamity_types \
                        and alert.calamity_type not in entry.calamity_types:
                    continue
                if km > entry.service_radius_km:
                    continue
                rec = best.setdefault(entry.org_id, {"org_id": entry.org_id, "name": entry.name, "region_ids": [],
                                                     "distance_km": km, "calamity_types": entry.calamity_types,
                                                     "alert_id": alert.alert_id})
                rec["region_ids"].append(region.region_id)
                rec["distance_km"] = min(rec["distance_km"], km)
        ranked = sorted(best.values(), key=lambda o: (o["distance_km"], o["org_id"]))
        return ranked[: max_orgs or self.outreach_max_orgs()]

    def _outreach_orgs(self, alerts: list[ZoneAlert]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for a in alerts:
            for rec in self.select_outreach(a, max_orgs=10_000):
                cur = merged.get(rec["org_id"])
                if cur is None or rec["distance_km"] < cur["distance_km"]:
                    merged[rec["org_id"]] = {**rec, "region_ids": sorted(set(rec["region_ids"] + (cur["region_ids"] if cur else [])))}
                else:
                    cur["region_ids"] = sorted(set(cur["region_ids"] + rec["region_ids"]))
        ranked = sorted(merged.values(), key=lambda o: (o["distance_km"], o["org_id"]))
        return ranked[: self.outreach_max_orgs()]

    def regions_near_view(self, *, alert_id: Optional[str] = None, zone_id: Optional[str] = None,
                          lat: Optional[float] = None, lon: Optional[float] = None,
                          radius_km: Optional[float] = None, calamity_type: Optional[str] = None,
                          service: Optional[str] = None) -> dict[str, Any]:
        origin_info: dict[str, Any] = {}
        alert = None
        if alert_id:
            alert = self.get_alert(alert_id)
        elif zone_id:
            alert = next((a for a in self._alerts({"zone_id": zone_id, "active": True})), None)
            if alert is None:
                raise NotFound(f"No active alert for zone {zone_id!r}")
        if alert is not None:
            geom = geo.polygon(alert.geometry)
            origin_info = {"alert_id": alert.alert_id, "zone_id": alert.zone_id}
            calamity_type = calamity_type or alert.calamity_type
            max_km = radius_km or self._max_radius_km()
        elif lat is not None and lon is not None:
            from shapely.geometry import Point
            geom = Point(lon, lat)
            origin_info = {"lat": lat, "lon": lon}
            max_km = radius_km or self._max_radius_km()
        else:
            raise Conflict("Provide alert_id, zone_id, or lat+lon", code="VALIDATION_ERROR")
        current_alerts = self.same_event_alert_ids(alert.alert_id) if alert is not None else set()
        regions = []
        for region, km in self.store.partners.regions_near(geom, max_km):
            orgs = []
            for e in region.orgs:
                if service and service not in e.services:
                    continue
                if calamity_type and calamity_type != "UNKNOWN" and "ANY" not in e.calamity_types \
                        and calamity_type not in e.calamity_types:
                    continue
                orgs.append({"org_id": e.org_id, "name": e.name, "approved": e.approved,
                             "calamity_types": e.calamity_types, "services": e.services,
                             "within_service_radius": km <= e.service_radius_km,
                             "volunteer_count": len(e.volunteers),
                             "approved_volunteers": sum(1 for v in e.volunteers if v.approved),
                             "available_for_alert": sum(1 for v in e.volunteers if v.availability
                                                        and v.availability.alert_id in current_alerts
                                                        and v.availability.state == "AVAILABLE"),
                             "shelter_sites": len(e.shelter_sites)})
            regions.append({"region_id": region.region_id, "label": region.label, "distance_km": km, "orgs": orgs})
        return {"origin": origin_info, "max_km": max_km, "regions": regions}

    # -------------------------------------------------------- active view
    def active_view(self) -> dict[str, Any]:
        alerts = []
        for a in self._alerts({"active": True}):
            sim = a.source_type == SourceType.OFFICIAL_SIMULATION.value
            alerts.append({**a.model_dump(exclude={"missed_polls", "canceled_at", "cancel_reason"}),
                           "freshness": self.freshness(a.source_id), "can_trigger_checkins": sim,
                           "affected_resident_count": len(self._residents_in(a)) if sim else None})
        st = self.feed.state()
        sim_geoms = [g for g in (geo.polygon(a.geometry) for a in self._alerts(
            {"active": True, "source_type": SourceType.OFFICIAL_SIMULATION.value})) if g is not None]
        awareness = []
        for inc in st.incidents:
            if not inc.active:
                continue
            nearby = [p for p in self.store.list_resident_profiles()
                      if p.address.geocode_confidence == "HIGH"
                      and geo.haversine_km(inc.lat, inc.lon, p.address.lat, p.address.lon) <= inc.radius_km
                      and not any(geo.covers(g, p.address.lat, p.address.lon) for g in sim_geoms)]
            awareness.append({"incident_id": inc.incident_id, "calamity_type": inc.calamity_type,
                              "point": {"lat": inc.lat, "lon": inc.lon}, "radius_km": inc.radius_km,
                              "label": inc.label, "residents_nearby_not_in_zone": len(nearby),
                              "note": "Awareness only; not an evacuation zone."})
        feeds = [{**_strip(d), "feed_freshness": self.freshness(d["_id"])} for d in self.db.coll("feeds").find({})]
        return {"alerts": alerts, "awareness": awareness, "feeds": feeds, "generated_at": utc_now_iso()}

    # ------------------------------------------------- volunteer outreach
    def start_outreach(self, alert_id: str, idempotency_key: Optional[str] = None, max_orgs: Optional[int] = None,
                       correlation_id: str = "") -> dict[str, Any]:
        """Volunteer Network agent: ask the nearest suitable orgs' volunteers (in the selected regions only)."""
        alert = self.get_alert(alert_id)
        if not alert.is_simulation:
            raise Conflict("Live (display-only) alerts never trigger outreach", code="NOT_SIMULATED")
        if not alert.active:
            raise Conflict("Alert is no longer active", code="ALERT_NOT_ACTIVE")
        key = idempotency_key or f"{alert_id}:outreach"
        prior = self.db.coll("provider_events").find_one({"_id": key})
        if prior:
            return {**_strip(prior).get("result", {}), "duplicate": True}

        partners = self.store.partners
        selected = self.select_outreach(alert, max_orgs)
        orgs_out = []
        with self.db.tx():
            for rec in selected:
                asked, skipped = [], []
                for region_id in rec["region_ids"]:
                    region = partners.get_region(region_id)
                    entry = next(o for o in region.orgs if o.org_id == rec["org_id"])
                    targets = [v for v in entry.volunteers if v.approved]
                    skipped += [{"volunteer_id": v.volunteer_id, "reason": "VOLUNTEER_NOT_APPROVED"}
                                for v in entry.volunteers if not v.approved]
                    ids = {v.volunteer_id for v in targets}

                    def fn(r, ids=ids, org_id=rec["org_id"]):
                        e = next(o for o in r.orgs if o.org_id == org_id)
                        for v in e.volunteers:
                            if v.volunteer_id in ids:
                                v.availability = VolunteerAvailability(alert_id=alert_id, state=AvailabilityState.ASKED)
                        return bool(ids), None
                    partners.mutate_region(region_id, fn)
                    for v in targets:
                        body = templates.render("volunteer_outreach", "en", calamity=alert.calamity_type.lower(),
                                                zone=alert.zone_name or alert.zone_id, org=entry.name)
                        msg = self.engine.sim.send(case_id=None, recipient=v.phone, body=body, language="en",
                                                   template_id="volunteer_outreach", correlation_id=correlation_id)
                        asked.append({"volunteer_id": v.volunteer_id, "message_id": msg.message_id})
                orgs_out.append({"org_id": rec["org_id"], "region_ids": rec["region_ids"],
                                 "distance_km": rec["distance_km"], "asked": asked, "skipped": skipped})
            result = {"alert_id": alert_id, "orgs": orgs_out}
            self.store.record_provider_event(key, {"type": "VOLUNTEER_OUTREACH", "alert_id": alert_id, "result": result})
            self.events.append("VOLUNTEER_OUTREACH_SENT", case_id=None, correlation_id=correlation_id,
                               data={"alert_id": alert_id, "orgs": [o["org_id"] for o in orgs_out],
                                     "asked": sum(len(o["asked"]) for o in orgs_out)})
        return {**result, "duplicate": False}

    def volunteer_by_phone(self, phone: str):
        return self.store.partners.locate_volunteer_by_phone(phone)

    def volunteer_reply(self, found, text: str, external_id: Optional[str], correlation_id: str = "") -> dict[str, Any]:
        """A volunteer answers the outreach SMS (YES/SI or NO)."""
        region, entry, volunteer = found
        if volunteer.availability is None:
            raise Conflict("This volunteer has not been asked about any alert", code="NOT_ASKED")
        intent = intake.extract(text, "en").intent.value
        if intent not in ("CONFIRM_YES", "CONFIRM_NO"):
            raise Conflict("Reply YES or NO", code="UNPARSED_REPLY")
        alert_id = volunteer.availability.alert_id
        key = f"{alert_id}:sms:{external_id}" if external_id else None
        out = self.engine.registry.record_availability(alert_id, volunteer.volunteer_id, org_id=entry.org_id,
                                                       available=intent == "CONFIRM_YES", idempotency_key=key,
                                                       correlation_id=correlation_id)
        return {**out, "region_id": region.region_id, "sender_role": "volunteer"}

    def outreach_deadline(self, alert_id: str) -> dict[str, Any]:
        """Unanswered volunteers become NO_REPLY (never treated as available)."""
        partners = self.store.partners
        marked: list[str] = []
        with self.db.tx():
            for region in partners.list_regions():
                def fn(r):
                    hit = []
                    for e in r.orgs:
                        for v in e.volunteers:
                            a = v.availability
                            if a and a.alert_id == alert_id and a.state == AvailabilityState.ASKED.value:
                                v.availability = VolunteerAvailability(alert_id=alert_id,
                                                                       state=AvailabilityState.NO_REPLY)
                                hit.append(v.volunteer_id)
                    return bool(hit), hit
                marked += partners.mutate_region(region.region_id, fn)
            self.events.append("VOLUNTEER_OUTREACH_DEADLINE", case_id=None,
                               data={"alert_id": alert_id, "no_reply": len(marked)})
        return {"alert_id": alert_id, "marked_no_reply": marked}

    def outreach_summary(self, alert_id: str) -> dict[str, Any]:
        """Live per-org counts for an alert (updates as answers arrive)."""
        alert = self.get_alert(alert_id)
        geom = geo.polygon(alert.geometry)
        orgs: dict[str, dict[str, Any]] = {}
        for region in self.store.partners.list_regions():
            from shapely.geometry import shape as _shape
            km = round(geo.geometry_distance_km(geom, _shape(region.area)), 1) if geom is not None else None
            for e in region.orgs:
                states = [v.availability.state for v in e.volunteers
                          if v.availability and v.availability.alert_id == alert_id]
                if not states:
                    continue
                rec = orgs.setdefault(e.org_id, {"org_id": e.org_id, "name": e.name, "region_ids": [],
                                                 "distance_km": km, "asked": 0, "awaiting": 0, "available": 0,
                                                 "unavailable": 0, "no_reply": 0})
                rec["region_ids"].append(region.region_id)
                if km is not None and (rec["distance_km"] is None or km < rec["distance_km"]):
                    rec["distance_km"] = km
                rec["asked"] += len(states)
                rec["awaiting"] += states.count(AvailabilityState.ASKED.value)
                rec["available"] += states.count(AvailabilityState.AVAILABLE.value)
                rec["unavailable"] += states.count(AvailabilityState.UNAVAILABLE.value)
                rec["no_reply"] += states.count(AvailabilityState.NO_REPLY.value)
        return {"alert_id": alert_id, "calamity_type": alert.calamity_type,
                "orgs": sorted(orgs.values(), key=lambda o: (o["distance_km"] is None, o["distance_km"] or 0, o["org_id"]))}

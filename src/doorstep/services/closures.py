"""Road closures (contract v2.1 §5.9). B sets the state by fixed rules; the News
agent never does. Only OFFICIAL_CONFIRMED closures on mapped segments block roads.
No report never means a road is open. REAL_WORLD_CONTEXT is display-only.

State rules over a road's ACTIVE (unexpired) claims:
* any official CLOSED/RESTRICTED            -> OFFICIAL_CONFIRMED (blocks; conflicting news is counted)
* official OPEN + news CLOSED/RESTRICTED    -> CONFLICTING (caution)
* only news: all CLOSED/RESTRICTED          -> UNVERIFIED_REPORT (caution)
* only news: disagreeing claims             -> CONFLICTING (caution)
* only news: all OPEN                       -> UNVERIFIED_REPORT (claimed OPEN; never "safe")
* nothing active, or only an official OPEN  -> EXPIRED
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from shapely.geometry import shape

from doorstep.demo import roads
from doorstep.models import utc_now_iso
from doorstep.models.closures import (
    ClaimedStatus,
    Closure,
    ClosureClaim,
    ClosureSourceType,
    ClosureState,
)

from .errors import Conflict

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

FEED_DOC = "synthetic_closures"
BLOCKING_CLAIMS = (ClaimedStatus.CLOSED.value, ClaimedStatus.RESTRICTED.value)
SEGMENT_BUFFER_DEG = 0.0003  # ~30 m either side of the fictional road line
NOTE = "No report does not mean a road is open."
STATUS_ALIASES = {"UNCLEAR": "UNKNOWN"}  # the News agent's extractor says UNCLEAR


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _expired(iso: Optional[str]) -> bool:
    if not iso:
        return False
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) <= _now()
    except ValueError:
        return True


def _strip(doc: Optional[dict]) -> dict:
    return {k: v for k, v in (doc or {}).items() if not k.startswith("_")}


def segment_area(segment_id: str):
    """Fictional road line buffered into a polygon (what HERE gets as an avoid area)."""
    return shape(roads.ROADS[segment_id]["geometry"]).buffer(SEGMENT_BUFFER_DEG)


class ClosureService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.events = engine.events

    # ------------------------------------------------- synthetic feeds (demo)
    def _feed(self) -> dict[str, Any]:
        return _strip(self.db.coll("synthetic_closure_feed").find_one({"_id": FEED_DOC})) or {"official": [], "news": []}

    def _save_feed(self, feed: dict) -> None:
        self.db.coll("synthetic_closure_feed").update_one({"_id": FEED_DOC}, {"$set": feed}, upsert=True)

    def seed_feeds(self) -> None:
        now = _now()
        self._save_feed({
            "official": [{"closure_id": "off_001", "issuing_authority": "SIMULATED_LA_COUNTY_PUBLIC_WORKS",
                          "road_name": "Ridge Ave", "segment_description": "between Zone 3 Sector B and Zone 4",
                          "status": "CLOSED", "published_at": _iso(now), "updated_at": _iso(now),
                          "expires_at": _iso(now + timedelta(hours=6))}],
            "news": [{"item_id": "news_001", "source_name": "Fictional Valley Gazette (DEMO)", "url": None,
                      "published_at": _iso(now), "headline": "Residents report Canyon Rd blocked by debris (DEMO)",
                      "body": "Several residents say Canyon Rd near Zone 3 is blocked by fallen debris. "
                              "Officials have not confirmed. SIMULATION."}],
        })

    def feed_official(self) -> dict[str, Any]:
        return {"closures": self._feed()["official"], "simulated": True}

    def feed_news(self) -> dict[str, Any]:
        return {"items": self._feed()["news"], "simulated": True}

    def trigger(self, action: str, *, road_name: str, status: str = "CLOSED", headline: Optional[str] = None,
                body: Optional[str] = None, expires_in_minutes: int = 360) -> dict[str, Any]:
        feed = self._feed()
        now = _now()
        action = action.upper()
        if action == "PUBLISH_OFFICIAL":
            n = len(feed["official"]) + 1
            feed["official"] = [c for c in feed["official"] if c["road_name"].lower() != road_name.lower()] + [{
                "closure_id": f"off_{n:03d}", "issuing_authority": "SIMULATED_LA_COUNTY_PUBLIC_WORKS",
                "road_name": road_name, "segment_description": "", "status": status.upper(),
                "published_at": _iso(now), "updated_at": _iso(now),
                "expires_at": _iso(now + timedelta(minutes=expires_in_minutes))}]
        elif action == "LIFT_OFFICIAL":
            for c in feed["official"]:
                if c["road_name"].lower() == road_name.lower():
                    c["status"], c["updated_at"] = "OPEN", _iso(now)
        elif action == "PUBLISH_NEWS":
            n = len(feed["news"]) + 1
            feed["news"].append({"item_id": f"news_{n:03d}", "source_name": "Fictional Valley Gazette (DEMO)",
                                 "url": None, "published_at": _iso(now),
                                 "headline": headline or f"Report about {road_name} (DEMO)",
                                 "body": body or f"Residents report {road_name} is closed. SIMULATION."})
        else:
            raise Conflict(f"Unknown action {action!r}", code="VALIDATION_ERROR")
        self._save_feed(feed)
        return {"action": action, "road_name": road_name, "official": len(feed["official"]), "news": len(feed["news"])}

    # ------------------------------------------------------------- storage
    def _closures(self, query: Optional[dict] = None) -> list[Closure]:
        return [Closure.model_validate(_strip(d)) for d in self.db.coll("closures").find(query or {}).sort("_ord", 1)]

    def _save(self, c: Closure) -> None:
        self.db.coll("closures").update_one({"_id": c.closure_id}, {"$set": c.model_dump(mode="json"),
                                                                    "$setOnInsert": {"_ord": self.db.next_ord()}},
                                            upsert=True)

    def _find(self, road_name: str, segment_id: Optional[str], display_only: bool) -> Optional[Closure]:
        query: dict[str, Any] = {"display_only": display_only}
        if segment_id:
            query["segment_id"] = segment_id
        else:
            query.update({"segment_id": None, "road_name": road_name})
        d = self.db.coll("closures").find_one(query)
        return Closure.model_validate(_strip(d)) if d else None

    # --------------------------------------------------------------- state
    @staticmethod
    def compute_state(claims: list[ClosureClaim]) -> tuple[str, str, int]:
        """(state, claimed_status, conflicting_reports) from a road's claims."""
        active = [c for c in claims if not _expired(c.expires_at)]
        official = [c for c in active if c.source_type == ClosureSourceType.OFFICIAL_SIMULATION.value]
        reports = [c for c in active if c.source_type != ClosureSourceType.OFFICIAL_SIMULATION.value]
        latest_official = max(official, key=lambda c: c.updated_at or c.published_at or "", default=None)
        report_closed = [c for c in reports if c.claimed_status in BLOCKING_CLAIMS]
        report_open = [c for c in reports if c.claimed_status == ClaimedStatus.OPEN.value]
        if latest_official and latest_official.claimed_status in BLOCKING_CLAIMS:
            return ClosureState.OFFICIAL_CONFIRMED.value, latest_official.claimed_status, len(report_open)
        if latest_official and latest_official.claimed_status == ClaimedStatus.OPEN.value:
            if report_closed:
                return ClosureState.CONFLICTING.value, ClaimedStatus.UNKNOWN.value, len(report_closed)
            return ClosureState.EXPIRED.value, ClaimedStatus.OPEN.value, 0
        if report_closed and report_open:
            return ClosureState.CONFLICTING.value, ClaimedStatus.UNKNOWN.value, len(report_open)
        if report_closed:
            return ClosureState.UNVERIFIED_REPORT.value, report_closed[-1].claimed_status, 0
        if report_open:
            return ClosureState.UNVERIFIED_REPORT.value, ClaimedStatus.OPEN.value, 0
        return ClosureState.EXPIRED.value, ClaimedStatus.UNKNOWN.value, 0

    def _refresh(self, c: Closure) -> Closure:
        state, claimed, conflicts = self.compute_state(c.claims)
        expiries = [cl.expires_at for cl in c.claims if cl.expires_at and not _expired(cl.expires_at)]
        return c.model_copy(update={
            "state": state, "claimed_status": claimed, "conflicting_reports": conflicts,
            "used_for_routing": state == ClosureState.OFFICIAL_CONFIRMED.value and bool(c.segment_id)
            and not c.display_only,
            "expires_at": max(expiries) if expiries else None})

    # -------------------------------------------------------------- ingest
    def ingest(self, *, source_id: str, source_type: str, url: Optional[str], fetched_at: Optional[str],
               items: list[dict[str, Any]], idempotency_key: Optional[str],
               correlation_id: str = "") -> dict[str, Any]:
        source_type = ClosureSourceType(source_type).value
        key = idempotency_key or f"closures:{source_id}:{fetched_at or utc_now_iso()}"
        prior = self.db.coll("ingests").find_one({"_id": key})
        if prior:
            return {**_strip(prior), "duplicate": True}
        display_only = source_type == ClosureSourceType.REAL_WORLD_CONTEXT.value
        accepted, rejected, new_official = [], [], []
        changed = False
        with self.db.tx():
            for item in items:
                cand = item.get("candidate") or {}
                road_name = (cand.get("road_name") or "").strip()
                item_id = str(item.get("source_item_id") or "")
                if not road_name:
                    rejected.append({"source_item_id": item_id, "reason": "MISSING_ROAD"})
                    continue
                raw_status = (cand.get("claimed_status") or "UNKNOWN").strip().upper()
                raw_status = STATUS_ALIASES.get(raw_status, raw_status)
                try:
                    claimed = ClaimedStatus(raw_status).value
                except ValueError:
                    rejected.append({"source_item_id": item_id, "reason": f"UNKNOWN_STATUS:{cand.get('claimed_status')}"})
                    continue
                segment_id = None if display_only else roads.resolve(road_name)
                claim = ClosureClaim(source_id=source_id, source_type=source_type, source_item_id=item_id,
                                     claimed_status=claimed, road_name=road_name,
                                     location_text=cand.get("location_text") or "",
                                     published_at=item.get("published_at"), updated_at=item.get("updated_at"),
                                     expires_at=item.get("expires_at"), url=item.get("url") or url,
                                     headline=item.get("headline") or "", raw_text=(item.get("raw_text") or "")[:2000],
                                     extraction_method=item.get("extraction_method") or "STRUCTURED_FEED",
                                     received_at=utc_now_iso())
                existing = self._find(road_name, segment_id, display_only)
                before = existing.state if existing else None
                if existing is None:
                    existing = Closure(closure_id=self.db.next_id("closure"),
                                       road_name=roads.ROADS[segment_id]["name"] if segment_id else road_name,
                                       segment_id=segment_id, display_only=display_only,
                                       state=ClosureState.EXPIRED, claimed_status=ClaimedStatus.UNKNOWN,
                                       first_seen_at=utc_now_iso())
                claims = [c for c in existing.claims
                          if not (c.source_id == source_id and c.source_item_id == item_id)] + [claim]
                updated = self._refresh(existing.model_copy(update={"claims": claims, "updated_at": utc_now_iso()}))
                self._save(updated)
                changed = changed or updated.state != before
                if updated.state == ClosureState.OFFICIAL_CONFIRMED.value and before != updated.state:
                    new_official.append(updated.closure_id)
                accepted.append({"closure_id": updated.closure_id, "road_name": updated.road_name,
                                 "claimed_status": claimed, "state": updated.state,
                                 "segment_id": updated.segment_id, "display_only": display_only})
            self.events.append("CLOSURES_INGESTED", case_id=None, correlation_id=correlation_id,
                               data={"source_id": source_id, "source_type": source_type, "accepted": len(accepted),
                                     "rejected": len(rejected), "new_official": new_official})
        result = {"ingest_id": self.db.next_id("cl_ingest"), "accepted": accepted, "rejected": rejected,
                  "new_official_closures": new_official, "notify_coordinator": changed, "correlation_id": correlation_id}
        self.db.coll("ingests").update_one({"_id": key}, {"$set": result}, upsert=True)
        return {**result, "duplicate": False}

    # ---------------------------------------------------------------- views
    def current(self) -> list[Closure]:
        """All closures with state recomputed now (claims can expire between ingests)."""
        return [self._refresh(c) for c in self._closures()]

    def list_view(self) -> dict[str, Any]:
        out = []
        for c in self.current():
            out.append({"closure_id": c.closure_id, "road_name": c.road_name, "segment_id": c.segment_id,
                        "state": c.state, "claimed_status": c.claimed_status, "used_for_routing": c.used_for_routing,
                        "display_only": c.display_only, "conflicting_reports": c.conflicting_reports,
                        "sources": [{"source_id": cl.source_id, "source_type": cl.source_type, "url": cl.url,
                                     "published_at": cl.published_at, "headline": cl.headline,
                                     "claimed_status": cl.claimed_status, "extraction_method": cl.extraction_method}
                                    for cl in c.claims],
                        "first_seen_at": c.first_seen_at, "updated_at": c.updated_at, "expires_at": c.expires_at})
        return {"closures": out, "note": NOTE, "simulated": True}

    def blocking(self) -> list[Closure]:
        return [c for c in self.current() if c.used_for_routing]

    def cautions(self) -> list[Closure]:
        return [c for c in self.current() if not c.display_only and c.segment_id
                and c.state in (ClosureState.UNVERIFIED_REPORT.value, ClosureState.CONFLICTING.value)]

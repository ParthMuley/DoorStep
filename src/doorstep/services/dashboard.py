"""Card data for ASI:One Interactive Cards (contract v2.1 §5.11). Read-only views
built only from persisted state; coordinates are coarse, never pickup points."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from doorstep.models import ResidentStatus, map_color, utc_now_iso

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

STATUS_ORDER = [s.value for s in (ResidentStatus.NEEDS_ASSISTANCE, ResidentStatus.PROVIDER_ACCEPTED,
                                  ResidentStatus.PICKUP_CONFIRMED, ResidentStatus.ARRIVAL_CONFIRMED,
                                  ResidentStatus.REQUIRES_COORDINATOR, ResidentStatus.UNKNOWN)]
STEP_FOR_STATUS = {"NEEDS_ASSISTANCE": "REQUESTED", "PROVIDER_ACCEPTED": "PROVIDER_ACCEPTED",
                   "PICKUP_CONFIRMED": "PICKUP_CONFIRMED", "ARRIVAL_CONFIRMED": "ARRIVAL_CONFIRMED"}
STEPS = ["REQUESTED", "PROVIDER_ACCEPTED", "PICKUP_CONFIRMED", "ARRIVAL_CONFIRMED"]


class DashboardService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.store = engine.store

    # ------------------------------------------------------- progress steps
    def progress_steps(self, case_id: str) -> list[dict[str, Any]]:
        """Requested → Volunteer accepted → Pickup → Arrival.
        A step is done only if (1) a timeline event recorded it, (2) the case's CURRENT status is at or past it
        (a canceled volunteer un-does "accepted"), and (3) every earlier step is done. Green is never early."""
        reached: dict[str, str] = {}
        for e in self.engine.events.for_case(case_id):
            if e.event_type == "RESIDENT_STATUS_CHANGED" and e.to_status in STEP_FOR_STATUS:
                reached[STEP_FOR_STATUS[e.to_status]] = e.created_at
        case = self.store.get_case(case_id)
        if case.resident_status in STEP_FOR_STATUS:
            current = STEPS.index(STEP_FOR_STATUS[case.resident_status])
        else:  # UNKNOWN / REQUIRES_COORDINATOR: at most "requested" (if it ever was)
            current = 0
        verifs = {v.kind: v.verification_id for v in self.store.verifications_for_case(case_id)}
        out, previous_done = [], True
        for i, step in enumerate(STEPS):
            done = previous_done and step in reached and i <= current
            item = {"step": step, "done": done, "at": reached[step] if done else None}
            if done and step == "PICKUP_CONFIRMED":
                item["evidence_ref"] = verifs.get("pickup")
            if done and step == "ARRIVAL_CONFIRMED":
                item["evidence_ref"] = verifs.get("arrival")
            out.append(item)
            previous_done = done
        return out

    # -------------------------------------------------------------- summary
    def summary(self) -> dict[str, Any]:
        eng = self.engine
        cases = self.store.list_cases()
        counts = {s: 0 for s in STATUS_ORDER}
        unresolved = []
        for c in cases:
            counts[c.resident_status] = counts.get(c.resident_status, 0) + 1
            view = eng.get_case_status(c.case_id)
            if view["unresolved"]:
                escalations = self.store.escalations_for_case(c.case_id)
                reason = escalations[-1].reason if escalations else c.resident_status
                unresolved.append({"case_id": c.case_id, "display_name": view["display_name"], "reason": reason,
                                   "zone_status": view["zone_status"], "next_step": c.next_step})
        alerts = eng.alerts._alerts({"active": True, "source_type": "OFFICIAL_SIMULATION"})
        feeds = list(eng.db.coll("feeds").find({}))
        outreach = {"orgs_contacted": 0, "volunteers_asked": 0, "volunteers_available": 0,
                    "volunteers_awaiting": 0, "volunteers_no_reply": 0}
        seen_orgs: set[str] = set()
        for a in alerts:
            for o in eng.alerts.outreach_summary(a.alert_id)["orgs"]:
                seen_orgs.add(o["org_id"])
                outreach["volunteers_asked"] += o["asked"]
                outreach["volunteers_available"] += o["available"]
                outreach["volunteers_awaiting"] += o["awaiting"]
                outreach["volunteers_no_reply"] += o["no_reply"]
        outreach["orgs_contacted"] = len(seen_orgs)
        closures = eng.closures.current()
        routed = [c for c in closures if not c.display_only]
        referrals = [r for r in self.store.referrals_for_case_all() if r.help_type]
        return {
            "generated_at": utc_now_iso(), "simulated": True,
            "counts_by_status": [{"status": s, "count": counts[s], "color": map_color(s)[0], "label": map_color(s)[1]}
                                 for s in STATUS_ORDER],
            "unresolved": unresolved,
            "alerts": {"active_order": sum(1 for a in alerts if a.status == "ORDER"),
                       "active_warning": sum(1 for a in alerts if a.status == "WARNING"),
                       "active_shelter_in_place": sum(1 for a in alerts if a.status == "SHELTER_IN_PLACE"),
                       "feed_freshness": eng.alerts.simulated_freshness(),
                       "last_ingest_at": max((f.get("last_ingest_at") or "" for f in feeds), default=None) or None},
            "outreach": outreach,
            "closures": {"official_confirmed": sum(1 for c in routed if c.state == "OFFICIAL_CONFIRMED"),
                         "unverified": sum(1 for c in routed if c.state == "UNVERIFIED_REPORT"),
                         "conflicting": sum(1 for c in routed if c.state == "CONFLICTING"),
                         "display_only": sum(1 for c in closures if c.display_only)},
            "recovery": {"requested": sum(1 for r in referrals if r.status == "REQUESTED"),
                         "accepted": sum(1 for r in referrals if r.status == "ACCEPTED"),
                         "completed": sum(1 for r in referrals if r.status == "COMPLETED"),
                         "unresolved": sum(1 for r in referrals if r.status == "UNRESOLVED")},
        }

    def cases(self) -> dict[str, Any]:
        out = []
        for c in self.store.list_cases():
            view = self.engine.get_case_status(c.case_id)
            profile = self.store.find_resident_profile(c.resident_id)
            coarse = ({"lat": round(profile.address.lat, 2), "lon": round(profile.address.lon, 2)}
                      if profile and profile.address.geocode_confidence == "HIGH" else None)
            out.append({"case_id": c.case_id, "display_name": view["display_name"], "zone_status": view["zone_status"],
                        "resident_status": c.resident_status, "map": view["map"], "coarse_location": coarse,
                        "unresolved": view["unresolved"], "progress_steps": view["progress_steps"],
                        "updated_at": c.updated_at})
        return {"cases": out, "simulated": True, "note": "Coarse synthetic locations only."}

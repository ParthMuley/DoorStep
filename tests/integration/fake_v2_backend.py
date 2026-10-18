"""Contract-shaped TEST DOUBLE for v2.0/v2.1 (team plan rev 3) endpoints Developer B
hasn't built yet.

It is B's real app (real orgs, volunteers, registry, auth) with stand-in routes
inserted *in front* for the missing paths. Rev 3: no per-org agents; outreach and
availability are alert-scoped and done by the Volunteer Network agent; nearby help is
found by location (regions). Shapes follow
docs/interface-contract.md v2.0 §5 and the §10 seed IDs. Delete each stand-in as B's
real route lands; tests that use it must keep passing against B's code.
Never used outside tests.
"""

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from doorstep.api.app import create_app
from doorstep.api.security import expected_token
from doorstep.workflows.backend_v2 import DoorstepBackendV2

TOKEN = "change-me-local-demo-token"
V2 = "2.0"

ZONES = {  # zone_id -> (raw Cal OES status, affected case)
    "zone_3_sector_b": ("Evacuation Warning", "case_maria_001", "resident_001"),
    "zone_3_sector_a": ("Evacuation Order", "case_david_002", "resident_002"),
}
STATUS_MAP = {"evacuation order": "ORDER", "evacuation warning": "WARNING", "shelter in place": "SHELTER_IN_PLACE",
              "normal": "INACTIVE", "clear to repopulate": "INACTIVE"}
# Rev 3 location-first stand-in: regions near Zone 3 (nearest first) -> orgs active there.
REGIONS = [("la_county:zone_3", 0.9, [("neighbor_sedans_demo", "Neighbor Sedans (fictional)")]),
           ("la_county:zone_2", 4.1, [("eastside_rides_demo", "Eastside Accessible Rides (fictional)")]),
           ("la_county:zone_4", 7.9, [("red_cross_demo", "Red Cross (fictional demo chapter)")])]
OUTREACH_ORGS = [(o, n, d, r) for r, d, orgs in REGIONS for o, n in orgs]
MARIA_CANDIDATES = [("eastside_rides_demo", "volunteer_sarah", "WHEELCHAIR_VAN", 4.0),
                    ("red_cross_demo", "volunteer_lee", "WHEELCHAIR_VAN", 7.5)]
RECOVERY_ORGS = {"TEMPORARY_HOUSING": "recovery_housing_demo", "INSURANCE_GUIDANCE": "red_cross_demo"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(status: int, code: str, detail: str, reasons: list[str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"schema_version": V2, "error": code, "detail": detail,
                                                     "reasons": reasons or [], "correlation_id": None})


def _feature(zone_id: str, status: str, edit_ms: int, oid: int) -> dict[str, Any]:
    return {"type": "Feature", "id": oid,
            "geometry": {"type": "Polygon", "coordinates": [[[-118.1, 34.1], [-118.09, 34.1], [-118.09, 34.11],
                                                             [-118.1, 34.11], [-118.1, 34.1]]]},
            "properties": {"OBJECTID": oid, "COUNTY": "Los Angeles (SIMULATED)", "ZONE_ID": zone_id,
                           "ZONE_NAME": f"DEMO {zone_id}", "STATUS": status, "EVENT_TYPE": "Wildfire (SIMULATED)",
                           "EDIT_DATE": edit_ms, "STATEWIDE_LAST_UPDATED": edit_ms, "GlobalID": f"sim-{oid:04d}"}}


def build_v2_router(state: dict[str, Any]) -> APIRouter:
    r = APIRouter()

    def authed(authorization: str | None) -> bool:
        return authorization == f"Bearer {expected_token()}"  # same rule as B's real routes

    # ---------------------------------------------------------------- alerts
    @r.get("/demo/feeds/caloes")
    def feed():
        return {"type": "FeatureCollection", "features": state["features"]}

    @r.post("/demo/alerts/trigger")
    async def trigger(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        state["edit"] += 60_000
        if body["action"] == "ISSUE":
            state["features"] = [_feature(z, s, state["edit"], i + 1) for i, (z, (s, _, _)) in enumerate(ZONES.items())]
        elif body["action"] == "CANCEL":
            state["features"] = []
        return {"schema_version": V2, "action": body["action"], "features": len(state["features"])}

    @r.post("/alerts/ingest")
    async def ingest(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        state["ingests"] += 1
        ingest_id = f"ingest_{state['ingests']:03d}"
        if not body.get("fetch_ok"):
            return {"schema_version": V2, "ingest_id": ingest_id, "feed_freshness": "UNKNOWN", "new_alerts": [],
                    "changed_alerts": [], "canceled_alerts": [], "affected_cases": [], "checkins_sent": [],
                    "outreach_orgs": [], "records_rejected": [], "notify_coordinator": False, "duplicate": False}
        new_alerts, affected, rejected = [], [], []
        for f in body["payload"]["features"]:
            p = f["properties"]
            status = STATUS_MAP.get(str(p["STATUS"]).lower())
            if status is None:
                rejected.append({"source_record_id": p["GlobalID"], "reason": f"UNKNOWN_STATUS:{p['STATUS']}"})
                continue
            key = (p["GlobalID"], p["EDIT_DATE"])
            if key in state["seen"]:
                continue
            state["seen"].add(key)
            state["alert_seq"] += 1
            alert_id = f"alert_{state['alert_seq']:03d}"
            new_alerts.append({"alert_id": alert_id, "status": status, "zone_id": p["ZONE_ID"],
                               "calamity_type": "WILDFIRE"})
            _, case_id, resident_id = ZONES[p["ZONE_ID"]]
            affected.append({"case_id": case_id, "resident_id": resident_id, "zone_status": status,
                             "alert_id": alert_id})
        simulated = body["source"]["source_type"] == "OFFICIAL_SIMULATION"
        if simulated and new_alerts and not state["cases_created"]:
            # Stand-in for B's geofencing: create the real cases + simulated check-ins in B's DB.
            state["service"].start_demo_warning("zone_3", "la_hacks_demo_v1", "SIMULATED_OFFICIAL",
                                                body.get("correlation_id"))
            state["cases_created"] = True
        warning = next((a for a in new_alerts if a["status"] == "WARNING"), None)
        if warning:
            state["warning_alert_id"] = warning["alert_id"]
        outreach = [{"org_id": o, "name": n, "region_id": r, "distance_km": d,
                     "calamity_types": ["WILDFIRE"], "alert_id": warning["alert_id"]}
                    for o, n, d, r in OUTREACH_ORGS] if (simulated and warning) else []
        return {"schema_version": V2, "ingest_id": ingest_id, "source_id": body["source"]["source_id"],
                "feed_freshness": "FRESH", "records_received": len(body["payload"]["features"]),
                "records_rejected": rejected, "new_alerts": new_alerts, "changed_alerts": [],
                "canceled_alerts": [], "pending_cancellation": [], "affected_cases": affected,
                "checkins_sent": [{"case_id": a["case_id"], "message_id": f"msg_{i}"} for i, a in enumerate(affected)]
                if simulated else [], "outreach_orgs": outreach, "notify_coordinator": bool(new_alerts) and simulated,
                "duplicate": not new_alerts}

    # ------------------------------------------------- outreach (rev 3, alert-scoped)
    def org_volunteers(org_id: str) -> list[dict[str, Any]]:
        return state["service"].registry.org_volunteers(org_id, None)["volunteers"]

    @r.get("/regions/near")
    def regions_near(zone_id: str | None = None):
        return {"schema_version": V2, "zone_id": zone_id, "regions": [
            {"region_id": rid, "distance_km": d, "orgs": [{"org_id": o, "name": n,
                                                          "volunteers": len(org_volunteers(o))} for o, n in orgs]}
            for rid, d, orgs in REGIONS]}

    @r.post("/alerts/{alert_id}/outreach")
    async def outreach(alert_id: str, request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        if body["idempotency_key"] in state["outreach_keys"]:
            return {**state["outreach_keys"][body["idempotency_key"]], "duplicate": True}
        orgs = []
        for org_id, name, dist, region_id in OUTREACH_ORGS:
            vols = org_volunteers(org_id)
            asked = [v["volunteer_id"] for v in vols if v["approved"]]
            for vid in asked:
                state["availability"][(alert_id, vid)] = ("ASKED", org_id)
            orgs.append({"org_id": org_id, "name": name, "region_id": region_id, "distance_km": dist,
                         "asked": [{"volunteer_id": v, "message_id": f"msg_{v}"} for v in asked],
                         "skipped": [{"volunteer_id": v["volunteer_id"], "reason": "VOLUNTEER_NOT_APPROVED"}
                                     for v in vols if not v["approved"]]})
        result = {"schema_version": V2, "alert_id": alert_id, "orgs": orgs, "duplicate": False}
        state["outreach_keys"][body["idempotency_key"]] = result
        return result

    @r.post("/alerts/{alert_id}/volunteers/{volunteer_id}/availability")
    async def availability(alert_id: str, volunteer_id: str, request: Request,
                           authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        current = state["availability"].get((alert_id, volunteer_id))
        if current is None:
            return _err(409, "STALE_AVAILABILITY", "volunteer was not asked for this alert")
        if current[1] != body["org_id"]:
            return _err(403, "UNAUTHORIZED", "volunteer does not belong to this org")
        status = "AVAILABLE" if body["available"] else "UNAVAILABLE"
        state["availability"][(alert_id, volunteer_id)] = (status, body["org_id"])
        return {"schema_version": V2, "volunteer_id": volunteer_id, "alert_id": alert_id, "availability": status}

    @r.get("/alerts/{alert_id}/outreach")
    def outreach_status(alert_id: str):
        orgs = []
        for org_id, name, dist, _ in OUTREACH_ORGS:
            states = [st for (aid, _vid), (st, o) in state["availability"].items() if aid == alert_id and o == org_id]
            orgs.append({"org_id": org_id, "name": name, "distance_km": dist, "asked": len(states),
                         "available": states.count("AVAILABLE"), "unavailable": states.count("UNAVAILABLE"),
                         "no_reply": states.count("ASKED")})
        return {"schema_version": V2, "alert_id": alert_id, "orgs": orgs}

    # --------------------------------------------------------------- matching
    def available(org_id: str, volunteer_id: str) -> bool:
        st = state["availability"].get((state.get("warning_alert_id"), volunteer_id))
        return bool(st) and st == ("AVAILABLE", org_id)

    @r.post("/matches/propose")
    async def propose(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        case_id = body["case_id"]
        if body["idempotency_key"] in state["proposals"]:
            return {**state["proposals"][body["idempotency_key"]], "duplicate": True}
        if case_id == "case_david_002":
            return {"schema_version": V2, "case_id": case_id, "zone_status": "ORDER",
                    "evaluation": {"volunteers": {"eligible": [], "rejected": []},
                                   "shelters": {"eligible": [], "rejected": []}},
                    "escalation_required": True, "no_match_reason": "ORDER_ZONE", "match": None, "duplicate": False}
        declined = state["declined"].setdefault(case_id, set())
        eligible, rejected = [], [{"org_id": "neighbor_sedans_demo", "volunteer_id": "volunteer_joe",
                                   "vehicle_type": "SEDAN", "distance_km": 0.8,
                                   "reason_codes": ["NEEDS_NOT_COVERED", "NO_WHEELCHAIR_SPACE"], "missing_needs": [1, 2]}]
        for org_id, vid, vehicle, dist in MARIA_CANDIDATES:
            if vid in declined:
                rejected.append({"org_id": org_id, "volunteer_id": vid, "reason_codes": ["DECLINED_THIS_CASE"]})
            elif not available(org_id, vid):
                rejected.append({"org_id": org_id, "volunteer_id": vid, "reason_codes": ["NOT_AVAILABLE_FOR_THIS_ALERT"]})
            else:
                eligible.append({"org_id": org_id, "volunteer_id": vid, "vehicle_type": vehicle, "distance_km": dist,
                                 "rank": len(eligible) + 1, "reason_codes": ["NEEDS_COVERED", "WHEELCHAIR_OK",
                                                                             "TRANSFER_OK", "PET_OK"]})
        shelter = {"org_id": "civic_shelter_demo", "site_id": "dest_center_a", "distance_km": 6.2, "rank": 1,
                   "reason_codes": ["ORG_APPROVED", "STEP_FREE_OK", "PET_OK", "BEDS_OK"]}
        select = body.get("select") or {}
        if select.get("volunteer_id"):
            eligible = [e for e in eligible if e["volunteer_id"] == select["volunteer_id"]]
            if not eligible:
                return _err(409, "NOT_ELIGIBLE", "selected volunteer is not eligible")
        match = None
        if body["create_proposal"] and eligible:
            top = eligible[0]
            state["assign_seq"] += 1
            aid = f"assign_{state['assign_seq']:03d}"
            state["assignments"][aid] = {"case_id": case_id, "org_id": top["org_id"], "volunteer_id": top["volunteer_id"],
                                         "status": "PROPOSED", "shelter_accepted": False, "pickup": False}
            match = {"assignment_id": aid, "status": "PROPOSED", "reserved": True, "org_id": top["org_id"],
                     "volunteer_id": top["volunteer_id"], "vehicle_type": top["vehicle_type"],
                     "shelter_org_id": "civic_shelter_demo", "site_id": "dest_center_a",
                     "reason_codes": top["reason_codes"], "authorization": "SIMULATED_PREAPPROVED",
                     "route_status": "ILLUSTRATIVE_ONLY",
                     "shared_with_volunteer": {"needs": [1, 2, 4], "pet_count": 1, "language": "es",
                                               "pickup_area": "zone_3_sector_b (synthetic)"},
                     "eta_estimate": {"minutes": 18, "label": "Illustrative estimate, not a guarantee"},
                     "idempotency_key": body["idempotency_key"]}
        result = {"schema_version": V2, "case_id": case_id, "alert_id": state.get("warning_alert_id"),
                  "zone_status": "WARNING",
                  "evaluation": {"volunteers": {"eligible": eligible, "rejected": rejected},
                                 "shelters": {"eligible": [shelter], "rejected": []}},
                  "escalation_required": not eligible, "no_match_reason": None if eligible else "NO_AVAILABLE_VOLUNTEER",
                  "match": match, "duplicate": False}
        if match:
            state["proposals"][body["idempotency_key"]] = result
        return JSONResponse(status_code=201 if match else 200, content=result)

    @r.post("/assignments/{assignment_id}/accept")
    async def accept(assignment_id: str, request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        a = state["assignments"].get(assignment_id)
        if a is None:
            return _err(404, "NOT_FOUND", "assignment")
        if body.get("site_id"):  # shelter confirms the bed
            if body["org_id"] != "civic_shelter_demo":
                return _err(403, "UNAUTHORIZED", "wrong shelter org")
            a["shelter_accepted"] = body["decision"] == "ACCEPTED"
            return {"schema_version": V2, "assignment_id": assignment_id, "case_id": a["case_id"], "responding": "shelter",
                    "org_id": body["org_id"], "site_id": body["site_id"], "decision": body["decision"],
                    "assignment_status": a["status"], "resident_status": "PROVIDER_ACCEPTED"
                    if a["status"] == "ACCEPTED" else "NEEDS_ASSISTANCE", "duplicate": False}
        if (body["org_id"], body.get("volunteer_id")) != (a["org_id"], a["volunteer_id"]):
            return _err(403, "UNAUTHORIZED", "wrong org or volunteer for this assignment")
        if a["status"] in ("DECLINED", "CANCELED"):
            return _err(409, "INVALID_TRANSITION", "assignment no longer active")
        if body["decision"] == "DECLINED":
            a["status"] = "DECLINED"
            state["declined"].setdefault(a["case_id"], set()).add(a["volunteer_id"])
            nxt = next(({"org_id": o, "volunteer_id": v} for o, v, _, _ in MARIA_CANDIDATES
                        if v not in state["declined"][a["case_id"]]), None)
            return {"schema_version": V2, "assignment_id": assignment_id, "case_id": a["case_id"], "responding": "volunteer",
                    "org_id": a["org_id"], "volunteer_id": a["volunteer_id"], "decision": "DECLINED",
                    "assignment_status": "DECLINED", "resident_status": "NEEDS_ASSISTANCE",
                    "next_alternate": nxt, "duplicate": False}
        a["status"] = "ACCEPTED"
        return {"schema_version": V2, "assignment_id": assignment_id, "case_id": a["case_id"], "responding": "volunteer",
                "org_id": a["org_id"], "volunteer_id": a["volunteer_id"], "decision": "ACCEPTED",
                "assignment_status": "ACCEPTED", "resident_status": "PROVIDER_ACCEPTED",
                "pickup_details": {"pickup_point": "SYNTHETIC: Zone 3 Sector B meeting point 4",
                                   "resident_phone": "sim_phone_maria"},
                "help_on_the_way_sent": True, "eta": {"minutes": 18, "label": "Illustrative estimate, not a guarantee"},
                "next_alternate": None, "next_step": "Shelter confirmation and route preview pending.", "duplicate": False}

    @r.post("/assignments/{assignment_id}/pickup")
    async def pickup(assignment_id: str, request: Request):
        body = await request.json()
        a = state["assignments"].get(assignment_id)
        ev = body["evidence"]
        if not a or a["status"] != "ACCEPTED":
            return _err(409, "INVALID_TRANSITION", "pickup before acceptance")
        if not (ev.get("volunteer_confirmed") and (ev.get("resident_confirmed") or ev.get("caregiver_confirmed"))):
            return _err(409, "INSUFFICIENT_EVIDENCE", "volunteer and resident confirmation required")
        a["pickup"] = True
        return {"schema_version": V2, "assignment_id": assignment_id, "case_id": a["case_id"], "assignment_status": "ACCEPTED",
                "resident_status": "PICKUP_CONFIRMED", "confirmed_pickup_at": _now(), "confirmed_arrival_at": None,
                "map": {"color": "blue", "label": "Pickup confirmed (not yet arrived)"}, "duplicate": False}

    @r.post("/assignments/{assignment_id}/arrival")
    async def arrival(assignment_id: str, request: Request):
        a = state["assignments"].get(assignment_id)
        if not a or not a["pickup"] or not a["shelter_accepted"]:
            return _err(409, "INVALID_TRANSITION", "arrival needs pickup and an accepted shelter")
        a["status"] = "COMPLETED"
        return {"schema_version": V2, "assignment_id": assignment_id, "case_id": a["case_id"], "assignment_status": "COMPLETED",
                "resident_status": "ARRIVAL_CONFIRMED", "confirmed_arrival_at": _now(),
                "map": {"color": "green", "label": "Arrival confirmed"}, "duplicate": False}

    # ------------------------------------------------------------- escalation
    @r.post("/cases/{case_id}/escalate")
    async def escalate(case_id: str, request: Request):
        body = await request.json()
        if body["reason"] == "ACTIVE_EVACUATION_ORDER_ZONE" and case_id != "case_david_002":
            return _err(409, "INVALID_TRANSITION", "case is not inside an order zone")
        state["esc_seq"] += 1
        esc_id = f"esc_{state['esc_seq']:03d}"
        state["escalations"][esc_id] = case_id
        return JSONResponse(status_code=201, content={
            "schema_version": V2, "escalation_id": esc_id, "case_id": case_id, "reason": body["reason"],
            "recipient": "SIMULATED_AUTHORIZED_RESPONSE_SERVICE", "status": "REQUESTED", "assistance_confirmed": False,
            "case_summary_for_recipient": {"case_id": case_id, "zone_id": "zone_3_sector_a", "zone_status": "ORDER",
                                           "language": "en", "needs": [1]},
            "resident_status": "REQUIRES_COORDINATOR", "assignment_status": "UNRESOLVED",
            "next_step": "Awaiting simulated authorized service acknowledgment; assistance not confirmed."})

    @r.post("/escalations/{escalation_id}/ack")
    async def ack(escalation_id: str):
        case_id = state["escalations"][escalation_id]
        return {"schema_version": V2, "escalation_id": escalation_id, "case_id": case_id,
                "status": "ACKNOWLEDGED_REQUEST_ONLY", "assistance_confirmed": False,
                "resident_status": "REQUIRES_COORDINATOR", "assignment_status": "UNRESOLVED",
                "next_step": "Coordinator follows up; assistance not confirmed."}

    # --------------------------------------------------------- post-calamity
    @r.post("/cases/{case_id}/recovery")
    async def recovery(case_id: str, request: Request):
        body = await request.json()
        if not body["consent"]["share_recovery_needs"]:
            return _err(409, "CONSENT_MISSING", "resident did not consent to share recovery needs")
        referrals, unmatched = [], []
        for help_type in body["help_types"]:
            org = RECOVERY_ORGS.get(help_type)
            if org is None:
                unmatched.append(help_type)
                continue
            state["ref_seq"] += 1
            rid = f"ref_{state['ref_seq']:03d}"
            state["referrals"][rid] = {"org_id": org, "help_type": help_type}
            referrals.append({"referral_id": rid, "help_type": help_type, "org_id": org, "status": "REQUESTED",
                              "shared_payload": {"referral_id": rid, "help_type": help_type, "language": "es",
                                                 "needs": [1, 6], "pet_count": 1}})
        return JSONResponse(status_code=201, content={"schema_version": V2, "case_id": case_id, "referrals": referrals,
                                                      "unmatched_help_types": unmatched, "housing_secured": False})

    @r.post("/recovery/{referral_id}/respond")
    async def respond(referral_id: str, request: Request):
        body = await request.json()
        ref = state["referrals"][referral_id]
        if body["org_id"] != ref["org_id"]:
            return _err(403, "UNAUTHORIZED", "only the referred org can respond")
        status = {"ACCEPTED": "ACCEPTED", "DECLINED": "UNRESOLVED", "COMPLETED": "COMPLETED"}[body["decision"]]
        return {"schema_version": V2, "referral_id": referral_id, "status": status, "housing_secured": False}

    # ------------------------------------------------- road closures (contract §5.9)
    GAZETTEER = {"ridge ave": "seg_ridge_ave", "canyon rd": "seg_canyon_rd"}  # unmapped names never route

    @r.get("/demo/feeds/closures")
    def official_feed():
        return {"schema_version": V2, "closures": state["official_feed"]}

    @r.get("/demo/feeds/news")
    def news_feed():
        return {"schema_version": V2, "items": state["news_feed"]}

    @r.post("/demo/closures/trigger")
    async def closures_trigger(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        n = len(state["official_feed"]) + len(state["news_feed"]) + 1
        if body["action"] == "PUBLISH_OFFICIAL":
            state["official_feed"].append({"closure_id": f"off_{n:03d}", "issuing_authority":
                                           "SIMULATED_LA_COUNTY_PUBLIC_WORKS", "road_name": body["road_name"],
                                           "status": "CLOSED", "published_at": _now(), "expires_at": None})
        elif body["action"] == "PUBLISH_NEWS":
            state["news_feed"].append({"item_id": f"news_{n:03d}", "source_name": "Fictional Valley Gazette (DEMO)",
                                       "url": None, "published_at": _now(), "headline": body.get("headline", ""),
                                       "body": body.get("body", "")})
        return {"schema_version": V2, "action": body["action"]}

    @r.post("/closures/ingest")
    async def closures_ingest(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        source_type = body["source"]["source_type"]
        accepted, rejected = [], []
        for item in body["items"]:
            key = (body["source"]["source_id"], item["source_item_id"])
            if key in state["closure_keys"]:
                continue
            state["closure_keys"].add(key)
            cand = item.get("candidate") or {}
            road = cand.get("road_name", "")
            if not road:
                rejected.append({"source_item_id": item["source_item_id"], "reason": "NO_CANDIDATE"})
                continue
            # Deterministic state rules (B's job; the agent never sets state).
            if source_type == "OFFICIAL_SIMULATION" and cand.get("claimed_status") == "CLOSED":
                st = "OFFICIAL_CONFIRMED"
            else:
                st = "UNVERIFIED_REPORT"
            segment = GAZETTEER.get(road.lower())
            same = [c for c in state["closures"] if c["segment_id"] and c["segment_id"] == segment]
            if any(c["claimed_status"] != cand.get("claimed_status") for c in same):
                st = "CONFLICTING"
                for c in same:
                    if c["state"] != "OFFICIAL_CONFIRMED":
                        c["state"] = "CONFLICTING"
            state["closure_seq"] += 1
            rec = {"closure_id": f"closure_{state['closure_seq']:03d}", "road_name": road, "segment_id": segment,
                   "state": st, "claimed_status": cand.get("claimed_status"),
                   "used_for_routing": st == "OFFICIAL_CONFIRMED" and segment is not None,
                   "sources": [{"source_type": source_type, "url": body["source"].get("url"),
                                "published_at": item.get("published_at"), "headline": item.get("headline"),
                                "extraction_method": item.get("extraction_method")}], "expires_at": None}
            state["closures"].append(rec)
            accepted.append({k: rec[k] for k in ("closure_id", "road_name", "state", "segment_id", "claimed_status",
                                                 "used_for_routing")} | {"source_type": source_type})
        return {"schema_version": V2, "accepted": accepted, "rejected": rejected,
                "new_official_closures": [a for a in accepted if a["state"] == "OFFICIAL_CONFIRMED"],
                "notify_coordinator": bool(accepted)}

    @r.get("/closures")
    def closures():
        return {"schema_version": V2, "closures": state["closures"],
                "note": "No report does not mean a road is open."}

    return r


def build_v2_app(db_path: str | None = ":memory:"):
    """B's real app + v2 stand-ins in front. Also used by scripts/dev_backend_v2.py (DEV ONLY)."""
    app = create_app(db_path, seed=True)
    state: dict[str, Any] = {"features": [], "edit": 1_792_281_600_000, "seen": set(), "ingests": 0, "alert_seq": 0,
                             "proposals": {}, "declined": {}, "assignments": {}, "assign_seq": 0, "esc_seq": 0,
                             "escalations": {}, "ref_seq": 0, "referrals": {}, "service": app.state.service,
                             "availability": {}, "outreach_keys": {}, "closures": [], "closure_keys": set(),
                             "closure_seq": 0,
                             "official_feed": [{"closure_id": "off_001",
                                                "issuing_authority": "SIMULATED_LA_COUNTY_PUBLIC_WORKS",
                                                "road_name": "Ridge Ave", "status": "CLOSED",
                                                "published_at": "2026-10-17T20:05:00Z", "expires_at": None}],
                             "news_feed": [{"item_id": "news_001", "source_name": "Fictional Valley Gazette (DEMO)",
                                            "url": None, "published_at": "2026-10-17T20:07:00Z",
                                            "headline": "Residents report Canyon Rd blocked by debris (DEMO)",
                                            "body": "Neighbors say a fallen tree stops traffic near Zone 3. (DEMO)"},
                                           {"item_id": "news_002", "source_name": "Fictional Valley Gazette (DEMO)",
                                            "url": None, "published_at": "2026-10-17T20:09:00Z",
                                            "headline": "Library bake sale raises funds (DEMO)",
                                            "body": "Volunteers sold 300 cookies. (DEMO)"}]}
    state["cases_created"] = False
    router = build_v2_router(state)
    for route in reversed(router.routes):
        app.router.routes.insert(0, route)
    return app, state


def make_v2_backend(monkeypatch) -> tuple[DoorstepBackendV2, dict]:
    """In-process client for tests. Returns (client, state)."""
    monkeypatch.setenv("SIMULATION_MODE", "true")
    monkeypatch.delenv("DEMO_AUTH_TOKEN", raising=False)
    app, state = build_v2_app()
    client = DoorstepBackendV2(base_url="http://backend.test", token=TOKEN, transport=httpx.ASGITransport(app=app))
    return client, state

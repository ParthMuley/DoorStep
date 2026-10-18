"""Scripted Scenario A (Maria) and Scenario B (David) against contract v1.0, API only.

Works with any client exposing ``.get/.post`` -> response with ``.status_code``
and ``.json()`` (FastAPI TestClient or httpx.Client). Raw provider offers come
from ``seed.transport_offers()`` / ``seed.destination_offers()``, standing in for
Developer A's provider agents. All data is synthetic; nothing leaves this machine.

    PYTHONPATH=src python -m doorstep.demo.scenarios --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from . import seed

MARIA = seed.CASE_IDS["resident_001"]
DAVID = seed.CASE_IDS["resident_002"]
MARIA_SPANISH_REPLY = "1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño."


class ScenarioFailure(AssertionError):
    pass


def _ok(resp, *expected: int) -> dict[str, Any]:
    expected = expected or (200,)
    if resp.status_code not in expected:
        raise ScenarioFailure(f"Expected HTTP {expected}, got {resp.status_code}: {resp.text}")
    body = resp.json()
    if body.get("schema_version") != "1.0":
        raise ScenarioFailure(f"Response missing schema_version: {body}")
    return body


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ScenarioFailure(msg)


def run_scenario_a(client, log=print) -> dict[str, Any]:
    _ok(client.post("/demo/warnings", json={"zone_id": seed.DEMO_ZONE, "scenario_id": seed.SCENARIO_ID,
                                            "alert_source": "SIMULATED_OFFICIAL"}), 201)
    status = _ok(client.get(f"/cases/{MARIA}"))
    _check(status["resident_status"] == "UNKNOWN", "new case must start UNKNOWN (silence != danger)")
    log("A1 simulated official warning; Maria's case starts UNKNOWN / SENT")

    r = _ok(client.post(f"/cases/{MARIA}/responses",
                        json={"text": MARIA_SPANISH_REPLY, "language": "es", "sender": seed.MARIA_SENDER,
                              "external_id": "sim_maria_reply_1"}))
    _check(r["intent"] == "NEED_HELP" and not r["needs_confirmed"], "Spanish reply should request help")
    _check(r["confirmation_question"].startswith("DOORSTEP DEMO"), "confirmation must be DEMO-labeled")
    log("A2 Spanish reply parsed -> candidate needs, awaiting confirmation")

    r = _ok(client.post(f"/cases/{MARIA}/responses",
                        json={"text": "SI", "language": "es", "sender": seed.MARIA_SENDER,
                              "external_id": "sim_maria_reply_2"}))
    _check(r["needs_confirmed"] and r["needs"]["wheelchair_accessible_vehicle"], "needs confirmed after SI")
    log("A3 resident confirmed needs")

    t = _ok(client.post(f"/cases/{MARIA}/transport/evaluate",
                        json={"request_id": "req_001", "service_type": "accessible_transport",
                              "candidate_offers": seed.transport_offers()}))
    _check(t["eligible"] and t["eligible"][0]["offer_id"] == "offer_t_001", "expected offer_t_001 ranked first")
    rejected = {x["provider_id"]: x["reasons"] for x in t["rejected"]}
    _check("NOT_WHEELCHAIR_ACCESSIBLE" in rejected.get("transport_org_b", []),
           "closer sedan must be rejected as not wheelchair accessible")
    _check(not t["escalation_required"], "no escalation for Maria")
    log(f"A4 transport: eligible={[x['offer_id'] for x in t['eligible']]} rejected={sorted(rejected)}")

    d = _ok(client.post(f"/cases/{MARIA}/destination/evaluate",
                        json={"request_id": "req_002", "service_type": "accessible_destination",
                              "candidate_offers": seed.destination_offers()}))
    _check(d["eligible"] and d["eligible"][0]["offer_id"] == "offer_d_001", "expected offer_d_001")
    log("A5 destination: offer_d_001 eligible")

    body = {"transport_offer_id": "offer_t_001", "destination_offer_id": "offer_d_001",
            "authorization": "SIMULATED_PREAPPROVED", "idempotency_key": f"{MARIA}:transport:v1"}
    a = _ok(client.post(f"/cases/{MARIA}/assignments", json=body), 201)
    again = _ok(client.post(f"/cases/{MARIA}/assignments", json=body), 200)
    _check(again["assignment_id"] == a["assignment_id"], "repeated idempotency key returns the original")
    _check(a["service_status"] == "AWAITING_PROVIDER" and a["resident_status"] == "NEEDS_ASSISTANCE",
           "proposal is not acceptance")
    _check("pickup_point" not in a["shared_with_provider"], "exact pickup point only after acceptance")
    aid = a["assignment_id"]
    log(f"A6 proposed {aid} (transport + destination); repeat key returned same assignment")

    acc = _ok(client.post(f"/assignments/{aid}/acceptance",
                          json={"provider_id": "transport_org_a", "decision": "ACCEPTED",
                                "idempotency_key": f"{aid}:acceptance:transport_org_a"}))
    _check(acc["resident_status"] == "PROVIDER_ACCEPTED", "acceptance -> PROVIDER_ACCEPTED (yellow)")
    _check(acc["pickup_details"] and acc["pickup_details"]["pickup_point"].startswith("SYNTHETIC"),
           "pickup point released after acceptance")
    _check(acc["confirmed_pickup_at"] is None and acc["confirmed_arrival_at"] is None,
           "acceptance must not set pickup or arrival")
    _ok(client.post(f"/assignments/{aid}/acceptance",
                    json={"provider_id": "destination_org_a", "decision": "ACCEPTED"}))
    log("A7 transport + destination accepted; pickup/arrival still unconfirmed")

    p = _ok(client.post(f"/assignments/{aid}/pickup", json={
        "evidence": {"type": "PROVIDER_AND_RESIDENT_CONFIRMATION", "provider_confirmed": True,
                     "resident_confirmed": True, "code_verified": True, "source": "SIMULATED"},
        "idempotency_key": f"{aid}:pickup"}))
    _check(p["resident_status"] == "PICKUP_CONFIRMED" and p["confirmed_arrival_at"] is None,
           "pickup -> PICKUP_CONFIRMED (blue), never arrival")
    log("A8 pickup confirmed (not arrival)")

    arr = _ok(client.post(f"/assignments/{aid}/arrival", json={
        "evidence": {"type": "DESTINATION_CHECKIN", "destination_provider_id": "destination_org_a",
                     "provider_confirmed": True, "source": "SIMULATED"},
        "idempotency_key": f"{aid}:arrival"}))
    _check(arr["resident_status"] == "ARRIVAL_CONFIRMED" and arr["service_status"] == "COMPLETED",
           "arrival -> ARRIVAL_CONFIRMED (green)")
    log("A9 arrival confirmed -> green")

    rec = _ok(client.post(f"/cases/{MARIA}/recovery-referrals", json={
        "consent": {"share_recovery_needs": True, "granted_by": "RESIDENT", "granted_at": "2026-10-17T18:40:00Z"},
        "idempotency_key": f"{MARIA}:recovery:v1"}), 201)
    _check(rec["status"] == "REQUESTED" and rec["housing_secured"] is False, "referral REQUESTED, no housing")
    _check("pickup_point" not in rec["shared_fields"], "recovery payload must be consent-scoped")
    ref = _ok(client.post(f"/recovery-referrals/{rec['referral_id']}/response",
                          json={"provider_id": "recovery_org_demo", "decision": "ACCEPTED"}))
    _check(ref["status"] == "ACCEPTED" and ref["housing_secured"] is False, "follow-up accepted, not housing")
    log("A10 consented recovery referral REQUESTED -> ACCEPTED (housing not secured)")

    final = _ok(client.get(f"/cases/{MARIA}"))
    _check(final["map"]["color"] == "green", "final map color must be green")
    _check(final["evidence"]["timeline_replay_matches_status"], "timeline replay must match status")
    _check(not final["unresolved"], "Maria's case should be resolved")
    log("A  PASS\n" + final["summary_text"])
    return final


def run_scenario_b(client, log=print) -> dict[str, Any]:
    _ok(client.post("/demo/warnings", json={"zone_id": seed.DEMO_ZONE, "scenario_id": seed.SCENARIO_ID}), 201)
    _ok(client.post(f"/cases/{DAVID}/responses",
                    json={"text": "1 NEED HELP", "language": "en", "sender": seed.DAVID_SENDER,
                          "external_id": "sim_david_reply_1"}))
    _ok(client.post(f"/cases/{DAVID}/responses",
                    json={"text": "YES", "language": "en", "sender": seed.DAVID_SENDER,
                          "external_id": "sim_david_reply_2"}))
    log("B1 David requested help and confirmed needs")

    t = _ok(client.post(f"/cases/{DAVID}/transport/evaluate",
                        json={"request_id": "req_101", "candidate_offers": seed.transport_offers()}))
    _check(t["zone_rule"] == "INSIDE_ACTIVE_ORDER" and t["eligible"] == [], "no offer eligible inside active order")
    _check(all("ACTIVE_ORDER_ZONE" in x["reasons"] for x in t["rejected"]), "every offer cites ACTIVE_ORDER_ZONE")
    _check(t["escalation_required"], "escalation_required must be true")
    log("B2 all transport offers rejected: ACTIVE_ORDER_ZONE, escalation_required")

    blocked = client.post(f"/cases/{DAVID}/assignments", json={"transport_offer_id": "offer_t_001"})
    _check(blocked.status_code == 409 and blocked.json()["error"] == "UNSAFE_ZONE",
           f"proposing inside the order zone must be refused with UNSAFE_ZONE, got {blocked.status_code} {blocked.text}")
    log("B3 direct proposal refused: 409 UNSAFE_ZONE")

    esc = _ok(client.post(f"/cases/{DAVID}/escalations",
                          json={"reason": "ACTIVE_EVACUATION_ORDER_ZONE",
                                "idempotency_key": f"{DAVID}:escalation:v1"}), 201)
    _check(esc["status"] == "ACKNOWLEDGED_REQUEST_ONLY" and esc["assistance_confirmed"] is False,
           "simulated ack means received only")
    _check(esc["resident_status"] == "REQUIRES_COORDINATOR" and esc["service_status"] == "UNRESOLVED",
           "case stays unresolved")
    log("B4 simulated authorized service acknowledged receipt only")

    final = _ok(client.get(f"/cases/{DAVID}"))
    _check(final["unresolved"] and final["map"]["color"] == "black", "David must remain unresolved")
    _check(final["active_assignment"] is None, "no assignment may exist for David")
    _check(final["evidence"]["timeline_replay_matches_status"], "timeline replay must match status")
    log("B  PASS\n" + final["summary_text"])
    return final


# =================================================================== contract v2.0 flow
def _ok2(resp, *expected: int) -> dict[str, Any]:
    expected = expected or (200,)
    if resp.status_code not in expected:
        raise ScenarioFailure(f"Expected HTTP {expected}, got {resp.status_code}: {resp.text}")
    body = resp.json()
    if body.get("schema_version") != "2.0":
        raise ScenarioFailure(f"Response missing schema_version 2.0: {body}")
    return body


NETWORK = {"X-Agent-Token": os.environ.get("NETWORK_AGENT_TOKEN") or "change-me-network-agent-token"}


def start_alert_v2(client, log=print) -> dict[str, Any]:
    r = _ok2(client.post("/demo/alerts/trigger", json={"action": "ISSUE", "preset": "ZONE_3_WILDFIRE",
                                                       "poll_now": True}))
    poll = r["poll_result"]
    _check(poll["feed_freshness"] == "FRESH", "synthetic feed should be fresh")
    zones = {c["case_id"]: c["zone_status"] for c in poll["affected_cases"]}
    _check(zones == {MARIA: "WARNING", DAVID: "ORDER"}, f"unexpected zones {zones}")
    _check(len(poll["checkins_sent"]) == 2, "one check-in per affected resident")
    orgs = [o["org_id"] for o in poll["outreach_orgs"]]
    _check("flood_only_demo" not in orgs and "unlisted_vans_demo" not in orgs, "only fire-capable approved orgs")
    red_cross = next(o for o in poll["outreach_orgs"] if o["org_id"] == "red_cross_demo")
    _check("sf:mission" not in red_cross["region_ids"], "far-away regions (SF) are never contacted for an LA fire")
    log(f"V2-1 alert ingested: zones={zones}, outreach orgs={orgs}")
    return poll


def run_scenario_a_v2(client, log=print) -> dict[str, Any]:
    poll = start_alert_v2(client, log)
    alert_id = next(a["alert_id"] for a in poll["new_alerts"] if a["status"] == "WARNING")
    outreach = _ok2(client.post(f"/alerts/{alert_id}/outreach", json={}, headers=NETWORK))
    asked = sorted(a["volunteer_id"] for o in outreach["orgs"] for a in o["asked"])
    _check("volunteer_sam" not in asked, "SF volunteer never asked")
    replies = {"sim_phone_sarah": "YES", "sim_phone_joe": "YES", "sim_phone_maya": "NO", "sim_phone_lee": "SI"}
    for phone, text in replies.items():
        _ok(client.post("/sim/inbound", json={"sender": phone, "text": text, "external_id": f"v2-{phone}"}))
    log(f"V2-2 Volunteer Network asked nearby volunteers {asked}; Sarah/Joe/Lee yes, Maya no")

    _ok(client.post(f"/cases/{MARIA}/responses", json={"text": MARIA_SPANISH_REPLY, "language": "es",
                                                       "sender": seed.MARIA_SENDER, "external_id": "v2-maria-1"}))
    _ok(client.post(f"/cases/{MARIA}/responses", json={"text": "SI", "language": "es",
                                                       "sender": seed.MARIA_SENDER, "external_id": "v2-maria-2"}))
    log("V2-3 Maria asked for help in Spanish and confirmed needs")

    ev = _ok2(client.post("/matches/propose", json={"case_id": MARIA, "create_proposal": False}))
    vols = ev["evaluation"]["volunteers"]
    _check(vols["eligible"][0]["volunteer_id"] == "volunteer_sarah", "Sarah should rank first")
    joe = next(v for v in vols["rejected"] if v["volunteer_id"] == "volunteer_joe")
    _check("NEEDS_NOT_COVERED" in joe["reason_codes"] and joe["missing_needs"] == [1, 2],
           "closer sedan rejected: wheelchair + transfer not covered")
    log(f"V2-4 suitable: {[v['volunteer_id'] for v in vols['eligible']]}; Joe rejected {joe['reason_codes']}")

    m = _ok2(client.post("/matches/propose", json={"case_id": MARIA, "idempotency_key": f"{MARIA}:match:v1"}), 201)
    match = m["match"]
    _check(match["volunteer_id"] == "volunteer_sarah" and match["site_id"] == "dest_center_a" and match["reserved"],
           "Sarah + civic center, volunteer reserved")
    _check(_ok2(client.post("/matches/propose", json={"case_id": MARIA, "idempotency_key": f"{MARIA}:match:v1"}))
           ["duplicate"], "repeated key returns the original match")
    aid = match["assignment_id"]
    log(f"V2-5 match {aid}: Sarah ({match['vehicle_type']}) + {match['site_id']}, ETA ~{match['eta_estimate']['minutes']} min")

    acc = _ok2(client.post(f"/assignments/{aid}/accept", headers=NETWORK,
                           json={"org_id": "eastside_rides_demo", "volunteer_id": "volunteer_sarah",
                                 "decision": "ACCEPTED"}))
    _check(acc["resident_status"] == "PROVIDER_ACCEPTED" and acc["help_on_the_way_sent"], "help on the way sent")
    _check(acc["pickup_details"]["pickup_point"].startswith("SYNTHETIC"), "pickup point only after acceptance")
    _check(acc["confirmed_pickup_at"] is None and acc["confirmed_arrival_at"] is None, "acceptance != pickup")
    _ok2(client.post(f"/assignments/{aid}/accept", headers=NETWORK,
                     json={"org_id": "civic_shelter_demo", "site_id": "dest_center_a", "decision": "ACCEPTED"}))
    log("V2-6 volunteer accepted (resident told help is on the way, ETA is an estimate); shelter bed confirmed")

    run_routes_v2(client, aid, log)

    # Resident side by SMS (Maria texts RECOGIDO), volunteer side from the PickupReport.
    _ok(client.post("/sim/inbound", json={"sender": seed.MARIA_SENDER, "text": "RECOGIDO", "external_id": "v2-pickup"}))
    p = _ok(client.post(f"/assignments/{aid}/pickup", json={"evidence": {
        "type": "VOLUNTEER_AND_RESIDENT_CONFIRMATION", "volunteer_confirmed": True, "code_verified": True,
        "confirmations": [{"party": "volunteer", "party_id": "volunteer_sarah"}]}}))
    _check(p["resident_status"] == "PICKUP_CONFIRMED" and p["confirmed_arrival_at"] is None, "pickup != arrival")
    a = _ok(client.post(f"/assignments/{aid}/arrival", json={"evidence": {
        "type": "SHELTER_CHECKIN", "shelter_org_id": "civic_shelter_demo", "site_id": "dest_center_a",
        "shelter_confirmed": True}}))
    _check(a["resident_status"] == "ARRIVAL_CONFIRMED", "arrival -> green")
    log("V2-7 pickup (Maria's RECOGIDO + volunteer report) then shelter check-in -> green")

    # Post-calamity: Maria says SI to sharing her needs; the Post-Calamity agent requests help.
    _ok(client.post("/sim/inbound", json={"sender": seed.MARIA_SENDER, "text": "SI", "external_id": "v2-recovery-si"}))
    rec = _ok2(client.post(f"/cases/{MARIA}/recovery", json={
        "consent": {"share_recovery_needs": True, "granted_by": "RESIDENT"},
        "help_types": ["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"], "idempotency_key": f"{MARIA}:recovery:v2"}), 201)
    refs = {r["help_type"]: r for r in rec["referrals"]}
    _check(set(refs) == {"TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"} and not rec["housing_secured"],
           "one referral per help type, nothing secured yet")
    _check("phone" not in str(rec) and "address" not in str(rec), "only consent-scoped fields shared")
    housing = refs["TEMPORARY_HOUSING"]
    _ok2(client.post(f"/recovery/{housing['referral_id']}/respond", headers=NETWORK,
                     json={"org_id": housing["org_id"], "decision": "ACCEPTED"}))
    done = _ok2(client.post(f"/recovery/{housing['referral_id']}/respond", headers=NETWORK,
                            json={"org_id": housing["org_id"], "decision": "COMPLETED",
                                  "evidence": {"type": "SIMULATED_SERVICE_CONFIRMED", "reference": "res_sim_001"}}))
    _check(done["housing_secured"], "housing secured only after COMPLETED with evidence")
    log(f"V2-8 post-calamity: housing via {housing['org_id']} COMPLETED (simulated), insurance guidance REQUESTED")

    final = _ok(client.get(f"/cases/{MARIA}"))
    _check(final["map"]["color"] == "green" and final["evidence"]["timeline_replay_matches_status"], "green + replay")
    _check(final["recovery"]["housing_secured"], "case view shows recovery")
    log("V2-A PASS\n" + final["summary_text"])
    return final


# Mock HERE polylines (the Route agent would get these from HERE Routing v8).
ROUTE_THROUGH_RIDGE = {"type": "LineString", "coordinates": [[-118.110, 34.095], [-118.0964, 34.1012],
                                                             [-118.082, 34.098], [-118.070, 34.089]]}
ROUTE_AVOIDING_RIDGE = {"type": "LineString", "coordinates": [[-118.110, 34.095], [-118.0964, 34.1012],
                                                              [-118.093, 34.089], [-118.070, 34.089]]}


def run_routes_v2(client, aid: str, log=print) -> dict[str, Any]:
    """News agent ingests closures; Route agent asks for constraints, B post-checks HERE's line."""
    official = client.get("/demo/feeds/closures").json()["closures"]
    _ok2(client.post("/closures/ingest", json={
        "source": {"source_id": "SYNTHETIC_OFFICIAL_CLOSURES", "source_type": "OFFICIAL_SIMULATION"},
        "items": [{"source_item_id": c["closure_id"], "published_at": c["published_at"], "expires_at": c["expires_at"],
                   "headline": f"{c['road_name']} {c['status']} (SIMULATED)", "extraction_method": "STRUCTURED_FEED",
                   "candidate": {"road_name": c["road_name"], "claimed_status": c["status"]}} for c in official],
        "idempotency_key": "official-1"}))
    news = client.get("/demo/feeds/news").json()["items"]
    _ok2(client.post("/closures/ingest", json={
        "source": {"source_id": "SYNTHETIC_NEWS", "source_type": "NEWS"},
        "items": [{"source_item_id": n["item_id"], "published_at": n["published_at"], "headline": n["headline"],
                   "raw_text": n["body"], "extraction_method": "ASI_ONE_EXTRACTION",
                   "candidate": {"road_name": "Canyon Rd", "claimed_status": "CLOSED"}} for n in news],
        "idempotency_key": "news-1"}))
    closures = {c["road_name"]: c for c in _ok2(client.get("/closures"))["closures"]}
    _check(closures["Ridge Ave"]["state"] == "OFFICIAL_CONFIRMED" and closures["Ridge Ave"]["used_for_routing"],
           "official closure blocks the road")
    _check(closures["Canyon Rd"]["state"] == "UNVERIFIED_REPORT" and not closures["Canyon Rd"]["used_for_routing"],
           "news report is a caution, never a block")
    log("V2-6b closures: Ridge Ave OFFICIAL_CONFIRMED (blocks), Canyon Rd UNVERIFIED_REPORT (caution)")

    c1 = _ok2(client.post("/routes/constraints", json={"assignment_id": aid, "idempotency_key": f"{aid}:route:1"}))
    kinds = sorted(a["kind"] for a in c1["avoid_areas"])
    _check(kinds == ["OFFICIAL_CLOSURE", "ORDER_ZONE"] and len(c1["cautions"]) == 1, "avoid order zone + official")
    bad = _ok2(client.post("/routes/previews", json={"route_request_id": c1["route_request_id"], "provider": "HERE",
                                                     "polyline": ROUTE_THROUGH_RIDGE, "distance_m": 4100,
                                                     "duration_s": 540}))
    _check(bad["status"] == "REFUSED" and bad["crosses"], "a line through an official closure is refused")
    c2 = _ok2(client.post("/routes/constraints", json={"assignment_id": aid, "idempotency_key": f"{aid}:route:2"}))
    good = _ok2(client.post("/routes/previews", json={"route_request_id": c2["route_request_id"], "provider": "HERE",
                                                      "polyline": ROUTE_AVOIDING_RIDGE, "distance_m": 4600,
                                                      "duration_s": 660}))
    _check(good["status"] == "ILLUSTRATIVE_ONLY" and good["cautions_on_path"] and good["label"].startswith("ILLUSTRATIVE"),
           "illustrative route with a caution for the unverified report")
    log(f"V2-6c route: through Ridge Ave REFUSED; detour ILLUSTRATIVE_ONLY, ETA ~{good['eta']['minutes']} min "
        "(estimate), caution on Canyon Rd")
    return good


def run_scenario_b_v2(client, log=print) -> dict[str, Any]:
    _ok(client.post(f"/cases/{DAVID}/responses", json={"text": "1 NEED HELP", "language": "en",
                                                       "sender": seed.DAVID_SENDER, "external_id": "v2-david-1"}))
    _ok(client.post(f"/cases/{DAVID}/responses", json={"text": "YES", "language": "en",
                                                       "sender": seed.DAVID_SENDER, "external_id": "v2-david-2"}))
    m = _ok2(client.post("/matches/propose", json={"case_id": DAVID}))
    _check(m["match"] is None and m["no_match_reason"] == "ORDER_ZONE" and m["escalation_required"],
           "no ordinary volunteer inside an active order zone")
    esc = _ok2(client.post(f"/cases/{DAVID}/escalate", json={"reason": "ACTIVE_EVACUATION_ORDER_ZONE",
                                                             "idempotency_key": f"{DAVID}:escalation:v1"}), 201)
    if esc["status"] == "REQUESTED":  # an Escalation agent would acknowledge; simulate it
        esc = _ok2(client.post(f"/escalations/{esc['escalation_id']}/ack",
                               json={"status": "ACKNOWLEDGED_REQUEST_ONLY"}))
    _check(esc["status"] == "ACKNOWLEDGED_REQUEST_ONLY" and esc["assistance_confirmed"] is False, "receipt only")
    final = _ok(client.get(f"/cases/{DAVID}"))
    _check(final["unresolved"] and final["map"]["color"] == "black", "David stays unresolved")
    log("V2-B PASS\n" + final["summary_text"])
    return final


def run_scenario_c_v2(client, log=print) -> dict[str, Any]:
    start_alert_v2(client, log)
    _ok(client.post(f"/cases/{MARIA}/responses", json={"text": "1", "language": "es", "sender": seed.MARIA_SENDER,
                                                       "external_id": "v2c-1"}))
    _ok(client.post(f"/cases/{MARIA}/responses", json={"text": "SI", "language": "es", "sender": seed.MARIA_SENDER,
                                                       "external_id": "v2c-2"}))
    r = _ok2(client.post("/demo/alerts/trigger", json={"action": "FREEZE_FEED", "freeze_age_minutes": 30,
                                                       "poll_now": True}))
    _check(r["poll_result"]["feed_freshness"] == "STALE", "frozen feed goes stale")
    m = _ok2(client.post("/matches/propose", json={"case_id": MARIA}))
    _check(m["match"] is None and m["no_match_reason"] == "ZONE_STALE", "stale data -> no assignment")
    final = _ok(client.get(f"/cases/{MARIA}"))
    _check(final["zone_status"] == "STALE" and final["map"]["color"] != "green", "nobody marked safe")
    log("V2-C PASS: stale feed -> STALE zones, matching refused")
    return final


def main(argv: list[str] | None = None) -> int:
    import httpx

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("DOORSTEP_API_URL") or "http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.environ.get("DEMO_AUTH_TOKEN") or "change-me-local-demo-token")
    parser.add_argument("--scenario", choices=["a", "b", "both"], default="both")
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--flow", choices=["v1", "v2", "both"], default="both")
    args = parser.parse_args(argv)
    headers = {"Authorization": f"Bearer {args.token}", "X-Correlation-ID": "corr_smoke"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=10) as client:
        _ok(client.get("/health"))
        try:
            if args.flow in ("v1", "both"):
                if not args.no_reset:
                    _ok(client.post("/demo/reset", json={"dataset": "core"}))
                if args.scenario in ("a", "both"):
                    run_scenario_a(client)
                if args.scenario in ("b", "both"):
                    run_scenario_b(client)
            if args.flow in ("v2", "both"):
                _ok(client.post("/demo/reset", json={"dataset": "core"}))
                if args.scenario in ("a", "both"):
                    run_scenario_a_v2(client)
                if args.scenario in ("b", "both"):
                    if args.scenario == "b":
                        start_alert_v2(client)
                    run_scenario_b_v2(client)
                _ok(client.post("/demo/reset", json={"dataset": "core"}))
                run_scenario_c_v2(client)
        except ScenarioFailure as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
    print("ALL SCENARIOS PASSED (simulation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

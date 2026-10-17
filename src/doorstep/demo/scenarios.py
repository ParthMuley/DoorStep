"""Scripted Scenario A (Maria) and Scenario B (David), API-only.

Works with any client exposing ``.get/.post`` -> response with ``.status_code``
and ``.json()`` (FastAPI TestClient or httpx.Client). Used by unit tests and by
scripts/smoke_test.sh. All data is synthetic; nothing leaves this machine.

    PYTHONPATH=src python -m doorstep.demo.scenarios --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from . import seed

MARIA_PHONE = "sms:+15555550101"
DAVID_PHONE = "sms:+15555550102"
MARIA_SPANISH_REPLY = ("Necesito ayuda. Uso silla de ruedas, tengo un perrito y necesito ayuda "
                       "para subir a la camioneta.")


class ScenarioFailure(AssertionError):
    pass


def _ok(resp, expected: int = 200) -> dict[str, Any]:
    if resp.status_code != expected:
        raise ScenarioFailure(f"Expected HTTP {expected}, got {resp.status_code}: {resp.text}")
    return resp.json()


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ScenarioFailure(msg)


def _first_eligible(offers: list[dict]) -> dict:
    eligible = [o for o in offers if o["eligible"]]
    _check(bool(eligible), "expected at least one eligible offer")
    return eligible[0]


def run_scenario_a(client, log=print) -> dict[str, Any]:
    case_id = seed.CASE_IDS["resident_001"]
    _ok(client.post("/demo/warnings", json={"zone_id": seed.DEMO_ZONE, "scenario_id": seed.SCENARIO_A}))
    status = _ok(client.get(f"/cases/{case_id}"))
    _check(status["case"]["resident_status"] == "UNKNOWN", "new case must start UNKNOWN (silence != danger)")
    log("A1 warning sent; Maria's case starts UNKNOWN / SENT")

    r = _ok(client.post(f"/cases/{case_id}/responses",
                        json={"text": MARIA_SPANISH_REPLY, "sender": MARIA_PHONE, "language": "es",
                              "external_id": "sim_maria_reply_1"}))
    _check(r["intent"] == "NEED_HELP" and r["requires_confirmation"], "Spanish reply should request help")
    _check(r["confirmation_prompt"].startswith("DOORSTEP DEMO"), "confirmation must be DEMO-labeled")
    log("A2 Spanish reply parsed -> candidate needs, awaiting confirmation")

    r = _ok(client.post(f"/cases/{case_id}/responses",
                        json={"text": "Sí", "sender": MARIA_PHONE, "language": "es",
                              "external_id": "sim_maria_reply_2"}))
    _check(r["needs_confirmed"], "needs should be confirmed after SÍ")
    log("A3 resident confirmed needs")

    t = _ok(client.post("/transport/find", json={"case_id": case_id}))
    best = _first_eligible(t["offers"])
    rejected = {o["provider_id"]: o["reasons"] for o in t["offers"] if not o["eligible"]}
    _check(best["provider_id"] == "transport_org_a", f"expected transport_org_a, got {best['provider_id']}")
    _check("NOT_WHEELCHAIR_ACCESSIBLE" in rejected.get("transport_org_b", []),
           "closer sedan must be rejected as not wheelchair accessible")
    log(f"A4 transport offers: eligible={best['provider_id']} rejected={sorted(rejected)}")

    d = _ok(client.post("/destinations/find", json={"case_id": case_id}))
    dest = _first_eligible(d["offers"])
    _check(dest["provider_id"] == "dest_center_a", "expected the step-free, pet-friendly center")
    log(f"A5 destination offer: {dest['provider_id']}")

    ta = _ok(client.post("/assignments/propose", json={"case_id": case_id, "offer_id": best["offer_id"]}))
    da = _ok(client.post("/assignments/propose", json={"case_id": case_id, "offer_id": dest["offer_id"]}))
    _check(ta["status"] == "AWAITING_PROVIDER", "proposal must await provider")
    status = _ok(client.get(f"/cases/{case_id}"))
    _check(status["case"]["resident_status"] == "NEEDS_ASSISTANCE", "proposal is not acceptance")

    acc = _ok(client.post(f"/assignments/{ta['assignment_id']}/respond",
                          json={"provider_id": ta["provider_id"], "accept": True}))
    _check(acc["resident_status"] == "PROVIDER_ACCEPTED", "acceptance -> PROVIDER_ACCEPTED (yellow)")
    _ok(client.post(f"/assignments/{da['assignment_id']}/respond",
                    json={"provider_id": da["provider_id"], "accept": True}))
    status = _ok(client.get(f"/cases/{case_id}"))
    _check(not status["evidence"]["pickup_confirmed"] and not status["evidence"]["arrival_confirmed"],
           "acceptance must not set pickup or arrival")
    log("A6 transport + destination accepted; pickup/arrival still unconfirmed")

    pickup = {"evidence": {"confirmations": [
        {"party": "transport_provider", "party_id": ta["provider_id"]},
        {"party": "resident", "party_id": "resident_001"}]}}
    p = _ok(client.post(f"/assignments/{ta['assignment_id']}/pickup", json=pickup))
    _check(p["resident_status"] == "PICKUP_CONFIRMED", "pickup -> PICKUP_CONFIRMED (blue)")
    _check(p["assignment"]["confirmed_arrival_at"] is None, "pickup must not set arrival")
    log("A7 pickup confirmed (not arrival)")

    arrival = {"evidence": {"confirmations": [
        {"party": "destination_provider", "party_id": da["provider_id"]},
        {"party": "resident", "party_id": "resident_001"}]}}
    a = _ok(client.post(f"/assignments/{ta['assignment_id']}/arrival", json=arrival))
    _check(a["resident_status"] == "ARRIVAL_CONFIRMED", "arrival -> ARRIVAL_CONFIRMED (green)")
    log("A8 arrival confirmed -> green")

    rec = _ok(client.post(f"/cases/{case_id}/recovery", json={"consent": True, "granted_by": "resident_001"}))
    _check(rec["referral"]["status"] == "REQUESTED", "referral starts REQUESTED")
    _check("pickup_point" not in rec["shared_fields"] and "contact_channel" not in rec["shared_fields"],
           "recovery payload must be consent-scoped")
    ref = _ok(client.post(f"/recovery/{rec['referral']['referral_id']}/respond",
                          json={"provider_id": rec["referral"]["provider_id"], "accept": True}))
    _check(ref["status"] == "ACCEPTED", "recovery follow-up accepted")
    log("A9 recovery referral requested with consent -> ACCEPTED (not housing secured)")

    final = _ok(client.get(f"/cases/{case_id}"))
    _check(final["map"]["color"] == "green", "final map color must be green")
    _check(final["evidence"]["timeline_replay_matches_status"], "timeline replay must match status")
    _check(not final["unresolved"], "Maria's case should be resolved")
    log("A  PASS\n" + final["summary_text"])
    return final


def run_scenario_b(client, log=print) -> dict[str, Any]:
    case_id = seed.CASE_IDS["resident_002"]
    _ok(client.post("/demo/warnings", json={"zone_id": seed.DEMO_ZONE, "scenario_id": seed.SCENARIO_B}))
    _ok(client.post(f"/cases/{case_id}/responses",
                    json={"text": "1 NEED HELP", "sender": DAVID_PHONE, "language": "en",
                          "external_id": "sim_david_reply_1"}))
    _ok(client.post(f"/cases/{case_id}/responses",
                    json={"text": "YES", "sender": DAVID_PHONE, "language": "en",
                          "external_id": "sim_david_reply_2"}))
    log("B1 David requested help and confirmed needs")

    t = _ok(client.post("/transport/find", json={"case_id": case_id}))
    _check(t["eligible_count"] == 0, "no ordinary provider may be eligible inside an active-order zone")
    _check(all("INSIDE_ACTIVE_ORDER_ZONE" in o["reasons"] for o in t["offers"]),
           "every offer must cite the active-order zone")
    _check(t["resident_status"] == "REQUIRES_COORDINATOR", "case goes to coordinator")
    log("B2 all transport offers blocked: INSIDE_ACTIVE_ORDER_ZONE")

    blocked = client.post("/assignments/propose", json={"case_id": case_id, "offer_id": t["offers"][0]["offer_id"]})
    _check(blocked.status_code == 422, f"proposing a blocked offer must be refused, got {blocked.status_code}")
    log("B3 direct proposal refused by safety gate (422)")

    esc = _ok(client.post(f"/cases/{case_id}/escalate", json={"reason": "ACTIVE_EVACUATION_ORDER_ZONE"}))
    _check(esc["status"] == "ACKNOWLEDGED_REQUEST_ONLY", "simulated ack means received only")
    _check(esc["assistance_confirmed"] is False, "acknowledgment must not confirm assistance")
    log("B4 simulated authorized service acknowledged receipt only")

    final = _ok(client.get(f"/cases/{case_id}"))
    _check(final["unresolved"], "David's case must remain unresolved")
    _check(final["map"]["color"] == "black", "coordinator-attention color")
    _check(not final["assignments"], "no assignment may exist for David")
    _check(final["evidence"]["timeline_replay_matches_status"], "timeline replay must match status")
    log("B  PASS\n" + final["summary_text"])
    return final


def main(argv: list[str] | None = None) -> int:
    import httpx

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("DOORSTEP_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.environ.get("DOORSTEP_DEMO_TOKEN", "doorstep-local-demo-token"))
    parser.add_argument("--scenario", choices=["a", "b", "both"], default="both")
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args(argv)
    with httpx.Client(base_url=args.base_url, headers={"X-Demo-Token": args.token}, timeout=10) as client:
        _ok(client.get("/health"))
        if not args.no_reset:
            _ok(client.post("/demo/reset"))
        try:
            if args.scenario in ("a", "both"):
                run_scenario_a(client)
            if args.scenario in ("b", "both"):
                run_scenario_b(client)
        except ScenarioFailure as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
    print("ALL SCENARIOS PASSED (simulation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

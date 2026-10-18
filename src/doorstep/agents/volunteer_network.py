"""Volunteer Network agent - DOORSTEP DEMO (team plan rev 3).

One agent for ALL partner organizations (no agent per org). For an alert it asks B to
pick the organizations in the regions nearest the evacuation zone, asks their volunteers
whether they're available (simulated SMS on each org's behalf), and records the answers
per alert. It forwards a volunteer's accept/decline and a shelter's bed confirmation,
reports pickup and arrival, and answers recovery referrals for recovery orgs. Every
write names its `org_id`; B checks the volunteer/site belongs to it.

Volunteer answers are simulated from `fixtures/volunteer_personas.json`. Never ranks
people, never reads the residents DB, never forwards pickup points or phones.

Run:  python -m doorstep.agents.volunteer_network
"""

import json
import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import build_agent, role_port, seed_for
from doorstep.integrations.fetch_messages import (
    AcceptRequest,
    AcceptResponse,
    ArrivalReport,
    OutreachRequest,
    OutreachResult,
    PickupReport,
    ReferralRequest,
    ReferralResponse,
    ReportRequest,
    ReportUnavailable,
    utc_now,
)
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()

PERSONAS = json.loads((Path(__file__).parent / "fixtures" / "volunteer_personas.json").read_text(encoding="utf-8"))


def persona(volunteer_id: str) -> dict[str, str]:
    return PERSONAS["volunteers"].get(volunteer_id, PERSONAS["default_volunteer"])


def declines(volunteer_id: str) -> bool:
    forced = {v.strip() for v in os.getenv("DECLINE_VOLUNTEERS", "").split(",") if v.strip()}
    return volunteer_id in forced or persona(volunteer_id)["on_assignment"] == "DECLINE"


def _error(err: Exception) -> dict[str, Any]:
    if isinstance(err, BackendError):
        return {"code": err.code, "detail": err.detail, "reasons": err.reasons, "status": err.status_code}
    return {"code": type(err).__name__, "detail": "backend unreachable"}


def build_network_protocol(get_backend: Callable[[], DoorstepBackendV2]) -> Protocol:
    proto = Protocol(name="doorstep_volunteer_network", version="2.1")
    accepted: dict[tuple[str, str], dict[str, Any]] = {}  # (assignment_id, role) -> what was accepted
    decisions: dict[str, AcceptResponse] = {}  # idempotency_key -> reply

    @proto.on_message(OutreachRequest, replies=OutreachResult)
    async def on_outreach(ctx: Context, sender: str, msg: OutreachRequest):
        backend, corr, alert_id = get_backend(), msg.correlation_id, msg.alert_id
        orgs: list[dict[str, Any]] = []
        try:
            started = await backend.start_outreach(alert_id, msg.idempotency_key, corr)
            for org in started.get("orgs", []):
                asked = [a["volunteer_id"] for a in org.get("asked", [])]
                answers = {"available": [], "unavailable": [], "awaiting_reply": []}
                for vid in asked:  # simulated volunteer replies, recorded through B (SIMULATED)
                    answer = persona(vid)["availability"]
                    if answer in ("YES", "NO"):
                        await backend.record_availability(alert_id, vid, org["org_id"], answer == "YES", utc_now(),
                                                          f"{alert_id}:avail:{vid}", corr)
                        answers["available" if answer == "YES" else "unavailable"].append(vid)
                    else:
                        answers["awaiting_reply"].append(vid)
                orgs.append({"org_id": org["org_id"], "name": org.get("name"), "region_id": org.get("region_id"),
                             "distance_km": org.get("distance_km"), "asked": asked,
                             "skipped": org.get("skipped", []), **answers})
        except (BackendError, OSError) as err:
            ctx.logger.warning(f"[{corr}] outreach failed for {alert_id}: {_error(err)['code']}")
            orgs.append({"org_id": "*", "error": _error(err)})
        ctx.logger.info(f"[{corr}] outreach {alert_id}: {len(orgs)} orgs, "
                        f"{sum(len(o.get('asked', [])) for o in orgs)} volunteers asked")
        await ctx.send(sender, OutreachResult(correlation_id=corr, created_at=utc_now(), alert_id=alert_id, orgs=orgs))

    @proto.on_message(AcceptRequest, replies=AcceptResponse)
    async def on_accept(ctx: Context, sender: str, msg: AcceptRequest):
        if msg.idempotency_key in decisions:  # duplicate/delayed request: same answer
            await ctx.send(sender, decisions[msg.idempotency_key])
            return
        if msg.role == "VOLUNTEER":
            decision = "DECLINED" if declines(msg.volunteer_id or "") else "ACCEPTED"
        else:
            decision = "ACCEPTED" if PERSONAS["shelter_sites"].get(msg.site_id or "") == "ACCEPT" else "DECLINED"
        try:
            result = await get_backend().accept_v2(msg.assignment_id, msg.org_id, decision, msg.idempotency_key,
                                                   msg.correlation_id, volunteer_id=msg.volunteer_id,
                                                   site_id=msg.site_id)
            # Pickup point / phone are for the volunteer only, never sent back to Doorstep.
            result.pop("pickup_details", None)
            if decision == "ACCEPTED":
                accepted[(msg.assignment_id, msg.role)] = {"org_id": msg.org_id, "volunteer_id": msg.volunteer_id,
                                                           "site_id": msg.site_id}
            backend_view, error = result, None
        except (BackendError, OSError) as err:
            decision, backend_view, error = "ERROR", {}, _error(err)
        reply = AcceptResponse(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                               assignment_id=msg.assignment_id, org_id=msg.org_id, role=msg.role,
                               volunteer_id=msg.volunteer_id, site_id=msg.site_id, decision=decision,
                               backend=backend_view, error=error)
        if decision != "ERROR":
            decisions[msg.idempotency_key] = reply
        ctx.logger.info(f"[{msg.correlation_id}] {msg.org_id} {msg.role} {msg.assignment_id}: {decision}")
        await ctx.send(sender, reply)

    @proto.on_message(ReportRequest, replies={PickupReport, ArrivalReport, ReportUnavailable})
    async def on_report(ctx: Context, sender: str, msg: ReportRequest):
        base = dict(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                    assignment_id=msg.assignment_id)
        volunteer = accepted.get((msg.assignment_id, "VOLUNTEER"))
        shelter = accepted.get((msg.assignment_id, "SHELTER"))
        if msg.kind == "PICKUP" and volunteer:
            reply = PickupReport(**base, org_id=volunteer["org_id"], volunteer_id=volunteer["volunteer_id"],
                                 report_id=f"pickup_rep_{uuid4().hex[:8]}", code_verified=True)
        elif msg.kind == "ARRIVAL" and shelter:
            reply = ArrivalReport(**base, shelter_org_id=shelter["org_id"], site_id=shelter["site_id"],
                                  report_id=f"arrival_rep_{uuid4().hex[:8]}")
        else:
            reply = ReportUnavailable(**base, reason=f"no accepted {'volunteer' if msg.kind == 'PICKUP' else 'shelter'} "
                                                     "for this assignment")
        await ctx.send(sender, reply)

    @proto.on_message(ReferralRequest, replies=ReferralResponse)
    async def on_referral(ctx: Context, sender: str, msg: ReferralRequest):
        decision = "ACCEPTED" if PERSONAS["recovery_referrals"] == "ACCEPT" else "DECLINED"
        try:
            result = await get_backend().respond_recovery(msg.referral_id, msg.org_id, decision,
                                                          f"{msg.referral_id}:respond:{decision.lower()}",
                                                          msg.correlation_id)
            reply = ReferralResponse(correlation_id=msg.correlation_id, created_at=utc_now(),
                                     referral_id=msg.referral_id, org_id=msg.org_id, decision=decision,
                                     status=result.get("status", "UNKNOWN"), backend=result)
        except (BackendError, OSError) as err:
            reply = ReferralResponse(correlation_id=msg.correlation_id, created_at=utc_now(),
                                     referral_id=msg.referral_id, org_id=msg.org_id, decision="ERROR",
                                     status="UNRESOLVED", backend=_error(err))
        await ctx.send(sender, reply)

    return proto


def main() -> None:
    agent = build_agent("doorstep_volunteer_network", seed_for("NETWORK_SEED"), role_port("NETWORK"),
                        "volunteer_network.md",
                        "DOORSTEP DEMO: reaches the volunteers of the partner organizations nearest an evacuation "
                        "zone (simulated), forwards their answers, and reports pickup and arrival.")
    agent.include(build_network_protocol(lambda: DoorstepBackendV2()), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

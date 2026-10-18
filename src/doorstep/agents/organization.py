"""Organization agent - one instance per (fictional) partner organization. DOORSTEP DEMO.

Acts for ONE org: reads only that org's volunteers through B's org-scoped API
(`X-Org-Agent`), runs volunteer outreach for an alert, forwards its volunteer's or
shelter's decision on an assignment, reports pickup/arrival, and answers recovery
referrals. Volunteer answers are simulated from `fixtures/volunteer_personas.json`.
Never reads another org's data or the residents DB; never forwards pickup points.

Run:  python -m doorstep.agents.organization eastside_rides_demo
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import DEMO_ORGS, ORG_PORT_BASE, build_agent, org_env_key, seed_for
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


def build_org_protocol(org_id: str, get_backend: Callable[[], DoorstepBackendV2]) -> Protocol:
    proto = Protocol(name="doorstep_organization", version="2.0")
    accepted: dict[str, dict[str, Any]] = {}  # assignment_id -> what this org accepted (local only)
    decisions: dict[str, AcceptResponse] = {}  # idempotency_key -> reply

    @proto.on_message(OutreachRequest, replies=OutreachResult)
    async def on_outreach(ctx: Context, sender: str, msg: OutreachRequest):
        backend, corr = get_backend(), msg.correlation_id
        asked, skipped = [], []
        try:
            started = await backend.start_outreach(org_id, msg.alert_id, msg.idempotency_key, corr)
            asked = [a["volunteer_id"] for a in started.get("asked", [])]
            skipped = started.get("skipped", [])
            for vid in asked:  # simulated volunteer replies, recorded through B (SIMULATED)
                answer = persona(vid)["availability"]
                if answer in ("YES", "NO"):
                    await backend.record_availability(org_id, vid, msg.alert_id, answer == "YES", utc_now(),
                                                      f"{msg.alert_id}:avail:{vid}", corr)
            vols = (await backend.org_volunteers(org_id, corr, alert_id=msg.alert_id))["volunteers"]
        except (BackendError, OSError) as err:
            ctx.logger.warning(f"[{corr}] outreach failed for {org_id}: {_error(err)['code']}")
            vols, skipped = [], skipped + [{"volunteer_id": "*", "reason": _error(err)["code"]}]
        state = {v["volunteer_id"]: v["availability"]["state"] for v in vols if v["volunteer_id"] in asked}
        ctx.logger.info(f"[{corr}] outreach {org_id}/{msg.alert_id}: asked {len(asked)}")
        await ctx.send(sender, OutreachResult(
            correlation_id=corr, created_at=utc_now(), org_id=org_id, alert_id=msg.alert_id, asked=asked,
            skipped=skipped, available=[v for v, s in state.items() if s == "AVAILABLE"],
            unavailable=[v for v, s in state.items() if s == "UNAVAILABLE"],
            awaiting_reply=[v for v, s in state.items() if s not in ("AVAILABLE", "UNAVAILABLE")]))

    @proto.on_message(AcceptRequest, replies=AcceptResponse)
    async def on_accept(ctx: Context, sender: str, msg: AcceptRequest):
        if msg.idempotency_key in decisions:  # duplicate/delayed request: same answer
            await ctx.send(sender, decisions[msg.idempotency_key])
            return
        if msg.org_id != org_id:
            decision, backend_view, error = "ERROR", {}, {"code": "WRONG_ORG", "detail": "not this org"}
        else:
            if msg.role == "VOLUNTEER":
                decision = "DECLINED" if declines(msg.volunteer_id or "") else "ACCEPTED"
            else:
                decision = "ACCEPTED" if PERSONAS["shelter_sites"].get(msg.site_id or "") == "ACCEPT" else "DECLINED"
            try:
                result = await get_backend().accept_v2(msg.assignment_id, org_id, decision, msg.idempotency_key,
                                                       msg.correlation_id, volunteer_id=msg.volunteer_id,
                                                       site_id=msg.site_id)
                # Pickup point / phone go to this org's volunteer only, never back to Doorstep.
                pickup = result.pop("pickup_details", None)
                if decision == "ACCEPTED":
                    accepted[msg.assignment_id] = {"role": msg.role, "volunteer_id": msg.volunteer_id,
                                                   "site_id": msg.site_id, "has_pickup_details": bool(pickup)}
                backend_view, error = result, None
            except (BackendError, OSError) as err:
                decision, backend_view, error = "ERROR", {}, _error(err)
        reply = AcceptResponse(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                               assignment_id=msg.assignment_id, org_id=org_id, role=msg.role,
                               volunteer_id=msg.volunteer_id, site_id=msg.site_id, decision=decision,
                               backend=backend_view, error=error)
        if decision != "ERROR":
            decisions[msg.idempotency_key] = reply
        ctx.logger.info(f"[{msg.correlation_id}] {org_id} {msg.role} {msg.assignment_id}: {decision}")
        await ctx.send(sender, reply)

    @proto.on_message(ReportRequest, replies={PickupReport, ArrivalReport, ReportUnavailable})
    async def on_report(ctx: Context, sender: str, msg: ReportRequest):
        mine = accepted.get(msg.assignment_id)
        base = dict(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                    assignment_id=msg.assignment_id)
        if msg.kind == "PICKUP" and mine and mine["role"] == "VOLUNTEER":
            reply = PickupReport(**base, org_id=org_id, volunteer_id=mine["volunteer_id"],
                                 report_id=f"pickup_rep_{uuid4().hex[:8]}", code_verified=True)
        elif msg.kind == "ARRIVAL" and mine and mine["role"] == "SHELTER":
            reply = ArrivalReport(**base, shelter_org_id=org_id, site_id=mine["site_id"],
                                  report_id=f"arrival_rep_{uuid4().hex[:8]}")
        else:
            reply = ReportUnavailable(**base, reason=f"{org_id} has no accepted {msg.kind.lower()} role here")
        await ctx.send(sender, reply)

    @proto.on_message(ReferralRequest, replies=ReferralResponse)
    async def on_referral(ctx: Context, sender: str, msg: ReferralRequest):
        decision = "ACCEPTED" if PERSONAS["recovery_referrals"] == "ACCEPT" else "DECLINED"
        try:
            result = await get_backend().respond_recovery(msg.referral_id, org_id, decision,
                                                          f"{msg.referral_id}:respond:{decision.lower()}",
                                                          msg.correlation_id)
            reply = ReferralResponse(correlation_id=msg.correlation_id, created_at=utc_now(),
                                     referral_id=msg.referral_id, org_id=org_id, decision=decision,
                                     status=result.get("status", "UNKNOWN"), backend=result)
        except (BackendError, OSError) as err:
            reply = ReferralResponse(correlation_id=msg.correlation_id, created_at=utc_now(),
                                     referral_id=msg.referral_id, org_id=org_id, decision="ERROR",
                                     status="UNRESOLVED", backend=_error(err))
        await ctx.send(sender, reply)

    return proto


def get_backend() -> DoorstepBackendV2:
    return DoorstepBackendV2()


def main(org_id: str) -> None:
    if org_id not in DEMO_ORGS:
        raise SystemExit(f"Unknown demo org {org_id}. Choose one of {DEMO_ORGS}.")
    # Agentverse agent names are max 32 characters.
    agent = build_agent(f"doorstep_{org_id}", seed_for(f"ORG_SEED_{org_env_key(org_id)}"),
                        int(os.getenv(f"ORG_PORT_{org_env_key(org_id)}", str(ORG_PORT_BASE + DEMO_ORGS.index(org_id)))),
                        "organization.md",
                        f"DOORSTEP DEMO: simulated partner organization agent for {org_id} (fictional).")
    agent.include(build_org_protocol(org_id, lambda: get_backend()), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "eastside_rides_demo")

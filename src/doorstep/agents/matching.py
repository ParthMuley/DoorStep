"""Matching agent - DOORSTEP DEMO.

An independent matching service: answers `MatchRequest` by calling B's deterministic
`POST /matches/propose` and returning the explained result (eligible/rejected volunteers
with reason codes, shelter, proposed match). It never ranks people or decides
eligibility itself, and it never uses an LLM.

Drive-time ranking (rev 6, contract v2.2 §5.6): before proposing, it asks B for the
eligible volunteers (`create_proposal: false`), asks the Route agent for real drive times
to the pickup for the top DRIVE_TIME_CANDIDATES (default 3), and proposes with
`drive_minutes`, so B ranks by road time instead of straight-line distance. Any failure
falls back to B's distance ranking. DRIVE_TIME_RANKING=false turns it off.

Run:  python -m doorstep.agents.matching
"""

from typing import Callable

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import build_agent, role_port, seed_for
import os

from doorstep.agents.base import address_for
from doorstep.integrations.fetch_messages import (
    DriveTimeRequest,
    DriveTimeResponse,
    MatchRequest,
    MatchResult,
    utc_now,
)
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()


def build_matching_protocol(get_backend: Callable[[], DoorstepBackendV2],
                            route_address: Callable[[], str] = lambda: address_for("ROUTE")) -> Protocol:
    proto = Protocol(name="doorstep_matching", version="2.1")

    async def drive_minutes(ctx: Context, msg: MatchRequest) -> dict[str, float]:
        """Road minutes for B's top eligible volunteers, via the Route agent; {} = distance ranking."""
        if os.getenv("DRIVE_TIME_RANKING", "true").lower() == "false" or not msg.create_proposal \
                or msg.select_volunteer_id:
            return {}
        try:
            preview = await get_backend().propose_match(msg.case_id, False, f"{msg.idempotency_key}:preview",
                                                        msg.correlation_id)
        except (BackendError, OSError):
            return {}
        top = [e["volunteer_id"] for e in preview.get("evaluation", {}).get("volunteers", {}).get("eligible", [])]
        top = top[:int(os.getenv("DRIVE_TIME_CANDIDATES", "3"))]
        if len(top) < 2:  # nothing to re-rank
            return {}
        reply, _ = await ctx.send_and_receive(route_address(), DriveTimeRequest(
            correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id, volunteer_ids=top,
            idempotency_key=f"{msg.idempotency_key}:drive"), response_type=DriveTimeResponse, timeout=40)
        return dict(reply.drive_minutes) if isinstance(reply, DriveTimeResponse) else {}

    @proto.on_message(MatchRequest, replies=MatchResult)
    async def on_match(ctx: Context, sender: str, msg: MatchRequest):
        try:
            minutes = await drive_minutes(ctx, msg)
            result = await get_backend().propose_match(
                msg.case_id, msg.create_proposal, msg.idempotency_key, msg.correlation_id,
                select_volunteer_id=msg.select_volunteer_id, select_site_id=msg.select_site_id,
                drive_minutes=minutes)
            reply = MatchResult(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                                ok=True, status_code=201 if result.get("match") else 200, result=result)
        except BackendError as err:
            reply = MatchResult(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                                ok=False, status_code=err.status_code, result={},
                                error={"code": err.code, "detail": err.detail, "reasons": err.reasons})
        except OSError as err:
            reply = MatchResult(correlation_id=msg.correlation_id, created_at=utc_now(), case_id=msg.case_id,
                                ok=False, status_code=503, result={},
                                error={"code": "BACKEND_UNREACHABLE", "detail": type(err).__name__})
        ctx.logger.info(f"[{msg.correlation_id}] match {msg.case_id}: ok={reply.ok} "
                        f"match={'yes' if reply.result.get('match') else 'no'} "
                        f"ranking={reply.result.get('ranking', '-')}")
        await ctx.send(sender, reply)

    return proto


def main() -> None:
    agent = build_agent("doorstep_matching", seed_for("MATCHING_SEED"), role_port("MATCHING"), "matching.md",
                        "matching",
                        "DOORSTEP DEMO: deterministic matching of residents to available, capable volunteers "
                        "and accessible shelters, with explained reason codes.")
    agent.include(build_matching_protocol(lambda: DoorstepBackendV2()), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

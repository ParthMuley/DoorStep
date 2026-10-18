"""Post-Calamity agent - DOORSTEP DEMO.

After arrival and with the resident's consent, asks B to match recovery organizations
per help type (temporary housing, insurance guidance, supplies...), then sends each
referral (only B's consent-scoped `shared_payload`) to the Volunteer Network agent, which
answers for the partner organizations, and collects the answers.
Never files claims or applications and never promises housing (`housing_secured` comes
from B and is false unless a completed, evidenced referral says otherwise).

Run:  python -m doorstep.agents.post_calamity
"""

from typing import Any, Callable

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import address_for, build_agent, role_port, seed_for
from doorstep.integrations.fetch_messages import (
    RecoveryRequest,
    RecoveryResponse,
    ReferralRequest,
    ReferralResponse,
    utc_now,
)
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()

REFERRAL_TIMEOUT_SECONDS = 20


def build_post_calamity_protocol(get_backend: Callable[[], DoorstepBackendV2],
                                  network_address: Callable[[], str] = lambda: address_for("NETWORK")) -> Protocol:
    proto = Protocol(name="doorstep_post_calamity", version="2.0")

    async def refer(ctx: Context, case_id: str, ref: dict[str, Any], corr: str) -> dict[str, Any]:
        reply, status = await ctx.send_and_receive(
            network_address(),
            ReferralRequest(correlation_id=corr, created_at=utc_now(), referral_id=ref["referral_id"],
                            case_id=case_id, help_type=ref["help_type"], org_id=ref["org_id"],
                            shared_payload=ref["shared_payload"], idempotency_key=f"{ref['referral_id']}:request"),
            response_type=ReferralResponse, timeout=REFERRAL_TIMEOUT_SECONDS)
        if reply is None:  # no answer: still REQUESTED, never assumed accepted
            return {**ref, "status": "REQUESTED", "agent_reply": "NO_RESPONSE"}
        return {**ref, "status": reply.status, "agent_reply": reply.decision}

    @proto.on_message(RecoveryRequest, replies=RecoveryResponse)
    async def on_recovery(ctx: Context, sender: str, msg: RecoveryRequest):
        corr = msg.correlation_id
        try:
            result = await get_backend().request_recovery(msg.case_id, msg.help_types, msg.share_recovery_needs,
                                                           msg.granted_by, msg.idempotency_key, corr)
        except (BackendError, OSError) as err:
            await ctx.send(sender, RecoveryResponse(
                correlation_id=corr, created_at=utc_now(), case_id=msg.case_id, ok=False, referrals=[],
                error={"code": getattr(err, "code", type(err).__name__),
                       "detail": getattr(err, "detail", "backend unreachable")}))
            return
        # Sequential: all referrals go to the same Volunteer Network agent, and concurrent
        # send_and_receive calls to one destination from one handler collide (uagents 0.26).
        referrals = [await refer(ctx, msg.case_id, r, corr) for r in result.get("referrals", [])]
        # Only the minimal fields go back to Doorstep; shared payloads stay on the referral side.
        summary = [{k: r.get(k) for k in ("referral_id", "help_type", "org_id", "status", "agent_reply")}
                   for r in referrals]
        ctx.logger.info(f"[{corr}] recovery {msg.case_id}: {[(r['help_type'], r['status']) for r in summary]}")
        await ctx.send(sender, RecoveryResponse(
            correlation_id=corr, created_at=utc_now(), case_id=msg.case_id, ok=True, referrals=summary,
            unmatched_help_types=result.get("unmatched_help_types", []),
            housing_secured=bool(result.get("housing_secured", False))))

    return proto


def main() -> None:
    agent = build_agent("doorstep_post_calamity", seed_for("POSTCALAMITY_SEED"), role_port("POSTCALAMITY"),
                        "post_calamity.md",
                        "DOORSTEP DEMO: consent-based referrals to fictional recovery organizations "
                        "(temporary housing, insurance guidance, supplies). Never files claims or promises housing.")
    agent.include(build_post_calamity_protocol(lambda: DoorstepBackendV2()), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

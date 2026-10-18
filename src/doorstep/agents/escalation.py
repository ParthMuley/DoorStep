"""Escalation Simulator agent - DOORSTEP DEMO.

Stands in for an authorized emergency-response service. On an `EscalationRequest` it
records a receipt in B (`ACKNOWLEDGED_REQUEST_ONLY`) and replies. An acknowledgment
means "request received" only: it never implies responders were dispatched, and
`assistance_confirmed` is always false. Never contacts real 911 or any real service.

Run:  python -m doorstep.agents.escalation
"""

from typing import Callable

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import build_agent, role_port, seed_for
from doorstep.integrations.fetch_messages import EscalationAck, EscalationRequest, utc_now
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()


def build_escalation_protocol(get_backend: Callable[[], DoorstepBackendV2]) -> Protocol:
    proto = Protocol(name="doorstep_escalation_simulator", version="2.0")

    @proto.on_message(EscalationRequest, replies=EscalationAck)
    async def on_escalation(ctx: Context, sender: str, msg: EscalationRequest):
        try:
            result = await get_backend().ack_escalation(msg.escalation_id, ctx.agent.address,
                                                        f"{msg.escalation_id}:ack", msg.correlation_id)
            status = result.get("status", "ACKNOWLEDGED_REQUEST_ONLY")
        except (BackendError, OSError) as err:
            result, status = {"error": getattr(err, "code", type(err).__name__)}, "NO_ACKNOWLEDGMENT"
        ctx.logger.info(f"[{msg.correlation_id}] escalation {msg.escalation_id}: {status}")
        await ctx.send(sender, EscalationAck(correlation_id=msg.correlation_id, created_at=utc_now(),
                                             escalation_id=msg.escalation_id, case_id=msg.case_id, status=status,
                                             assistance_confirmed=False, backend=result))

    return proto


def main() -> None:
    agent = build_agent("doorstep_escalation_simulator", seed_for("ESCALATION_SEED"), role_port("ESCALATION"),
                        "escalation.md", "escalation",
                        "DOORSTEP DEMO: simulated authorized-response service that acknowledges receipt of "
                        "escalations only. Never dispatches anyone; not connected to 911.")
    agent.include(build_escalation_protocol(lambda: DoorstepBackendV2()), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

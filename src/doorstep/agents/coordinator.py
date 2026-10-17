"""Doorstep Coordinator agent (ASI:One entry point).

DOORSTEP DEMO - synthetic simulation only. Never contacts real emergency services,
residents, or volunteers.

Step 1 (hello-world): accepts ASI:One chat messages over the Agent Chat Protocol and
replies with a labeled DEMO response. Later steps route commands into the
coordination workflow.

Run:  python -m doorstep.agents.coordinator
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

from doorstep.agents.provider_client import OfferResult, request_all_offers
from doorstep.integrations.fetch_adapter import new_correlation_id

load_dotenv()

DEMO_PREFIX = "DOORSTEP DEMO - SIMULATION ONLY."
README_PATH = Path(__file__).parent / "profiles" / "coordinator.md"

HELP_TEXT = (
    "I coordinate simulated accessible-transport and recovery support for fictional residents. "
    "Try: 'Start the simulated Zone 3 readiness check', 'Show residents who requested assistance', "
    "'Show available suitable providers', 'Approve the simulated arrangement for Maria', "
    "'Show confirmed pickup, arrival, and unresolved cases', 'Request Maria's recovery handoff'. "
    "This is not an emergency service; call 911 in a real emergency."
)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


agent = Agent(
    name="doorstep_coordinator",
    seed=_require_env("COORDINATOR_SEED"),
    port=int(os.getenv("COORDINATOR_PORT", "8101")),
    mailbox=True,
    publish_agent_details=True,
    readme_path=str(README_PATH),
    description=(
        "DOORSTEP DEMO: simulated coordinator for accessible disaster-assistance transport, "
        "destinations, and recovery referrals using fictional data."
    ),
    handle_messages_concurrently=True,
)

chat_proto = Protocol(spec=chat_protocol_spec)


def make_chat_reply(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=f"{DEMO_PREFIX} {text}")]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def extract_text(msg: ChatMessage) -> str:
    return " ".join(item.text for item in msg.content if isinstance(item, TextContent)).strip()


# Step 2 stub: consent-scoped needs for the fictional case until the coordinator reads
# them from Developer B's backend (Step 3). No names, phones, or pickup points here.
STUB_CASE = {
    "case_id": "case_maria_001",
    "zone_id": "zone_3",
    "transport_requirements": {"wheelchair_accessible_vehicle": True, "transfer_assistance": True,
                               "portable_oxygen_equipment": False, "pet_count": 1},
    "destination_requirements": {"destination_accessibility": ["step_free_entry"], "pet_count": 1},
}


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_offers(transport: OfferResult, destination: OfferResult) -> str:
    lines = [f"Provider agents queried over Fetch.ai for {STUB_CASE['case_id']} (synthetic)."]
    if transport.response is None:
        lines.append(f"Transport agent: no response ({transport.status_detail}).")
    else:
        lines.append(f"Transport agent returned {len(transport.response.offers)} vehicles:")
        for o in transport.response.offers:
            lines.append(
                f"- {o['provider_id']} {o['vehicle_id']}: wheelchair {_yes_no(o['wheelchair_accessible'])}, "
                f"transfer help {_yes_no(o['transfer_assistance'])}, pets {_yes_no(o['pets_allowed'])}, "
                f"partner-approved {_yes_no(o['approved_by_partner'])}"
            )
    if destination.response is None:
        lines.append(f"Destination agent: no response ({destination.status_detail}).")
    else:
        lines.append(f"Destination agent returned {len(destination.response.offers)} sites:")
        for o in destination.response.offers:
            lines.append(
                f"- {o['destination_id']}: step-free {_yes_no(o['step_free_entry'])}, "
                f"pets {_yes_no(o['pets_allowed'])}, beds {o['beds_available']}"
            )
    lines.append("Eligibility is not decided yet: deterministic matching runs next. Nothing is assigned.")
    return "\n".join(lines)


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )
    text = extract_text(msg)
    correlation_id = new_correlation_id()
    # Never log resident free text; length is enough to debug delivery.
    ctx.logger.info(f"[{correlation_id}] chat message from {sender[:16]}... ({len(text)} chars)")

    lowered = text.lower()
    if "provider" in lowered or "offer" in lowered:
        transport, destination = await request_all_offers(
            ctx,
            STUB_CASE["case_id"],
            STUB_CASE["zone_id"],
            STUB_CASE["transport_requirements"],
            STUB_CASE["destination_requirements"],
            correlation_id,
        )
        await ctx.send(sender, make_chat_reply(format_offers(transport, destination)))
        return

    await ctx.send(sender, make_chat_reply(f"Coordinator online. {HELP_TEXT}"))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()

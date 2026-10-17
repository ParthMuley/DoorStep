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


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )
    text = extract_text(msg)
    # Never log resident free text; length is enough to debug delivery.
    ctx.logger.info(f"chat message from {sender[:16]}... ({len(text)} chars)")
    await ctx.send(sender, make_chat_reply(f"Coordinator online. {HELP_TEXT}"))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()

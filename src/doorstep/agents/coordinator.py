"""Doorstep Coordinator agent (ASI:One entry point).

DOORSTEP DEMO - synthetic simulation only. Never contacts real emergency services,
residents, or volunteers.

Step 1 (hello-world): accepts ASI:One chat messages over the Agent Chat Protocol and
replies with a labeled DEMO response. Later steps route commands into the
coordination workflow.

Run:  python -m doorstep.agents.coordinator
"""

import asyncio
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

from doorstep.agents import coordinator_actions as actions
from doorstep.integrations.agentverse_setup import enable_auto_mailbox
from doorstep.integrations.asi_cards import Card, parse_card_selection
from doorstep.integrations.asi_one_client import Intent, IntentClient, intent_enabled, keyword_intent
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


PORT = int(os.getenv("COORDINATOR_PORT", "8101"))

agent = Agent(
    name="doorstep_coordinator",
    seed=_require_env("COORDINATOR_SEED"),
    port=PORT,
    mailbox=True,
    publish_agent_details=True,
    readme_path=str(README_PATH),
    description=(
        "DOORSTEP DEMO: simulated coordinator for accessible disaster-assistance transport, "
        "destinations, and recovery referrals using fictional data."
    ),
    handle_messages_concurrently=True,
)
enable_auto_mailbox(agent, PORT)

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
    correlation_id = new_correlation_id()
    # Never log resident free text; length is enough to debug delivery.
    ctx.logger.info(f"[{correlation_id}] chat message from {sender[:16]}... ({len(text)} chars)")

    try:
        reply = await route(ctx, text, correlation_id, sender)
    except Exception as err:  # never leave the ASI:One user without an answer
        ctx.logger.exception(f"[{correlation_id}] coordinator error: {type(err).__name__}")
        reply = (f"Something went wrong on my side ({type(err).__name__}, ref {correlation_id}). "
                 "Nothing was changed; no assistance is confirmed.")
    await ctx.send(sender, reply.to_message() if isinstance(reply, Card) else make_chat_reply(reply))


PUSH_TEST_DELAY_SECONDS = 15


async def _delayed_push(ctx: Context, sender: str, correlation_id: str) -> None:
    """Spike: can the agent message an ASI:One user without a new user message? (V2 plan
    assumes no push; alerts would be much better if this shows up in the chat.)"""
    await asyncio.sleep(PUSH_TEST_DELAY_SECONDS)
    ctx.logger.info(f"[{correlation_id}] sending unsolicited push test")
    await ctx.send(sender, make_chat_reply(f"Push test follow-up (ref {correlation_id}). If you can read this "
                                           "without sending another message, unsolicited updates work."))


def get_intent_client() -> IntentClient | None:
    """Factory so tests can inject a fake model. None when LLM intent is disabled."""
    return IntentClient() if intent_enabled() else None


async def choose_intent(text: str, correlation_id: str) -> Intent:
    """Card click (selection JSON) -> ASI:One tool choice -> deterministic keywords."""
    selection = parse_card_selection(text)
    if selection and selection.get("action"):
        return selection_intent(selection)
    client = get_intent_client()
    if client is not None:
        intent = await client.choose(text, correlation_id)
        if intent is not None:
            # The model must not guess who a request is about: a resident chosen by the
            # model counts only if the user actually named them.
            resident = intent.args.get("resident")
            if resident and resident not in text.lower():
                return Intent("clarify_resident", {"tool": intent.name}, source="ASI_ONE")
            return intent
    return keyword_intent(text)


CARD_ACTIONS = {"case_status": "case_status", "show_matches": "show_suitable_volunteers"}


def selection_intent(selection: dict) -> Intent:
    name = CARD_ACTIONS.get(selection["action"], f"unsupported:{selection['action']}")
    case_id = selection.get("case_id") or actions.DEFAULT_CASE
    return Intent(name, {"case_id": case_id}, source="CARD")


def case_of(intent: Intent) -> str:
    if "case_id" in intent.args:
        return intent.args["case_id"]
    return actions.CASES_BY_NAME.get(intent.args.get("resident", ""), actions.DEFAULT_CASE)


async def route(ctx: Context, text: str, correlation_id: str, sender: str = "") -> str | Card:
    intent = await choose_intent(text, correlation_id)
    ctx.logger.info(f"[{correlation_id}] intent {intent.name} via {intent.source}")
    return await run_intent(ctx, intent, correlation_id, sender)


async def run_intent(ctx: Context, intent: Intent, correlation_id: str, sender: str) -> str | Card:
    # The reply always comes from the actions (B's data), never from model text.
    if intent.name == "start_readiness_check":
        return await actions.start_readiness_check(correlation_id)
    if intent.name == "case_status":
        return await actions.case_status(case_of(intent), correlation_id)
    if intent.name == "show_suitable_volunteers":
        return await actions.show_suitable_providers(ctx, case_of(intent), correlation_id)
    if intent.name == "test_push":
        asyncio.create_task(_delayed_push(ctx, sender, correlation_id))
        return f"Push test: I will send an unsolicited follow-up in {PUSH_TEST_DELAY_SECONDS} s (ref {correlation_id})."
    if intent.name == "clarify_resident":
        return ("Which resident do you mean? Please name them (for example 'Maria' or 'David'). "
                "I don't guess who a request is about. Nothing was changed.")
    if intent.name.startswith("unsupported:"):
        return f"The '{intent.name.split(':', 1)[1]}' action is not available yet in this demo build. Nothing was changed."
    return f"Coordinator online. {HELP_TEXT}"


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()

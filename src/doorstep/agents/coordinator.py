"""Doorstep agent (Coordinator + Doorstep Help) - the ASI:One entry point.

DOORSTEP DEMO - synthetic simulation only. Never contacts real emergency services,
residents, or volunteers.

Talks to the user over the Agent Chat Protocol (text + ASI:One Interactive Cards),
chooses what to do via card clicks, ASI:One tool calling or deterministic keywords, and
runs the V2 journey (`journey.py`) across the other Doorstep agents and B's backend.
Alerts from the Calamity Checker are pushed to the ASI:One users talking to it.

Run:  python -m doorstep.agents.coordinator
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from doorstep.agents import coordinator_actions as actions
from doorstep.agents.base import address_for
from doorstep.agents.journey import Journey
from doorstep.integrations.agentverse_setup import enable_auto_mailbox
from doorstep.integrations.asi_cards import DEMO_PREFIX, Card, parse_card_selection, text_message
from doorstep.integrations.asi_one_client import Intent, IntentClient, intent_enabled, keyword_intent
from doorstep.integrations.fetch_adapter import new_correlation_id
from doorstep.integrations.fetch_messages import AlertNotification
from doorstep.workflows.backend_v2 import DoorstepBackendV2

load_dotenv()

README_PATH = Path(__file__).parent / "profiles" / "coordinator.md"

HELP_TEXT = (
    "I coordinate simulated accessible transport, shelter and recovery help for fictional residents "
    "(Maria, David). Try, in order: 'Start the simulated Zone 3 readiness check', 'Simulate Maria's reply', "
    "'Find a match for Maria', then use the card buttons (approve, pickup, arrival, further help). "
    "'Find a match for David' shows the order-zone safety case. 'Status for Maria' anytime. "
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
        "shelter, and recovery referrals using fictional data."
    ),
    handle_messages_concurrently=True,
)
enable_auto_mailbox(agent, PORT)

chat_proto = Protocol(spec=chat_protocol_spec)
journey_proto = Protocol(name="doorstep_journey", version="2.0")


def get_v2_backend() -> DoorstepBackendV2:
    """Factory so tests can swap in an in-process backend."""
    return DoorstepBackendV2()


journey = Journey(lambda: get_v2_backend(), lambda role: address_for(role))


def make_chat_reply(text: str) -> ChatMessage:
    return text_message(text)


def extract_text(msg: ChatMessage) -> str:
    return " ".join(item.text for item in msg.content if isinstance(item, TextContent)).strip()


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id),
    )
    journey.subscribers.add(sender)  # alerts and journey updates are pushed to people talking to us
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
    for part in reply if isinstance(reply, list) else [reply]:
        await ctx.send(sender, part.to_message() if isinstance(part, Card) else make_chat_reply(part))


@journey_proto.on_message(AlertNotification)
async def handle_alert(ctx: Context, sender: str, msg: AlertNotification):
    ctx.logger.info(f"[{msg.correlation_id}] alert notification: {len(msg.new_alerts)} new, "
                    f"{len(msg.outreach_orgs)} orgs to contact")
    await journey.on_alert(ctx, msg)


PUSH_TEST_DELAY_SECONDS = 15


async def _delayed_push(ctx: Context, sender: str, correlation_id: str) -> None:
    """Checks that agent-initiated messages reach ASI:One (confirmed live 2026-10-17)."""
    await asyncio.sleep(PUSH_TEST_DELAY_SECONDS)
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


# Card button selection.action -> intent name
CARD_ACTIONS = {"case_status": "case_status", "show_matches": "find_match", "approve": "approve",
                "reject": "reject", "confirm_pickup": "confirm_pickup", "confirm_arrival": "confirm_arrival",
                "recovery_consent": "request_recovery", "recovery_decline": "decline_recovery",
                "escalate": "escalate"}


def selection_intent(selection: dict) -> Intent:
    name = CARD_ACTIONS.get(selection["action"], f"unsupported:{selection['action']}")
    case_id = selection.get("case_id") or actions.DEFAULT_CASE
    return Intent(name, {"case_id": case_id}, source="CARD")


def case_of(intent: Intent) -> str:
    if "case_id" in intent.args:
        return intent.args["case_id"]
    return actions.CASES_BY_NAME.get(intent.args.get("resident", ""), actions.DEFAULT_CASE)


async def route(ctx: Context, text: str, correlation_id: str, sender: str = ""):
    intent = await choose_intent(text, correlation_id)
    ctx.logger.info(f"[{correlation_id}] intent {intent.name} via {intent.source}")
    return await run_intent(ctx, intent, correlation_id, sender)


async def run_intent(ctx: Context, intent: Intent, corr: str, sender: str):
    # Replies always come from the journey/actions (B's data and agents' replies), never model text.
    name, case_id = intent.name, case_of(intent)
    if name == "start_readiness_check":
        return await journey.start_check(ctx, sender, corr)
    if name == "simulate_resident_reply":
        return await journey.simulate_reply(case_id, corr)
    if name == "find_match":
        return await journey.find_match(ctx, case_id, corr)
    if name == "approve":
        return await journey.approve(ctx, case_id, corr)
    if name == "reject":
        return "Not approved. No request was sent to the volunteer or the shelter."
    if name == "confirm_pickup":
        return await journey.confirm_pickup(ctx, case_id, corr)
    if name == "confirm_arrival":
        return await journey.confirm_arrival(ctx, case_id, corr)
    if name == "request_recovery":
        return await journey.recovery(ctx, case_id, True, corr)
    if name == "decline_recovery":
        return await journey.recovery(ctx, case_id, False, corr)
    if name == "escalate":
        return await journey.escalate(ctx, case_id, corr)
    if name == "case_status":
        if journey.case(case_id).steps["PROVIDER_ACCEPTED"]:
            return journey.journey_card(case_id, None, note="Journey status.")
        return await actions.case_status(case_id, corr)
    if name == "test_push":
        asyncio.create_task(_delayed_push(ctx, sender, corr))
        return f"Push test: I will send an unsolicited follow-up in {PUSH_TEST_DELAY_SECONDS} s (ref {corr})."
    if name == "clarify_resident":
        return ("Which resident do you mean? Please name them (for example 'Maria' or 'David'). "
                "I don't guess who a request is about. Nothing was changed.")
    if name.startswith("unsupported:"):
        return f"The '{name.split(':', 1)[1]}' action is not available yet in this demo build. Nothing was changed."
    return f"Coordinator online. {HELP_TEXT}"


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)
agent.include(journey_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()

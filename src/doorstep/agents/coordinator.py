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
from doorstep.agents.base import address_for, register_with_backend
from doorstep.agents.journey import Journey
from doorstep.integrations.agentverse_setup import enable_auto_mailbox
from doorstep.agents.links import MENTION, Link, link_code_from_text, link_from_backend
from doorstep.agents.registration import Registration, choice_card
from doorstep.integrations.asi_cards import (
    DEMO_PREFIX,
    Card,
    link_card,
    parse_card_selection,
    recovery_consent_card,
    text_message,
)
from doorstep.integrations.asi_one_client import Intent, IntentClient, intent_enabled, keyword_intent
from doorstep.integrations.fetch_adapter import new_correlation_id
from doorstep.integrations.fetch_messages import AlertNotification, ClosureNotification
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()

README_PATH = Path(__file__).parent / "profiles" / "coordinator.md"

HELP_TEXT = (
    "I coordinate simulated accessible transport, shelter and recovery help for fictional residents "
    "(Maria, David). Try, in order: 'Start the simulated Zone 3 readiness check', 'Simulate Maria's reply', "
    "'Find a match for Maria', then use the card buttons (approve, pickup, arrival, further help). "
    "'Find a match for David' shows the order-zone safety case. 'Road conditions' and 'Status for Maria' anytime. "
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
register_with_backend(agent, "doorstep")

chat_proto = Protocol(spec=chat_protocol_spec)
journey_proto = Protocol(name="doorstep_journey", version="2.0")


def get_v2_backend() -> DoorstepBackendV2:
    """Factory so tests can swap in an in-process backend."""
    return DoorstepBackendV2()


journey = Journey(lambda: get_v2_backend(), lambda role: address_for(role))
registration = Registration(lambda: get_v2_backend())


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
    journey.outbox.remember(ctx, sender)  # pushes to this person go out on this chat's session
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
    # Replies share the person's outbox with pushes, so one burst = one ASI:One message.
    await journey.send_to(ctx, sender, *(reply if isinstance(reply, list) else [reply]))


@journey_proto.on_message(AlertNotification)
async def handle_alert(ctx: Context, sender: str, msg: AlertNotification):
    ctx.logger.info(f"[{msg.correlation_id}] alert notification: {len(msg.new_alerts)} new, "
                    f"{len(msg.outreach_orgs)} orgs to contact")
    await journey.on_alert(ctx, msg)


@journey_proto.on_message(ClosureNotification)
async def handle_closures(ctx: Context, sender: str, msg: ClosureNotification):
    ctx.logger.info(f"[{msg.correlation_id}] closure notification: {len(msg.new_records)} new records")
    await journey.on_closures(ctx, msg)


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


def require_link() -> bool:
    """Rev 4: only linked accounts act. REQUIRE_LINK=false keeps the open demo mode
    (anyone acts as coordinator) for automated tests and quick local checks."""
    return os.getenv("REQUIRE_LINK", "true").lower() == "true"


RESIDENT_HELP = ("You're linked as a resident (synthetic). Use the buttons on your check-in cards, or reply "
                 "1 NEED HELP / 2 HAVE A PLAN / 3 ALREADY LEFT / 4 CALL ME, 'yes'/'no' to confirm needs, "
                 "'confirm pickup' once you are in the vehicle, or 'status'.")
VOLUNTEER_HELP = ("You're linked as a volunteer (synthetic). Use the buttons on your cards, or reply 'yes'/'no' "
                  "to an availability request, 'accept'/'decline' for an assignment, 'confirm pickup', or 'status'.")


async def link_account(ctx: Context, sender: str, code: str, corr: str):
    """The address is the message envelope's sender, never typed text (plan §0.5 item 1)."""
    try:
        res = await get_v2_backend().link(code, sender, corr)
        link = link_from_backend(sender, res)
    except BackendError as err:
        return link_card(f"That code didn't work ({err.code}).")
    except (OSError, ValueError):
        return "Linking is unavailable right now. Nothing was changed."
    journey.people.put(ctx, link)
    if link.role == "COORDINATOR":
        journey.subscribers.add(sender)
        return f"Linked as coordinator ({link.display_name}). {HELP_TEXT}"
    return f"Linked as {link.display_name}. " + (RESIDENT_HELP if link.role == "RESIDENT" else VOLUNTEER_HELP)


async def route(ctx: Context, text: str, correlation_id: str, sender: str = ""):
    selection = parse_card_selection(text) or {}
    code = link_code_from_text(text) or (selection.get("code") if selection.get("action") == "link" else None)
    if code:
        return await link_account(ctx, sender, str(code).strip().upper(), correlation_id)
    if MENTION.sub("", text).strip().lower() == "unlink":  # demo control: start over in this chat
        journey.subscribers.discard(sender)
        removed = journey.people.remove(ctx, sender)
        return ("This chat is no longer linked (demo). " if removed else "This chat wasn't linked. ") + (
            "You can LINK followed by your code, or register again.")
    link = journey.people.get(ctx, sender)
    if link is None:
        reg = await registration_route(ctx, sender, text, selection, correlation_id)
        if reg is not None:
            return reg
    if link is None and require_link():
        return [link_card(), choice_card()]
    if link is not None and link.role == "RESIDENT":
        return await resident_route(ctx, link, text, selection, correlation_id)
    if link is not None and link.role == "VOLUNTEER":
        return await volunteer_route(ctx, link, text, selection, correlation_id)
    journey.subscribers.add(sender)  # coordinators (and open demo mode) get operations pushes
    intent = await choose_intent(text, correlation_id)
    ctx.logger.info(f"[{correlation_id}] intent {intent.name} via {intent.source}")
    return await run_intent(ctx, intent, correlation_id, sender)


async def registration_route(ctx: Context, sender: str, text: str, sel: dict, corr: str):
    """Self-registration for unlinked chats (plan rev 5). Returns None when not a registration step."""
    action, word = sel.get("action"), MENTION.sub("", text).strip().lower()
    if action == "register_start" or word in ("register as resident", "register as volunteer"):
        role = sel.get("role") or ("VOLUNTEER" if "volunteer" in word else "RESIDENT")
        return await registration.start(role, corr)
    if action == "register_submit":
        return await registration.submit(sender, sel, corr)
    if action == "register_confirm" or (word == "confirm" and sender in registration.pending):
        link, error = await registration.confirm(sender, corr)
        if link is None:
            return error
        journey.people.put(ctx, link)
        if link.role == "RESIDENT":
            return f"Registered and linked as {link.display_name} (resident). " + RESIDENT_HELP
        return (f"Registered and linked as {link.display_name} (volunteer). Your organization must approve you "
                "before you can be matched. " + VOLUNTEER_HELP)
    return None


def _word(text: str) -> str:
    return MENTION.sub("", text).strip().lower().rstrip(".!")


async def resident_route(ctx: Context, link: Link, text: str, sel: dict, corr: str):
    """A resident acts only on their own case."""
    if sel.get("case_id") and sel["case_id"] != link.case_id:
        return "That card belongs to another case. Nothing was changed."
    action, word = sel.get("action"), _word(text)
    if action == "checkin" or word in ("1", "2", "3", "4"):
        answer = sel.get("answer") or {"1": "need_help", "2": "have_plan", "3": "already_left", "4": "call_me"}[word]
        return await journey.resident_checkin(ctx, link, answer, corr)
    if action == "confirm_needs" or word in ("yes", "si", "sí", "no"):
        return await journey.resident_confirm_needs(ctx, link, (sel.get("answer") or word) != "no", corr)
    if action == "confirm_pickup" or "pickup" in word or "picked up" in word:
        return await journey.confirm_pickup(ctx, link.case_id, corr, by=link)
    if action == "recovery_consent":
        return await journey.recovery(ctx, link.case_id, True, corr)
    if action == "recovery_decline":
        return await journey.recovery(ctx, link.case_id, False, corr)
    if action == "case_status" or "status" in word:
        if journey.case(link.case_id).steps["PROVIDER_ACCEPTED"]:
            return journey.trip_card(link.case_id, link, "Your trip so far:")
        return await actions.case_status(link.case_id, corr)
    return RESIDENT_HELP


def _volunteer_case(link: Link, accepted: bool) -> str | None:
    for case_id, j in journey.cases.items():
        record = j.accepted if accepted else j.proposal
        if record and record.get("volunteer_id") == link.volunteer_id:
            return case_id
    return None


async def volunteer_route(ctx: Context, link: Link, text: str, sel: dict, corr: str):
    """A volunteer answers availability, their own assignment and pickup."""
    action, word = sel.get("action"), _word(text)
    if action == "availability" or (not action and word in ("yes", "no")):
        if not action:
            sel = {"available": word == "yes"}
        return await journey.volunteer_availability(ctx, link, sel, corr)
    if action in ("volunteer_accept", "volunteer_decline") or word in ("accept", "decline"):
        case_id = sel.get("case_id") or _volunteer_case(link, accepted=False)
        if not case_id:
            return "There is no assignment waiting for you. Nothing was changed."
        return await journey.volunteer_decides(ctx, link, case_id, action == "volunteer_accept" or word == "accept",
                                               corr)
    if action == "confirm_pickup" or "pickup" in word:
        case_id = sel.get("case_id") or _volunteer_case(link, accepted=True)
        if not case_id:
            return "You have no accepted assignment. Nothing was changed."
        return await journey.confirm_pickup(ctx, case_id, corr, by=link)
    if action == "case_status" or "status" in word:
        case_id = _volunteer_case(link, accepted=True)
        return (journey.trip_card(case_id, link, "Your assignment so far:") if case_id
                else "You have no accepted assignment right now.")
    return VOLUNTEER_HELP


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
        resident = journey.people.resident_for_case(case_id)
        if resident:  # consent is the resident's own decision (plan §0.2)
            await journey.send_to(ctx, resident.address, recovery_consent_card(
                case_id=case_id, display_name=resident.display_name, help_types=["TEMPORARY_HOUSING",
                                                                                 "INSURANCE_GUIDANCE"]))
            return (f"Only {resident.display_name} can consent to sharing their needs. I've asked them in their "
                    "own chat; nothing is shared until they say yes.")
        return await journey.recovery(ctx, case_id, True, corr)
    if name == "decline_recovery":
        return await journey.recovery(ctx, case_id, False, corr)
    if name == "escalate":
        return await journey.escalate(ctx, case_id, corr)
    if name == "road_conditions":
        return await journey.road_conditions(corr)
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

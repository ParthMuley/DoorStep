"""End to end over Fetch.ai messaging (offline Bureau): an ASI:One user drives the whole
V2 journey through the Doorstep agent, clicking card buttons like ASI:One does.
Backend = B's real app + contract-shaped stand-ins (fake_v2_backend.py)."""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from doorstep.agents import coordinator
from doorstep.agents import coordinator_actions as actions
from doorstep.agents.calamity_checker import CalamityChecker
from doorstep.agents.escalation import build_escalation_protocol
from doorstep.agents.journey import Journey
from doorstep.agents.matching import build_matching_protocol
from doorstep.agents.news import NewsAgent
from doorstep.agents.route import RouteAgent
from doorstep.integrations.here_client import HereRouter
from doorstep.agents.post_calamity import build_post_calamity_protocol
from doorstep.agents.volunteer_network import build_network_protocol
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend, network_client
from tests.integration.test_route import GOOD, FakeHere, here_response


def chat(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=text)])


def card(msg: ChatMessage) -> dict | None:
    meta = next((c.metadata for c in msg.content if getattr(c, "type", "") == "metadata"), None)
    return json.loads(meta["card_payload"]) | {"_kind": meta["card_kind"]} if meta else None


def text(msg: ChatMessage) -> str:
    return msg.content[0].text


def primary_selection(payload: dict) -> dict:
    if payload["_kind"] == "review":
        return payload["approve_cta"]["selection"]
    return next(c for c in payload["ctas"] if c.get("primary"))["selection"]


async def test_full_v2_journey_from_asi_one(monkeypatch):
    doorstep = make_agent("doorstep")
    doorstep.include(coordinator.chat_proto)
    doorstep.include(coordinator.journey_proto)
    network, matching, escalation, post, calamity, news, route = (
        make_agent(n) for n in ("network", "matching", "escalation", "post", "calamity", "news", "route"))
    user = make_agent("asi_one_user")

    backend, _ = make_v2_backend(monkeypatch)
    net = network_client(backend)  # only the network agent holds X-Agent-Token
    network.include(build_network_protocol(lambda: net))
    matching.include(build_matching_protocol(lambda: backend))
    escalation.include(build_escalation_protocol(lambda: backend))
    post.include(build_post_calamity_protocol(lambda: backend))

    async def fetch(url):
        return True, 200, await backend._request("GET", "/demo/feeds/caloes", "corr"), None

    calamity.include(CalamityChecker(lambda: backend, fetch, coordinator_address=lambda: doorstep.address).protocol(3600))
    from doorstep.integrations.closure_extraction import ClosureExtractor
    from tests.integration.test_fetch_news import keyword_backed_model
    news.include(NewsAgent(lambda: backend, ClosureExtractor(client=keyword_backed_model(), model="m"),
                           coordinator_address=lambda: doorstep.address).protocol(3600))
    here = FakeHere(here_response(GOOD))  # HERE is mocked: no paid calls in tests
    route.include(RouteAgent(lambda: backend, HereRouter(api_key="test-key", transport=here.transport)).protocol())
    for role, a in (("MATCHING", matching), ("ESCALATION", escalation), ("POSTCALAMITY", post),
                    ("CALAMITY", calamity), ("NETWORK", network), ("NEWS", news), ("ROUTE", route)):
        monkeypatch.setenv(f"{role}_AGENT_ADDRESS", a.address)
    monkeypatch.setattr(coordinator, "get_v2_backend", lambda: backend)
    monkeypatch.setattr(coordinator, "journey", Journey(lambda: backend, coordinator.address_for))
    monkeypatch.setattr(actions, "get_backend", lambda: backend)

    inbox: asyncio.Queue[ChatMessage] = asyncio.Queue()
    seen: dict[str, list] = {}
    done = asyncio.Event()

    @user.on_message(ChatMessage)
    async def on_message(ctx: Context, sender: str, msg: ChatMessage):
        await inbox.put(msg)

    async def say(ctx: Context, message: str | dict, expect: int = 1) -> list[ChatMessage]:
        await ctx.send(doorstep.address, chat(message if isinstance(message, str) else json.dumps(message)))
        return [await asyncio.wait_for(inbox.get(), 20) for _ in range(expect)]

    @user.on_event("startup")
    async def converse(ctx: Context):
        try:
            # 1. Start: reply + pushed Alert, Outreach and Road-conditions cards (no further user message).
            seen["start"] = await say(ctx, "Start the simulated Zone 3 readiness check", expect=4)
            seen["roads"] = await say(ctx, "Show road conditions")
            seen["reply"] = await say(ctx, "Simulate Maria's reply")
            seen["match"] = await say(ctx, "Find a match for Maria")
            seen["approved"] = await say(ctx, primary_selection(card(seen["match"][0])), expect=2)
            seen["pickup"] = await say(ctx, primary_selection(card(seen["approved"][0])))
            seen["arrival"] = await say(ctx, "Confirm arrival for Maria", expect=2)
            seen["recovery"] = await say(ctx, primary_selection(card(seen["arrival"][1])))
            seen["david_reply"] = await say(ctx, "Simulate David's reply")
            seen["david"] = await say(ctx, "Find a match for David")
            seen["escalated"] = await say(ctx, primary_selection(card(seen["david"][0])))
        finally:
            done.set()

    await run_until([doorstep, user, network, matching, escalation, post, calamity, news, route], done, timeout=120)

    titles = {(card(m) or {}).get("title", text(m)) for m in seen["start"]}
    assert any("Alert detected" in t for t in titles)
    outreach = next(m for m in seen["start"] if "Volunteer outreach" in (card(m) or {}).get("title", ""))
    assert "eastside_rides_demo · la_county:" in text(outreach) and "available 1" in text(outreach)
    assert any("Road conditions" in (card(m) or {}).get("title", "") for m in seen["start"])
    roads = text(seen["roads"][0])
    assert "Ridge Ave · Official (blocks illustrative routes)" in roads
    assert "Canyon Rd · Unverified report (caution only)" in roads
    assert "No report does not mean a road is open" in roads
    assert "Needs confirmed: True" in text(seen["reply"][0])

    match = card(seen["match"][0])
    assert match["_kind"] == "review" and "volunteer_sarah" in text(seen["match"][0])
    assert "NO_WHEELCHAIR_SPACE" in text(seen["match"][0])  # closer sedan rejected, with reason

    approved = card(seen["approved"][0])
    assert "Help on the way" in approved["title"] and "estimate, not a guarantee" in text(seen["approved"][0])
    assert "SYNTHETIC: Zone 3 Sector B meeting point" not in text(seen["approved"][0])  # pickup point stays private
    route_text = text(seen["approved"][1])
    assert "Route for volunteer_sarah" in (card(seen["approved"][1]) or {}).get("title", "")
    assert "ILLUSTRATIVE_ONLY" in route_text and "ORDER_ZONE" in route_text and "OFFICIAL_CLOSURE" in route_text
    assert "unverified report on the path" in route_text and "safe" not in route_text.lower()
    assert len(here.calls) == 1

    assert "Resident status: PICKUP_CONFIRMED" in text(seen["pickup"][0])
    assert "BLUE - pickup confirmed" in text(seen["pickup"][0]) and "Arrival Confirmed: not yet" in text(seen["pickup"][0])
    assert "Resident status: ARRIVAL_CONFIRMED" in text(seen["arrival"][0])
    assert "GREEN - arrival confirmed" in text(seen["arrival"][0])
    assert card(seen["arrival"][1])["_kind"] == "review"  # consent asked before any sharing

    recovery = text(seen["recovery"][0])
    assert "Temporary Housing:" in recovery and "Insurance Guidance:" in recovery and ": ACCEPTED" in recovery
    assert "Housing secured: no" in recovery

    david = card(seen["david"][0])
    assert david["_kind"] == "detail" and "ORDER_ZONE" in text(seen["david"][0])
    assert "approve_cta" not in david
    esc = text(seen["escalated"][0])
    assert "UNRESOLVED" in esc and "ACKNOWLEDGED_REQUEST_ONLY" in esc and "receipt only" in esc

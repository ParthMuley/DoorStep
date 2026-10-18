"""Rev 4: three people on three ASI:One accounts (resident, volunteer, coordinator), each
answering in their own chat. Backend = B's real app + the /link stand-in; HERE mocked."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from doorstep.agents import coordinator
from doorstep.agents import coordinator_actions as actions
from doorstep.agents.calamity_checker import CalamityChecker
from doorstep.agents.journey import Journey
from doorstep.agents.matching import build_matching_protocol
from doorstep.agents.news import NewsAgent
from doorstep.agents.post_calamity import build_post_calamity_protocol
from doorstep.agents.route import RouteAgent
from doorstep.agents.volunteer_network import build_network_protocol
from doorstep.integrations.closure_extraction import ClosureExtractor
from doorstep.integrations.here_client import HereRouter
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend, network_client
from tests.integration.test_fetch_news import keyword_backed_model
from tests.integration.test_route import GOOD, FakeHere, here_response


def chat(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=text)])


def card(msg: ChatMessage) -> dict | None:
    meta = next((c.metadata for c in msg.content if getattr(c, "type", "") == "metadata"), None)
    return json.loads(meta["card_payload"]) | {"_kind": meta["card_kind"]} if meta else None


def text(msg: ChatMessage) -> str:
    return msg.content[0].text


def title(msg: ChatMessage) -> str:
    return (card(msg) or {}).get("title", "")


class Inbox:
    def __init__(self):
        self.messages: list[ChatMessage] = []
        self.used: set[int] = set()

    async def wait(self, pred: Callable[[ChatMessage], bool], timeout: float = 20) -> ChatMessage:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for i, m in enumerate(self.messages):
                if i not in self.used and pred(m):
                    self.used.add(i)
                    return m
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("timed out; got: " + " | ".join(title(m) or text(m)[:70] for m in self.messages))
            await asyncio.sleep(0.05)


async def test_three_linked_people_run_maria_end_to_end(monkeypatch):
    monkeypatch.setenv("REQUIRE_LINK", "true")
    backend, _ = make_v2_backend(monkeypatch)
    doorstep = make_agent("doorstep")
    doorstep.include(coordinator.chat_proto)
    doorstep.include(coordinator.journey_proto)
    network, matching, post, calamity, news, route = (
        make_agent(n) for n in ("network", "matching", "post", "calamity", "news", "route"))
    net = network_client(backend)
    network.include(build_network_protocol(lambda: net))
    matching.include(build_matching_protocol(lambda: backend))
    post.include(build_post_calamity_protocol(lambda: backend, network_address=lambda: network.address))
    here = FakeHere(here_response(GOOD))
    route.include(RouteAgent(lambda: backend, HereRouter(api_key="test-key", transport=here.transport)).protocol())

    async def fetch(url):
        return True, 200, await backend._request("GET", "/demo/feeds/caloes", "corr"), None

    calamity.include(CalamityChecker(lambda: backend, fetch,
                                     coordinator_address=lambda: doorstep.address).protocol(3600))
    news.include(NewsAgent(lambda: backend, ClosureExtractor(client=keyword_backed_model(), model="m"),
                           coordinator_address=lambda: doorstep.address).protocol(3600))
    for role, a in (("MATCHING", matching), ("POSTCALAMITY", post), ("CALAMITY", calamity), ("NETWORK", network),
                    ("NEWS", news), ("ROUTE", route)):
        monkeypatch.setenv(f"{role}_AGENT_ADDRESS", a.address)
    monkeypatch.setattr(coordinator, "get_v2_backend", lambda: backend)
    monkeypatch.setattr(coordinator, "journey", Journey(lambda: backend, coordinator.address_for))
    monkeypatch.setattr(actions, "get_backend", lambda: backend)

    people = {n: make_agent(n) for n in ("resident", "volunteer", "coord", "stranger")}
    inbox = {n: Inbox() for n in people}
    ctxs: dict[str, Context] = {}
    seen: dict[str, ChatMessage] = {}
    done = asyncio.Event()

    def wire(n: str) -> None:
        a = people[n]

        @a.on_message(ChatMessage)
        async def on_msg(ctx: Context, sender: str, msg: ChatMessage):
            inbox[n].messages.append(msg)

        @a.on_event("startup")
        async def keep(ctx: Context):
            ctxs[n] = ctx

    for n in people:
        wire(n)

    async def say(who: str, message: str | dict) -> None:
        await ctxs[who].send(doorstep.address, chat(message if isinstance(message, str) else json.dumps(message)))

    def sel(msg: ChatMessage, which: str = "approve") -> dict:
        c = card(msg)
        if c["_kind"] == "review":
            return c["approve_cta" if which == "approve" else "reject_cta"]["selection"]
        return next(x for x in c["ctas"] if x.get("primary"))["selection"]

    async def script():
        try:
            while len(ctxs) < len(people):
                await asyncio.sleep(0.05)
            # Unlinked people are asked to link; a code works once.
            await say("stranger", "Start the simulated Zone 3 readiness check")
            seen["stranger"] = await inbox["stranger"].wait(lambda m: "Link your account" in title(m))
            for who, code in (("resident", "MARIA-4821"), ("volunteer", "SARAH-7310"), ("coord", "COORD-1150")):
                await say(who, f"LINK {code}")
                seen[f"link_{who}"] = await inbox[who].wait(lambda m: "Linked as" in text(m))
            await say("stranger", "LINK MARIA-4821")
            seen["spent"] = await inbox["stranger"].wait(lambda m: "CODE_SPENT" in text(m))

            await say("coord", "Start the simulated Zone 3 readiness check")
            checkin = await inbox["resident"].wait(lambda m: "Check-in" in title(m))
            availability = await inbox["volunteer"].wait(lambda m: "Are you available" in title(m))
            seen["outreach"] = await inbox["coord"].wait(lambda m: "Volunteer outreach" in title(m))

            await say("resident", sel(checkin))  # 1 NEED HELP
            confirm = await inbox["resident"].wait(lambda m: "Confirm your needs" in title(m))
            await say("resident", sel(confirm))
            seen["needs"] = await inbox["resident"].wait(lambda m: "Needs confirmed: True" in text(m))
            await say("volunteer", sel(availability))
            seen["avail"] = await inbox["volunteer"].wait(lambda m: "AVAILABLE" in text(m))

            await say("coord", "Find a match for Maria")
            match = await inbox["coord"].wait(lambda m: "Match proposal" in title(m))
            await say("coord", sel(match))
            seen["asked"] = await inbox["coord"].wait(lambda m: "Asked volunteer_sarah in their own" in text(m))
            seen["assignment"] = await inbox["volunteer"].wait(lambda m: "New assignment" in title(m))

            await say("volunteer", sel(seen["assignment"]))  # Accept
            seen["route"] = await inbox["volunteer"].wait(lambda m: "Route for volunteer_sarah" in title(m))
            v_pickup = await inbox["volunteer"].wait(lambda m: "Confirm pickup" in title(m))
            seen["help"] = await inbox["resident"].wait(lambda m: "Help on the way" in title(m))
            r_pickup = await inbox["resident"].wait(lambda m: "Confirm pickup" in title(m))
            seen["coord_help"] = await inbox["coord"].wait(lambda m: "Help on the way" in title(m))

            await say("resident", sel(r_pickup))
            seen["waiting"] = await inbox["resident"].wait(lambda m: "Waiting for the volunteer" in text(m))
            await say("volunteer", sel(v_pickup))
            seen["picked"] = await inbox["volunteer"].wait(lambda m: "PICKUP_CONFIRMED" in text(m))
            seen["picked_resident"] = await inbox["resident"].wait(lambda m: "PICKUP_CONFIRMED" in text(m))

            await say("coord", "Confirm arrival for Maria")
            seen["arrival"] = await inbox["coord"].wait(lambda m: "Asked Maria (synthetic) in their own chat" in text(m))
            consent = await inbox["resident"].wait(
                lambda m: "Further help" in title(m) and (card(m) or {}).get("_kind") == "review")
            await say("coord", "Request recovery for Maria")
            seen["coord_cannot"] = await inbox["coord"].wait(lambda m: "can consent" in text(m))
            await say("resident", sel(consent))
            seen["referrals"] = await inbox["resident"].wait(lambda m: "Housing secured" in text(m))
        finally:
            done.set()

    @people["coord"].on_event("startup")
    async def start(ctx: Context):
        asyncio.create_task(script())

    await run_until([doorstep, network, matching, post, calamity, news, route, *people.values()], done, timeout=150)

    assert "Link this chat first" in text(seen["stranger"])
    assert "Linked as coordinator" in text(seen["link_coord"]) and "Linked as Maria" in text(seen["link_resident"])
    assert "CODE_SPENT" in text(seen["spent"])  # demo codes work once
    assert "SYNTHETIC: Zone 3 Sector B meeting point" not in text(seen["assignment"])  # pickup point private
    assert "ILLUSTRATIVE_ONLY" in text(seen["route"]) and len(here.calls) == 1
    assert "both the volunteer and the resident in their own chats" in text(seen["picked"])
    assert "Housing secured: no" in text(seen["referrals"])

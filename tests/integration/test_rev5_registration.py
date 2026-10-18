"""Rev 5: self-registration in ASI:One with HERE geocoding (mocked; no paid calls)."""

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
from uagents import Context

from doorstep.agents import coordinator
from doorstep.agents import coordinator_actions as actions
from doorstep.agents.calamity_checker import CalamityChecker
from doorstep.agents.journey import Journey
from doorstep.agents.registration import Registration
from doorstep.agents.volunteer_network import build_network_protocol
from doorstep.integrations.geocoder import Geocoder, classify
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend, network_client
from tests.integration.test_rev4_linking import Inbox, card, chat, text, title

IN_WARNING_ZONE = (34.1010, -118.0960)  # inside Zone 3 Sector B (synthetic WARNING polygon)
IN_EAST_VALLEY = (34.0960, -118.1080)


def item(lat, lng, score=0.98, kind="houseNumber", title_="1 Demo Way, Demo City, CA (DEMO)"):
    return {"title": title_, "resultType": kind, "position": {"lat": lat, "lng": lng},
            "scoring": {"queryScore": score}}


def test_geocode_confidence_rules():
    assert classify([item(*IN_WARNING_ZONE)]).confidence == "HIGH"
    assert classify([]).confidence == "FAILED"
    assert classify([item(1, 1, kind="locality")]).reason.startswith("NOT_PRECISE")  # a city is not a home
    assert classify([item(1, 1, score=0.7)]).confidence == "LOW"
    assert classify([item(1, 1, 0.95), item(2, 2, 0.93)]).reason == "AMBIGUOUS"  # never guess between two


class FakeGeocode:
    def __init__(self, by_query):
        self.by_query, self.calls = by_query, []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        q = parse_qs(urlparse(str(request.url)).query)["q"][0]
        self.calls.append(q)
        return httpx.Response(200, json={"items": self.by_query.get(q, [])})


async def test_resident_and_volunteer_register_themselves(monkeypatch):
    monkeypatch.setenv("REQUIRE_LINK", "true")
    backend, _ = make_v2_backend(monkeypatch)
    geo = FakeGeocode({"1 Demo Way": [item(*IN_WARNING_ZONE)], "Somewhere": [item(1, 1, kind="locality")],
                       "2 Demo Ave": [item(*IN_EAST_VALLEY)]})
    doorstep, network, calamity = make_agent("doorstep"), make_agent("network"), make_agent("calamity")
    doorstep.include(coordinator.chat_proto)
    doorstep.include(coordinator.journey_proto)
    network.include(build_network_protocol(lambda: network_client(backend)))

    async def fetch(url):
        return True, 200, await backend._request("GET", "/demo/feeds/caloes", "corr"), None

    calamity.include(CalamityChecker(lambda: backend, fetch, coordinator_address=lambda: doorstep.address).protocol(3600))
    for role, a in (("NETWORK", network), ("CALAMITY", calamity), ("NEWS", network)):
        monkeypatch.setenv(f"{role}_AGENT_ADDRESS", a.address)
    monkeypatch.setattr(coordinator, "get_v2_backend", lambda: backend)
    monkeypatch.setattr(coordinator, "journey", Journey(lambda: backend, coordinator.address_for))
    monkeypatch.setattr(coordinator, "registration",
                        Registration(lambda: backend, Geocoder(api_key="test-key", transport=geo.transport)))
    monkeypatch.setattr(actions, "get_backend", lambda: backend)

    people = {n: make_agent(n) for n in ("newres", "newvol", "coord")}
    inbox = {n: Inbox() for n in people}
    ctxs: dict[str, Context] = {}
    seen: dict = {}
    done = asyncio.Event()

    def wire(n):
        from uagents_core.contrib.protocols.chat import ChatMessage

        @people[n].on_message(ChatMessage)
        async def on_msg(ctx: Context, sender: str, msg):
            inbox[n].messages.append(msg)

        @people[n].on_event("startup")
        async def keep(ctx: Context):
            ctxs[n] = ctx

    for n in people:
        wire(n)

    async def say(who, message):
        await ctxs[who].send(doorstep.address, chat(message if isinstance(message, str) else json.dumps(message)))

    async def script():
        try:
            while len(ctxs) < len(people):
                await asyncio.sleep(0.05)
            await say("newres", "hello")
            seen["choice"] = await inbox["newres"].wait(lambda m: "Register" == title(m).split(" · ")[-1])
            await say("newres", "register as resident")
            form = await inbox["newres"].wait(lambda m: "Register as resident" in title(m))
            seen["form_kind"] = card(form)["_kind"]
            base = {"action": "register_submit", "role": "RESIDENT", "name": "Rosa (synthetic)", "language": "es",
                    "need_1": True, "need_4": "true", "pet_count": "1", "consent_checkin": True,
                    "consent_transport": True, "consent_destination": True}
            await say("newres", {**base, "address": "Somewhere"})  # too vague -> refused, nothing stored
            seen["vague"] = await inbox["newres"].wait(lambda m: "too vague" in text(m))
            await say("newres", {**base, "address": "1 Demo Way"})
            seen["confirm"] = await inbox["newres"].wait(lambda m: "Confirm registration" in title(m))
            await say("newres", card(seen["confirm"])["approve_cta"]["selection"])
            seen["linked"] = await inbox["newres"].wait(lambda m: "Registered and linked" in text(m))

            await say("newvol", "register as volunteer")
            vform = await inbox["newvol"].wait(lambda m: "Register as volunteer" in title(m))
            seen["orgs"] = [o["value"] for f in card(vform)["fields"] if f["name"] == "org_id" for o in f["options"]]
            await say("newvol", {"action": "register_submit", "role": "VOLUNTEER", "name": "Vic (synthetic)",
                                 "org_id": "eastside_rides_demo", "address": "2 Demo Ave",
                                 "vehicle_type": "WHEELCHAIR_VAN", "vehicle_seats": 2, "wheelchair_spaces": 1,
                                 "can_1": True, "can_2": True})
            vconfirm = await inbox["newvol"].wait(lambda m: "Confirm registration" in title(m))
            await say("newvol", "confirm")
            seen["vlinked"] = await inbox["newvol"].wait(lambda m: "Registered and linked" in text(m))
            seen["vconfirm"] = vconfirm

            await say("coord", "LINK COORD-1150")
            await inbox["coord"].wait(lambda m: "Linked as coordinator" in text(m))
            await say("coord", "Start the simulated Zone 3 readiness check")
            seen["checkin"] = await inbox["newres"].wait(lambda m: "Check-in" in title(m))
        finally:
            done.set()

    @people["coord"].on_event("startup")
    async def start(ctx: Context):
        asyncio.create_task(script())

    await run_until([doorstep, network, calamity, *people.values()], done, timeout=120)

    assert seen["form_kind"] == "form"
    assert "too vague" in text(seen["vague"]) and geo.calls[0] == "Somewhere"
    assert "Rosa (synthetic)" in text(seen["linked"])
    assert "Only the coordinates are stored" in text(seen["confirm"])
    assert "eastside_rides_demo" in seen["orgs"] and "unlisted_vans_demo" not in seen["orgs"]
    assert "must approve you" in text(seen["vlinked"])
    assert "Rosa (synthetic)" in title(seen["checkin"])  # a self-registered resident gets a real check-in
    assert "Aviso SIMULADO" in text(seen["checkin"])  # in the language Rosa chose on the form ("es")

"""Coordinator <-> Transport/Destination agents over uAgents messaging (in-process)."""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from doorstep.agents import coordinator_actions as actions
from doorstep.agents.coordinator import DEMO_PREFIX, chat_proto
from doorstep.agents.destination_provider import destination_proto
from doorstep.agents.provider_client import request_acceptance
from doorstep.agents.transport_provider import transport_proto
from tests.integration.backend_fixtures import confirm_needs, make_backend
from tests.integration.conftest import make_agent, run_until


@pytest.fixture
async def providers(monkeypatch):
    # Async so the agents bind to the test's event loop.
    transport = make_agent("transport")
    transport.include(transport_proto)
    destination = make_agent("destination")
    destination.include(destination_proto)
    monkeypatch.setenv("TRANSPORT_AGENT_ADDRESS", transport.address)
    monkeypatch.setenv("DESTINATION_AGENT_ADDRESS", destination.address)
    return [transport, destination]


async def ask_coordinator(providers, text: str) -> str:
    coordinator = make_agent("coordinator")
    coordinator.include(chat_proto)
    tester = make_agent("asi_one_user")
    replies: list[str] = []
    done = asyncio.Event()

    @tester.on_event("startup")
    async def ask(ctx: Context):
        await ctx.send(coordinator.address, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
            content=[TextContent(type="text", text=text)]))

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        LAST_REPLY["msg"] = msg
        replies.append(msg.content[0].text)
        done.set()

    await run_until([coordinator, tester, *providers], done)
    assert replies[0].startswith(DEMO_PREFIX)
    return replies[0]


LAST_REPLY: dict = {}


@pytest.fixture
async def backend(monkeypatch):
    b = make_backend(monkeypatch)
    monkeypatch.setattr(actions, "get_backend", lambda: b)
    return b


async def test_maria_offers_from_agents_are_evaluated_by_backend(providers, backend):
    await confirm_needs(backend)
    text = await ask_coordinator(providers, "Show available suitable providers for Maria")
    assert "Transport agent returned 5 offers over Fetch.ai" in text
    assert "Destination agent returned 3 offers over Fetch.ai" in text
    assert "ELIGIBLE #1: transport_org_a" in text
    assert "not suitable: transport_org_b (NOT_WHEELCHAIR_ACCESSIBLE" in text
    assert "not suitable: transport_org_c (PROVIDER_NOT_APPROVED" in text
    assert "ELIGIBLE #1: destination_org_a" in text
    assert "Nothing is assigned yet" in text


async def test_no_case_before_warning(providers, backend):
    text = await ask_coordinator(providers, "Show available suitable providers for Maria")
    assert "Start the simulated Zone 3 readiness check first" in text


async def test_unconfirmed_needs_contact_no_provider(providers, backend):
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_setup")
    text = await ask_coordinator(providers, "Show available suitable providers for Maria")
    assert "not confirmed" in text
    assert "agent returned" not in text


async def test_start_readiness_check(providers, backend):
    text = await ask_coordinator(providers, "Start the simulated Zone 3 readiness check")
    assert "Simulated official warning verified for zone_3" in text
    assert "case_maria_001" in text and "case_david_002" in text


async def test_david_in_active_order_zone_is_blocked(providers, backend):
    await confirm_needs(backend)
    text = await ask_coordinator(providers, "Show providers for David")
    assert "ELIGIBLE" not in text
    assert "ACTIVE_ORDER_ZONE" in text
    assert "assistance is NOT confirmed" in text


async def test_status_uses_backend_summary(providers, backend):
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_setup")
    text = await ask_coordinator(providers, "Status for Maria")
    assert "Maria" in text


async def _accept(providers, provider_id: str, assignment_id: str) -> list:
    tester = make_agent("coordinator_client")
    results: list = []
    done = asyncio.Event()

    @tester.on_event("startup")
    async def go(ctx: Context):
        for _ in range(2):  # second call simulates a duplicate/delayed request
            results.append(await request_acceptance(
                ctx, "accessible_transport", "case_maria_001", assignment_id,
                f"offer_req_001_{provider_id}", provider_id,
                {"wheelchair_accessible_vehicle": True, "pet_count": 1}, "corr_test"))
        done.set()

    await run_until([tester, *providers], done)
    return results


async def test_provider_accepts_and_is_idempotent(providers):
    results = await _accept(providers, "transport_org_a", f"assign_{uuid4().hex[:6]}")
    assert [r.decision for r in results] == ["ACCEPTED", "ACCEPTED"]
    assert results[0].created_at == results[1].created_at  # same stored decision, not a new one
    assert results[0].correlation_id == "corr_test"


async def test_provider_can_decline(providers, monkeypatch):
    monkeypatch.setenv("DECLINE_PROVIDERS", "transport_org_a")
    results = await _accept(providers, "transport_org_a", f"assign_{uuid4().hex[:6]}")
    assert results[0].decision == "DECLINED"
    assert results[0].reason == "PROVIDER_DECLINED"


async def test_unknown_provider_is_declined(providers):
    results = await _accept(providers, "transport_org_zzz", f"assign_{uuid4().hex[:6]}")
    assert results[0].decision == "DECLINED"
    assert results[0].reason == "UNKNOWN_PROVIDER"


async def test_status_is_a_case_card_and_card_click_routes(providers, backend):
    """One ASI:One session: ask for status, get a card, click its button (selection JSON)."""
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_setup")
    coordinator = make_agent("coordinator")
    coordinator.include(chat_proto)
    tester = make_agent("asi_one_user")
    replies: list[ChatMessage] = []
    done = asyncio.Event()

    def chat(text: str) -> ChatMessage:
        return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                           content=[TextContent(type="text", text=text)])

    @tester.on_event("startup")
    async def ask(ctx: Context):
        await ctx.send(coordinator.address, chat("Status for Maria"))

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        replies.append(msg)
        if len(replies) == 1:
            selection = json.loads(msg.content[1].metadata["card_payload"])["ctas"][0]["selection"]
            await ctx.send(coordinator.address, chat(json.dumps(selection)))
        else:
            done.set()

    await run_until([coordinator, tester, *providers], done)

    first, second = (m.content[1].metadata for m in replies)
    assert first["card_kind"] == "detail" and first["card_protocol_version"] == "1"
    assert second["card_kind"] == "detail"
    assert "Maria" in replies[1].content[0].text

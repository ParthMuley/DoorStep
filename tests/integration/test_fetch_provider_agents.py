"""Coordinator <-> Transport/Destination agents over uAgents messaging (in-process)."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from doorstep.agents.coordinator import DEMO_PREFIX, chat_proto
from doorstep.agents.destination_provider import destination_proto
from doorstep.agents.provider_client import request_acceptance
from doorstep.agents.transport_provider import transport_proto
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


async def test_chat_fans_out_to_both_provider_agents(providers):
    coordinator = make_agent("coordinator")
    coordinator.include(chat_proto)
    tester = make_agent("asi_one_user")
    replies: list[str] = []
    done = asyncio.Event()

    @tester.on_event("startup")
    async def ask(ctx: Context):
        await ctx.send(coordinator.address, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
            content=[TextContent(type="text", text="Show available suitable providers")]))

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        replies.append(msg.content[0].text)
        done.set()

    await run_until([coordinator, tester, *providers], done)

    text = replies[0]
    assert text.startswith(DEMO_PREFIX)
    assert "Transport agent returned 5 vehicles" in text
    assert "Destination agent returned 3 sites" in text
    assert "transport_org_b sedan_b1: wheelchair no" in text
    assert "Nothing is assigned" in text


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

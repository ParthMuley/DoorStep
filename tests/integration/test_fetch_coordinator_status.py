"""Coordinator status replies: case cards from B's case record, and card clicks."""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from doorstep.agents import coordinator_actions as actions
from doorstep.agents.coordinator import DEMO_PREFIX, chat_proto
from tests.integration.backend_fixtures import make_backend
from tests.integration.conftest import make_agent, run_until


@pytest.fixture
async def backend(monkeypatch):
    b = make_backend(monkeypatch)
    monkeypatch.setattr(actions, "get_backend", lambda: b)
    return b


def chat(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=text)])


async def converse(*texts: str, follow_card_button: bool = False) -> list[ChatMessage]:
    coordinator, tester = make_agent("coordinator"), make_agent("asi_one_user")
    coordinator.include(chat_proto)
    replies: list[ChatMessage] = []
    done = asyncio.Event()

    @tester.on_event("startup")
    async def ask(ctx: Context):
        await ctx.send(coordinator.address, chat(texts[0]))

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        replies.append(msg)
        if follow_card_button and len(replies) == 1:
            selection = json.loads(msg.content[1].metadata["card_payload"])["ctas"][0]["selection"]
            await ctx.send(coordinator.address, chat(json.dumps(selection)))
        else:
            done.set()

    await run_until([coordinator, tester], done)
    assert all(r.content[0].text.startswith(DEMO_PREFIX) for r in replies)
    return replies


async def test_no_case_before_warning(backend):
    [reply] = await converse("Status for Maria")
    assert "Start the simulated Zone 3 readiness check first" in reply.content[0].text


async def test_status_is_a_case_card_and_card_click_routes(backend):
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_setup")
    first, second = await converse("Status for Maria", follow_card_button=True)
    assert first.content[1].metadata["card_kind"] == "detail"
    assert first.content[1].metadata["card_protocol_version"] == "1"
    assert second.content[1].metadata["card_kind"] == "detail"
    assert "Maria" in second.content[0].text

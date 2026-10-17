"""Local chat round-trip: a tester agent sends an ASI:One-style ChatMessage to an agent
running the coordinator's chat protocol (no Agentverse needed)."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Context
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

from doorstep.agents.coordinator import DEMO_PREFIX, chat_proto
from tests.integration.conftest import make_agent, run_until


async def test_coordinator_acknowledges_and_replies_with_demo_label():
    coordinator = make_agent("coordinator")
    coordinator.include(chat_proto)
    tester = make_agent("asi_one_user")

    received: dict[str, object] = {}
    done = asyncio.Event()
    sent_id = uuid4()

    @tester.on_event("startup")
    async def send_hello(ctx: Context):
        await ctx.send(coordinator.address, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=sent_id,
            content=[TextContent(type="text", text="hello")]))

    @tester.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        received["ack"] = msg

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        received["reply"] = msg
        done.set()

    await run_until([coordinator, tester], done)

    assert received["ack"].acknowledged_msg_id == sent_id
    reply_text = received["reply"].content[0].text
    assert reply_text.startswith(DEMO_PREFIX)
    assert "911" in reply_text

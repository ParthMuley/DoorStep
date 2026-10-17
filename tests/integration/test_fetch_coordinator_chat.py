"""Local chat round-trip: a tester agent sends an ASI:One-style ChatMessage to an agent
running the coordinator's chat protocol, inside one Bureau (no Agentverse needed)."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("COORDINATOR_SEED", "doorstep-test-coordinator-seed")

from uagents import Agent, Bureau, Context  # noqa: E402
from uagents_core.contrib.protocols.chat import (  # noqa: E402
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
)

from doorstep.agents.coordinator import DEMO_PREFIX, chat_proto  # noqa: E402


async def test_coordinator_acknowledges_and_replies_with_demo_label():
    coordinator = Agent(name="test_coordinator", seed="doorstep-test-coordinator-local")
    coordinator.include(chat_proto)
    tester = Agent(name="test_asi_one_user", seed="doorstep-test-asi-one-user")

    received: dict[str, object] = {}
    done = asyncio.Event()
    sent_id = uuid4()

    @tester.on_event("startup")
    async def send_hello(ctx: Context):
        await ctx.send(
            coordinator.address,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=sent_id,
                content=[TextContent(type="text", text="hello")],
            ),
        )

    @tester.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        received["ack"] = msg

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        received["reply"] = msg
        done.set()

    bureau = Bureau(port=8199)
    bureau.add(coordinator)
    bureau.add(tester)
    task = asyncio.create_task(bureau.run_async())
    try:
        await asyncio.wait_for(done.wait(), timeout=20)
    finally:
        task.cancel()

    assert received["ack"].acknowledged_msg_id == sent_id
    reply_text = received["reply"].content[0].text
    assert reply_text.startswith(DEMO_PREFIX)
    assert "911" in reply_text

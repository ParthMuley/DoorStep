"""Drive the whole V2 journey against the LIVE Doorstep agent (through Agentverse), the
way an ASI:One user would: send messages, click card buttons, print every message
received, including pushed alert cards. DOORSTEP DEMO only.

Usage (repo root, backend + agents running):  .venv/Scripts/python -u scripts/journey_probe.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Agent, Context
from uagents.crypto import Identity
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

load_dotenv()
DOORSTEP = Identity.from_seed(os.environ["COORDINATOR_SEED"], 0).address
WAIT = float(os.getenv("PROBE_WAIT_SECONDS", "90"))

probe = Agent(name="doorstep_journey_probe", seed=f"doorstep-journey-probe-{uuid4()}", port=8197,
              endpoint=["http://127.0.0.1:8197/submit"])
inbox: asyncio.Queue = asyncio.Queue()


def chat(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])


def card(msg: ChatMessage) -> dict | None:
    meta = next((c.metadata for c in msg.content if getattr(c, "type", "") == "metadata"), None)
    return json.loads(meta["card_payload"]) | {"_kind": meta["card_kind"]} if meta else None


def show(msg: ChatMessage) -> None:
    c = card(msg)
    head = f"[{c['_kind']} card] {c['title']}" if c else "[text]"
    print(f"\n<<< {head}\n{msg.content[0].text}", flush=True)


def primary(c: dict) -> dict:
    return c["approve_cta"]["selection"] if c["_kind"] == "review" else next(x for x in c["ctas"] if x.get("primary"))["selection"]


@probe.on_message(ChatAcknowledgement)
async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@probe.on_message(ChatMessage)
async def received(ctx: Context, sender: str, msg: ChatMessage):
    await inbox.put(msg)


async def say(ctx: Context, message, expect: int = 1) -> list[ChatMessage]:
    text = message if isinstance(message, str) else json.dumps(message)
    print(f"\n>>> {text}", flush=True)
    await ctx.send(DOORSTEP, chat(text))
    got = []
    for _ in range(expect):
        msg = await asyncio.wait_for(inbox.get(), WAIT)
        show(msg)
        got.append(msg)
    return got


@probe.on_event("startup")
async def run(ctx: Context):
    try:
        await say(ctx, "Start the simulated Zone 3 readiness check", expect=4)
        await say(ctx, "Show road conditions")
        await say(ctx, "Simulate Maria's reply")
        match = await say(ctx, "Find a match for Maria")
        approved = await say(ctx, primary(card(match[0])))
        await say(ctx, primary(card(approved[0])))
        arrival = await say(ctx, "Confirm arrival for Maria", expect=2)
        await say(ctx, primary(card(arrival[1])))
        david = await say(ctx, "Find a match for David")
        await say(ctx, primary(card(david[0])))
        print("\n=== JOURNEY COMPLETE ===", flush=True)
    except asyncio.TimeoutError:
        print(f"\n!!! timed out waiting {WAIT}s for a message", flush=True)
    finally:
        os._exit(0)


if __name__ == "__main__":
    sys.exit(probe.run())

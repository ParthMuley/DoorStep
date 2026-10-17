"""Send one chat message to the running Coordinator from a separate local agent process,
the same way ASI:One does, and print the reply. DOORSTEP DEMO only.

Usage: python scripts/chat_probe.py "Show available suitable providers"
"""

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Agent, Context
from uagents.crypto import Identity
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

load_dotenv()
TEXT = sys.argv[1] if len(sys.argv) > 1 else "hello"
COORDINATOR = Identity.from_seed(os.environ["COORDINATOR_SEED"], 0).address

probe = Agent(name="doorstep_chat_probe", seed=f"doorstep-chat-probe-{uuid4()}", port=8198,
              endpoint=["http://127.0.0.1:8198/submit"])


@probe.on_event("startup")
async def send(ctx: Context):
    await ctx.send(COORDINATOR, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                            content=[TextContent(type="text", text=TEXT)]))


@probe.on_message(ChatAcknowledgement)
async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info("coordinator acknowledged")


@probe.on_message(ChatMessage)
async def reply(ctx: Context, sender: str, msg: ChatMessage):
    print("\n----- COORDINATOR REPLY -----")
    print("".join(c.text for c in msg.content if isinstance(c, TextContent)), flush=True)
    os._exit(0)  # skips buffer flushing, hence flush=True above


if __name__ == "__main__":
    probe.run()

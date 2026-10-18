"""One ASI:One message per burst (live finding 2026-10-18).

ASI:One merges every agent message that arrives during one user turn into a single
bubble and renders only the last card. So everything for one person is queued here and
sent as ONE message once they've been quiet for PUSH_COALESCE_SECONDS (default 6 s: agent
hops through Agentverse mailboxes take several seconds; capped at PUSH_COALESCE_MAX_SECONDS): all text and card narrations are combined, and the
message carries the last interactive card (the one with buttons), or the last card.
PUSH_COALESCE_SECONDS=0 sends every part immediately (tests and debugging).

Pushes go out on the person's own chat session (live finding 2026-10-18): ctx.send stamps
the envelope with the context's session, and ASI:One shows a message only in the chat
whose session it carries. A push sent from an agent-to-agent handler (an alert) carries
that agent's session and never appears, so we send through the context of the person's
latest message (remember()).
"""

import asyncio
import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent, TextContent

from doorstep.integrations.asi_cards import DEMO_PREFIX, Card, text_message

Part = Card | str


CHAT_SEP = "#"  # DEMO_LINK_PER_CHAT identities are "<account address>#<chat tag>"


def destination(identity: str) -> str:
    """The ASI:One account address to send to (a per-chat demo identity carries a chat tag)."""
    return identity.split(CHAT_SEP, 1)[0]


def _interactive(part: Part) -> bool:
    return isinstance(part, Card) and part.interactive


def compose(parts: list[Part]) -> ChatMessage:
    """One message: combined text + the most actionable card."""
    cards = [p for p in parts if isinstance(p, Card)]
    primary = next((c for c in reversed(cards) if c.interactive), cards[-1] if cards else None)
    texts = [p.narration if isinstance(p, Card) else p for p in parts]
    body = f"{DEMO_PREFIX} " + "\n\n".join(t.strip() for t in texts if t and t.strip())
    content: list = [TextContent(type="text", text=body)]
    if primary is not None:
        dropped = [str(c.payload.get("title", "")).split(" · ", 1)[-1] for c in cards if c is not primary]
        if dropped and "summary_rows" in primary.payload:  # the card that renders names what the text holds
            rows = primary.payload["summary_rows"]
            primary = replace(primary, payload={**primary.payload, "summary_rows": rows[:-1] + [
                {"label": "Also in this update", "value": "; ".join(dropped) + " (see the text above)"}, rows[-1]]})
        content.append(next(c for c in primary.to_message().content if isinstance(c, MetadataContent)))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


class Outbox:
    def __init__(self):
        self._buf: dict[str, list[Part]] = {}
        self._last: dict[str, float] = {}
        self._first: dict[str, float] = {}
        self._running: set[str] = set()
        self._chat_ctx: dict[str, Context] = {}  # the person's latest inbound chat context
        self._flush_ctx: dict[str, Context] = {}

    def remember(self, ctx: Context, address: str) -> None:
        """Call on every chat message from a person: later pushes reuse its session."""
        self._chat_ctx[address] = ctx

    def _ctx_for(self, ctx: Context, address: str) -> Context:
        return self._chat_ctx.get(address, ctx)

    @staticmethod
    def delay() -> float:
        return float(os.getenv("PUSH_COALESCE_SECONDS", "6"))

    async def add(self, ctx: Context, address: str, *parts: Part) -> None:
        ctx = self._ctx_for(ctx, address)
        if self.delay() <= 0:  # legacy: one message per part
            for part in parts:
                await ctx.send(destination(address), part.to_message() if isinstance(part, Card) else text_message(part))
            return
        loop = asyncio.get_running_loop()
        self._buf.setdefault(address, []).extend(parts)
        self._flush_ctx[address] = ctx
        self._last[address] = loop.time()
        self._first.setdefault(address, loop.time())
        if address not in self._running:
            self._running.add(address)
            asyncio.create_task(self._flush_when_quiet(address))

    async def _flush_when_quiet(self, address: str) -> None:
        loop, cap = asyncio.get_running_loop(), float(os.getenv("PUSH_COALESCE_MAX_SECONDS", "30"))
        while True:
            await asyncio.sleep(self.delay())
            now = loop.time()
            if now - self._last[address] >= self.delay() or now - self._first[address] >= cap:
                break
        # No await between these lines: a part added later starts a new flush.
        self._running.discard(address)
        self._first.pop(address, None)
        parts = self._buf.pop(address, [])
        ctx = self._flush_ctx.pop(address)
        if parts:
            ctx.logger.info(f"outbox: 1 message ({len(parts)} parts) to {address[:16]}...")
            await ctx.send(destination(address), compose(parts))

"""One ASI:One message per burst: ASI:One merges a turn's messages and renders only the
last card, so the outbox combines a burst into one message carrying the actionable card."""

import asyncio

from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent

from doorstep.integrations.asi_cards import help_on_the_way_card, info_card, recovery_consent_card
from doorstep.integrations.outbox import Outbox, compose
from tests.integration.conftest import make_agent, run_until


def kind(msg: ChatMessage) -> str | None:
    meta = next((c for c in msg.content if isinstance(c, MetadataContent)), None)
    return meta.metadata["card_kind"] if meta else None


def test_compose_keeps_all_text_and_the_last_interactive_card():
    info = info_card("Alert detected", [("Zone", "WARNING")], "Alert text.", "test")
    consent = recovery_consent_card(case_id="c1", display_name="Maria (synthetic)", help_types=["TEMPORARY_HOUSING"])
    route = info_card("Route", [("Status", "ILLUSTRATIVE_ONLY")], "Route text.", "test")
    msg = compose(["Plain reply.", info, consent, route])
    body = msg.content[0].text
    assert body.startswith("DOORSTEP DEMO") and body.count("DOORSTEP DEMO") == 1
    assert "Plain reply." in body and "Alert text." in body and "Route text." in body
    assert kind(msg) == "review"  # the consent card (has buttons) wins over the later info card
    assert kind(compose(["only text"])) is None


async def test_burst_arrives_as_one_message(monkeypatch):
    monkeypatch.setenv("PUSH_COALESCE_SECONDS", "0.4")
    sender, receiver = make_agent("sender"), make_agent("receiver")
    got: list[ChatMessage] = []
    done = asyncio.Event()
    outbox = Outbox()
    help_card = help_on_the_way_card(case_id="c1", display_name="Maria (synthetic)", volunteer_label="v",
                                     eta_minutes=5, eta_label=None, route_status="ILLUSTRATIVE_ONLY")

    @receiver.on_message(ChatMessage)
    async def on_msg(ctx: Context, s: str, msg: ChatMessage):
        got.append(msg)

    @sender.on_event("startup")
    async def burst(ctx: Context):
        await outbox.add(ctx, receiver.address, "Reply first.")
        await asyncio.sleep(0.2)  # a push arriving shortly after the reply
        await outbox.add(ctx, receiver.address, info_card("Alert", [("Zone", "WARNING")], "Pushed alert.", "t"),
                         help_card)
        await asyncio.sleep(2.0)
        await outbox.add(ctx, receiver.address, "A later, separate update.")
        await asyncio.sleep(1.5)
        done.set()

    await run_until([sender, receiver], done)
    assert len(got) == 2
    assert "Reply first." in got[0].content[0].text and "Pushed alert." in got[0].content[0].text
    assert kind(got[0]) == "detail" and "Help on the way" in got[0].content[1].metadata["card_payload"]
    assert "A later, separate update." in got[1].content[0].text and kind(got[1]) is None


class FakeCtx:
    def __init__(self, name, sent):
        self.name, self.sent = name, sent
        self.logger = __import__("logging").getLogger("test")

    async def send(self, address, msg):
        self.sent.append((self.name, address))


async def test_pushes_go_out_on_the_persons_chat_session(monkeypatch):
    """ASI:One shows a message only in the chat whose session it carries, so a push from an
    alert handler must be sent through the person's own chat context."""
    sent: list = []
    outbox, chat_ctx, alert_ctx = Outbox(), FakeCtx("chat", sent), FakeCtx("alert", sent)
    monkeypatch.setenv("PUSH_COALESCE_SECONDS", "0.05")
    await outbox.add(alert_ctx, "stranger", "push")  # never chatted: falls back to the given ctx
    outbox.remember(chat_ctx, "rosa")
    await outbox.add(alert_ctx, "rosa", "check-in")
    await asyncio.sleep(0.3)
    monkeypatch.setenv("PUSH_COALESCE_SECONDS", "0")
    await outbox.add(alert_ctx, "rosa", "legacy")
    assert sorted(sent) == [("alert", "stranger"), ("chat", "rosa"), ("chat", "rosa")]

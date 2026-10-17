"""Local messaging simulator (P0 fallback for Photon). NOTHING IS SENT.

Messages are rows in SQLite. Outbound bodies must start with ``DOORSTEP DEMO``.
Delivery receipts are never invented: an outbound message stays ``SENT`` until
a delivery outcome is explicitly injected through the simulator.
"""

from __future__ import annotations

from typing import Optional

from doorstep.models import CommunicationStatus, MessageDirection, MessageEvent
from doorstep.services.db import Database
from doorstep.services.errors import Conflict
from doorstep.services.store import Store

DEMO_SENDER = "sim_doorstep_demo"  # simulator id for Doorstep outbound
MAX_OUTBOUND_PER_CASE = 25  # simple rate limit for the demo


class MessageSimulator:
    channel = "simulator"

    def __init__(self, db: Database, store: Store):
        self.db = db
        self.store = store

    def send(self, *, case_id: str, recipient: str, body: str, language: str,
             template_id: Optional[str] = None, correlation_id: str = "") -> MessageEvent:
        if not body.startswith("DOORSTEP DEMO"):
            raise ValueError("Outbound simulated messages must be labeled DOORSTEP DEMO")
        sent = [m for m in self.store.list_messages(case_id) if m.direction == MessageDirection.OUTBOUND]
        if len(sent) >= MAX_OUTBOUND_PER_CASE:
            raise Conflict("Outbound message rate limit reached for this case", reasons=["RATE_LIMITED"])
        msg = MessageEvent(
            message_id=self.db.next_id("msg"),
            case_id=case_id,
            direction=MessageDirection.OUTBOUND,
            channel=self.channel,
            sender=DEMO_SENDER,
            recipient=recipient,
            body=body,
            language=language,
            status=CommunicationStatus.SENT,
            template_id=template_id,
            correlation_id=correlation_id,
        )
        self.store.save_message(msg)
        return msg

    def record_inbound(self, *, case_id: Optional[str], sender: str, body: str, language: str,
                       external_id: str, correlation_id: str = "") -> MessageEvent:
        msg = MessageEvent(
            message_id=self.db.next_id("resp"),
            case_id=case_id,
            direction=MessageDirection.INBOUND,
            channel=self.channel,
            sender=sender,
            recipient=DEMO_SENDER,
            body=body,
            language=language,
            external_id=external_id,
            status=CommunicationStatus.REPLIED,
            correlation_id=correlation_id,
        )
        self.store.save_message(msg)
        return msg

    def set_outcome(self, message_id: str, delivered: bool) -> MessageEvent:
        msg = self.store.get_message(message_id)
        if msg.direction != MessageDirection.OUTBOUND:
            raise Conflict("Delivery outcomes apply to outbound messages only")
        msg.status = CommunicationStatus.DELIVERED if delivered else CommunicationStatus.DELIVERY_FAILED
        self.store.save_message(msg)
        return msg

    def outbox(self, case_id: Optional[str] = None) -> list[MessageEvent]:
        return self.store.list_messages(case_id)

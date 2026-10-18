"""Append-only case timeline (MongoDB ``events`` collection), plus replay.

Status-change events are written in the same transaction as the case row they
describe, so the displayed status always has persisted evidence behind it.
``replay_resident_status`` rebuilds the current status from events alone.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from doorstep.models import ResidentStatus, StatusEvent

from .db import Database

# Keys that must never be copied into the generic timeline.
_REDACT = {"text", "body", "needs", "pickup_point", "contact_channel", "display_name",
           "shared_fields", "candidate_needs"}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if k in _REDACT else v) for k, v in data.items()}


class EventLog:
    def __init__(self, db: Database):
        self.db = db

    def append(
        self,
        event_type: str,
        *,
        case_id: Optional[str],
        correlation_id: str = "",
        actor: str = "system",
        data: Optional[dict[str, Any]] = None,
        dimension: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
    ) -> StatusEvent:
        event = StatusEvent(
            event_id=self.db.next_id("evt"),
            case_id=case_id,
            correlation_id=correlation_id,
            event_type=event_type,
            actor=actor,
            dimension=dimension,
            from_status=from_status,
            to_status=to_status,
            data=_redact(data or {}),
        )
        with self.db.tx():
            event.seq = self.db.next_seq("events")
            self.db.coll("events").insert_one({"_id": event.event_id, **event.model_dump(mode="json")})
        return event

    def for_case(self, case_id: str) -> list[StatusEvent]:
        docs = self.db.coll("events").find({"case_id": case_id}).sort("seq", 1)
        return [StatusEvent.model_validate({k: v for k, v in d.items() if not k.startswith("_")}) for d in docs]

    def all(self) -> list[StatusEvent]:
        docs = self.db.coll("events").find({}).sort("seq", 1)
        return [StatusEvent.model_validate({k: v for k, v in d.items() if not k.startswith("_")}) for d in docs]

    def replay_resident_status(self, case_id: str) -> str:
        status = ResidentStatus.UNKNOWN.value
        for ev in self.for_case(case_id):
            if ev.event_type == "RESIDENT_STATUS_CHANGED" and ev.to_status:
                status = ev.to_status
        return status

    def replay_communication_status(self, case_id: str) -> str:
        status = "NOT_SENT"
        for ev in self.for_case(case_id):
            if ev.event_type == "COMMUNICATION_STATUS_CHANGED" and ev.to_status:
                status = ev.to_status
        return status


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True)

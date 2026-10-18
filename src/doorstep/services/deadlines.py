"""15-minute reply deadline (plan rev 4 §0.5.3, contract v2.2). DOORSTEP DEMO.

* Every check-in stores ``case.reply_by`` and every availability request stores
  ``availability.reply_by`` = asked + REPLY_DEADLINE_MINUTES (default 15).
* After it:
  - a volunteer still ASKED becomes NO_REPLY, which matching treats as not available;
  - a resident still SENT/DELIVERED becomes NO_REPLY_AFTER_DEADLINE and joins the
    coordinator's unresolved queue. Silence is NEVER safety or "no help needed".
* Late answers still count (transitions allow NO_REPLY -> AVAILABLE and
  NO_REPLY_AFTER_DEADLINE -> REPLIED).
* Applied lazily on reads (case, outreach, matching, dashboard) and by POST /deadlines/sweep.
  No automatic SMS fallback.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from doorstep.models import CommunicationStatus as C
from doorstep.models.registry import AvailabilityState, VolunteerAvailability

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService


def now() -> datetime:
    """Single clock for deadlines; tests monkeypatch this."""
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes() -> float:
    return float(os.environ.get("REPLY_DEADLINE_MINUTES", "15"))


def reply_by(start: Optional[datetime] = None) -> str:
    return iso((start or now()) + timedelta(minutes=minutes()))


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def passed(value: Optional[str], at: Optional[datetime] = None) -> bool:
    deadline = _parse(value)
    return deadline is not None and (at or now()) >= deadline


class DeadlineService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store
        self.events = engine.events

    def apply(self, correlation_id: str = "") -> dict[str, Any]:
        at = now()
        cases = self._cases(at)
        volunteers = self._volunteers(at)
        return {"checked_at": iso(at), "deadline_minutes": minutes(), "cases_no_reply": cases,
                "volunteers_no_reply": volunteers}

    def _cases(self, at: datetime) -> list[str]:
        hit = []
        for d in self.db.coll("cases").find({"communication_status": {"$in": [C.SENT.value, C.DELIVERED.value]},
                                             "reply_by": {"$ne": None}}):
            if passed(d.get("reply_by"), at):
                self.engine.mark_no_reply_deadline(d["case_id"])
                hit.append(d["case_id"])
        return hit

    def _volunteers(self, at: datetime) -> list[dict[str, str]]:
        partners = self.store.partners
        hit: list[dict[str, str]] = []
        for region in partners.list_regions():
            due = [(e.org_id, v.volunteer_id) for e in region.orgs for v in e.volunteers
                   if v.availability and v.availability.state == AvailabilityState.ASKED.value
                   and passed(v.availability.reply_by, at)]
            if not due:
                continue
            ids = {vid for _, vid in due}

            def fn(r, ids=ids):
                changed = []
                for e in r.orgs:
                    for v in e.volunteers:
                        a = v.availability
                        if v.volunteer_id in ids and a and a.state == AvailabilityState.ASKED.value:
                            v.availability = VolunteerAvailability(alert_id=a.alert_id, state=AvailabilityState.NO_REPLY,
                                                                   asked_at=a.asked_at, reply_by=a.reply_by)
                            changed.append(v.volunteer_id)
                return bool(changed), changed
            changed = set(partners.mutate_region(region.region_id, fn) or [])
            hit += [{"org_id": org, "volunteer_id": vid} for org, vid in due if vid in changed]
        if hit:
            self.events.append("VOLUNTEER_REPLY_DEADLINE_PASSED", case_id=None,
                               data={"no_reply": len(hit)})
        return hit

    def sweep(self, correlation_id: str = "") -> dict[str, Any]:
        out = self.apply(correlation_id)
        notify = []
        if out["cases_no_reply"] or out["volunteers_no_reply"]:
            text = (f"DOORSTEP DEMO: {len(out['cases_no_reply'])} resident(s) did not reply within "
                    f"{int(minutes())} min and need follow-up (silence is not safety); "
                    f"{len(out['volunteers_no_reply'])} volunteer(s) marked NO_REPLY (not available).")
            notify.append({"role": "COORDINATOR", "channel": "ASI_ONE", "template_id": "deadline_summary",
                           "language": "en", "text": text, "case_ids": out["cases_no_reply"]})
        return {"schema_version": "2.0", **out, "notify": notify, "correlation_id": correlation_id}

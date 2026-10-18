"""ASI:One Interactive Cards for the Doorstep dashboard (spec: docs/integration-decisions.md).

A card is a `ChatMessage` with a narration `TextContent` plus one `MetadataContent` whose
string values declare the card. ASI:One shows invalid cards as plain text, so the
narration is always a complete plain-text fallback on its own.

Builders take plain values (not backend responses) so they survive contract changes;
the coordinator maps B's fields into them, copying status words verbatim.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent, TextContent

CardKind = Literal["carousel", "detail", "form", "review"]

CARD_PROTOCOL_VERSION = "1"
MAX_PAYLOAD_BYTES = 64 * 1024
SIM_PREFIX = "SIMULATION"
DEMO_PREFIX = "DOORSTEP DEMO - SIMULATION ONLY."

# Map colors used by B (`map.color`) always shown with a text label too.
COLOR_LABELS = {
    "red": "RED - assistance needed",
    "yellow": "YELLOW - volunteer accepted",
    "blue": "BLUE - pickup confirmed",
    "green": "GREEN - arrival confirmed",
    "black": "BLACK - coordinator attention",
    "gray": "GRAY - unknown",
}


def text_message(text: str) -> ChatMessage:
    """Plain DEMO-labeled chat reply (no card)."""
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=f"{DEMO_PREFIX} {text}")])


class CardValidationError(ValueError):
    pass


@dataclass
class Card:
    kind: CardKind
    payload: dict[str, Any]
    narration: str  # plain-text fallback; must make sense without the card
    interactive: bool = True
    extra_metadata: dict[str, str] = field(default_factory=dict)

    def to_message(self) -> ChatMessage:
        validate(self)
        metadata = {
            "card_protocol_version": CARD_PROTOCOL_VERSION,
            "requires_card_interaction": "true" if self.interactive else "false",
            "card_kind": self.kind,
            "card_payload": json.dumps(self.payload, ensure_ascii=False),
            **self.extra_metadata,
        }
        if not self.interactive:
            metadata["is_terminal"] = "true"
        return ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=f"{DEMO_PREFIX} {self.narration}"),
                MetadataContent(type="metadata", metadata=metadata),
            ],
        )


_REQUIRED = {
    "carousel": ("title", "items"),
    "detail": ("title", "summary_rows"),
    "form": ("title", "fields", "submit_cta"),
    "review": ("title", "summary_rows", "approve_cta", "reject_cta"),
}


def validate(card: Card) -> None:
    """Local checks mirroring the documented limits; the Card Playground is the authority."""
    if card.kind not in _REQUIRED:
        raise CardValidationError(f"unknown card_kind {card.kind}")
    missing = [k for k in _REQUIRED[card.kind] if k not in card.payload]
    if missing:
        raise CardValidationError(f"{card.kind} card missing {missing}")
    if not str(card.payload["title"]).startswith(SIM_PREFIX):
        raise CardValidationError("card title must start with SIMULATION")
    size = len(json.dumps(card.payload, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise CardValidationError(f"card_payload is {size} bytes (> 64 KB)")
    if not card.narration.strip():
        raise CardValidationError("narration (plain-text fallback) is empty")
    for row in card.payload.get("summary_rows", []):
        if not isinstance(row.get("label"), str) or not isinstance(row.get("value"), str):
            raise CardValidationError("summary_rows need string label and value")


def parse_card_selection(text: str) -> dict[str, Any] | None:
    """Card clicks arrive as JSON of the CTA selection (when the agent is @mentioned).
    Returns None for prose so the caller falls back to keyword/intent routing."""
    candidate = text.strip()
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(candidate[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _row(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": "-" if value is None else str(value)}


def _footer(data_as_of: str | None, source: str) -> dict[str, str]:
    as_of = data_as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return _row("Data", f"as of {as_of} · source {source} · SIMULATION")


def _status(color: str | None, label: str | None) -> str:
    text = COLOR_LABELS.get(color or "", (color or "gray").upper())
    return f"{text} ({label})" if label else text


def _rows_text(rows: list[dict[str, str]]) -> str:
    return "\n".join(f"- {r['label']}: {r['value']}" for r in rows)


# ------------------------------------------------------------------ card deck

def case_card(*, case_id: str, display_name: str, map_color: str | None, map_label: str | None,
              zone_status: str | None, steps: list[tuple[str, bool, str | None]], next_step: str | None,
              communication_status: str | None, data_as_of: str | None = None) -> Card:
    """Resident case: status chip + progress stepper with evidence times."""
    rows = [
        _row("Status", _status(map_color, map_label)),
        _row("Zone status", zone_status),
        *[_row(step.replace("_", " ").title(), f"done {at}" if done else "not yet") for step, done, at in steps],
        _row("Communication", communication_status),
        _row("Next step", next_step),
        _footer(data_as_of, "Doorstep case record"),
    ]
    payload = {
        "title": f"{SIM_PREFIX} · Case · {display_name}",
        "summary_rows": rows,
        "ctas": [
            {"label": "Refresh status", "selection": {"action": "case_status", "case_id": case_id}, "primary": True},
            {"label": "Show suitable volunteers", "selection": {"action": "show_matches", "case_id": case_id}},
        ],
    }
    return Card("detail", payload, f"{display_name} ({case_id}):\n{_rows_text(rows)}")


def match_card(*, case_id: str, display_name: str, chosen: list[dict[str, Any]], rejected: list[dict[str, Any]],
               shelter: dict[str, Any] | None, assignment_id: str | None, escalation_required: bool,
               no_match_reason: str | None, data_as_of: str | None = None) -> Card:
    """Match proposal: eligible volunteers with reason chips, rejected with reasons, shelter.
    `chosen`/`rejected` items: {label, reasons: [codes]}; `shelter`: {label, reasons}."""
    rows = [_row(f"Eligible #{i}", f"{c['label']} — {', '.join(c['reasons'])}") for i, c in enumerate(chosen, 1)]
    rows += [_row("Not suitable", f"{r['label']} — {', '.join(r['reasons'])}") for r in rejected]
    rows.append(_row("Shelter", f"{shelter['label']} — {', '.join(shelter['reasons'])}" if shelter else "none eligible"))
    rows.append(_footer(data_as_of, "Doorstep deterministic matching"))
    if escalation_required or not assignment_id:
        rows.insert(0, _row("Result", f"NO MATCH ({no_match_reason or 'UNRESOLVED'}) — assistance not confirmed"))
        payload = {"title": f"{SIM_PREFIX} · No safe match · {display_name}", "summary_rows": rows,
                   "ctas": [{"label": "Escalate (simulated)", "selection": {"action": "escalate", "case_id": case_id},
                             "primary": True}]}
        return Card("detail", payload, f"No match for {display_name}:\n{_rows_text(rows)}")
    rows.insert(0, _row("Result", "PROPOSED — nothing is confirmed until the volunteer accepts"))
    payload = {
        "title": f"{SIM_PREFIX} · Match proposal · {display_name}",
        "summary_rows": rows,
        "approve_cta": {"label": "Approve simulated arrangement",
                        "selection": {"action": "approve", "case_id": case_id, "assignment_id": assignment_id},
                        "primary": True},
        "reject_cta": {"label": "Not now", "selection": {"action": "reject", "case_id": case_id,
                                                          "assignment_id": assignment_id}},
    }
    return Card("review", payload, f"Proposed match for {display_name} (reply 'approve' to continue):\n"
                                   f"{_rows_text(rows)}")


def escalation_card(*, case_id: str, display_name: str, reason: str, status: str, next_step: str | None,
                    data_as_of: str | None = None) -> Card:
    rows = [
        _row("Status", "UNRESOLVED — assistance not confirmed"),
        _row("Reason", reason),
        _row("Escalation", f"{status} (receipt only; no responders confirmed)"),
        _row("Owner", "Coordinator follow-up required"),
        _row("Next step", next_step),
        _footer(data_as_of, "Simulated authorized response service"),
    ]
    payload = {"title": f"{SIM_PREFIX} · Escalation · {display_name}", "summary_rows": rows,
               "ctas": [{"label": "Refresh status", "selection": {"action": "case_status", "case_id": case_id},
                         "primary": True}]}
    return Card("detail", payload, f"{display_name} is UNRESOLVED:\n{_rows_text(rows)}")


def help_on_the_way_card(*, case_id: str, display_name: str, volunteer_label: str, eta_minutes: int | None,
                         eta_label: str | None, route_status: str | None, data_as_of: str | None = None) -> Card:
    rows = [
        _row("Status", _status("yellow", "volunteer accepted, not yet picked up")),
        _row("Volunteer", volunteer_label),
        _row("Estimated arrival", f"about {eta_minutes} min ({eta_label or 'estimate, not a guarantee'})"
             if eta_minutes is not None else "no estimate"),
        _row("Route", route_status or "not previewed"),
        _footer(data_as_of, "Doorstep assignment record"),
    ]
    payload = {"title": f"{SIM_PREFIX} · Help on the way · {display_name}", "summary_rows": rows,
               "ctas": [{"label": "Confirm pickup (simulated)",
                         "selection": {"action": "confirm_pickup", "case_id": case_id}, "primary": True},
                        {"label": "Refresh status", "selection": {"action": "case_status", "case_id": case_id}}]}
    return Card("detail", payload, f"Help is on the way for {display_name} (simulated):\n{_rows_text(rows)}")


def operations_board_card(*, counts: list[dict[str, Any]], unresolved: list[dict[str, Any]],
                          feed_freshness: str | None, last_ingest_at: str | None,
                          case_buttons: list[tuple[str, str]]) -> Card:
    """counts: [{status, count, color, label}]; unresolved: [{display_name, reason}]."""
    rows = [_row(c.get("label") or c["status"], f"{c['count']} ({_status(c.get('color'), None)})") for c in counts]
    rows += [_row("Unresolved", f"{u['display_name']} — {u['reason']}") for u in unresolved]
    rows.append(_row("Alert feed", f"{feed_freshness or 'UNKNOWN'} (last ingest {last_ingest_at or 'never'})"))
    rows.append(_footer(last_ingest_at, "Doorstep operations"))
    payload = {"title": f"{SIM_PREFIX} · Operations board", "summary_rows": rows,
               "ctas": [{"label": f"Open {name}", "selection": {"action": "case_status", "case_id": cid}}
                        for name, cid in case_buttons][:4] or
                       [{"label": "Refresh", "selection": {"action": "operations_board"}}]}
    return Card("detail", payload, f"Operations board:\n{_rows_text(rows)}")


def recovery_consent_card(*, case_id: str, display_name: str, help_types: list[str]) -> Card:
    """Ask before sharing anything with recovery organizations (consent is per purpose)."""
    readable = ", ".join(h.replace("_", " ").lower() for h in help_types)
    rows = [_row("Question", f"Share {display_name}'s accessibility needs with recovery organizations to request "
                             f"help with: {readable}?"),
            _row("What is shared", "Only the minimum for each help type (needs codes, language, pets). "
                                   "No address or phone."),
            _row("Note", "A referral is a request, not secured housing or a filed claim."),
            _footer(None, "Doorstep consent record")]
    payload = {"title": f"{SIM_PREFIX} · Further help · {display_name}", "summary_rows": rows,
               "approve_cta": {"label": "Yes, share and request help (resident consents)",
                               "selection": {"action": "recovery_consent", "case_id": case_id}, "primary": True},
               "reject_cta": {"label": "No thanks",
                              "selection": {"action": "recovery_decline", "case_id": case_id}}}
    return Card("review", payload, f"Does {display_name} want further help ({readable})? Reply 'yes, request "
                                   f"recovery help for {display_name.split(' ')[0]}' to consent.\n{_rows_text(rows)}")


def info_card(title: str, rows: list[tuple[str, Any]], narration_intro: str, source: str,
              data_as_of: str | None = None) -> Card:
    """Generic read-only card (alerts, outreach, road conditions, data health)."""
    summary = [_row(label, value) for label, value in rows] + [_footer(data_as_of, source)]
    payload = {"title": f"{SIM_PREFIX} · {title}", "summary_rows": summary}
    return Card("detail", payload, f"{narration_intro}\n{_rows_text(summary)}", interactive=False)

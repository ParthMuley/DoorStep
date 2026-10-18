"""Coordinator actions behind ASI:One commands. Each returns the reply text.

Case state always comes from Developer B's backend. The V2 journey steps live in
`journey.py`; this module keeps case lookup and the case card.
"""

from typing import Any

from uagents import Context

from doorstep.integrations.asi_cards import Card, case_card
from doorstep.workflows.backend_client import BackendError, DoorstepBackend

CASES_BY_NAME = {"maria": "case_maria_001", "david": "case_david_002"}
DEFAULT_CASE = "case_maria_001"


def get_backend() -> DoorstepBackend:
    """Factory so tests can swap in an in-process backend."""
    return DoorstepBackend()


def case_from_text(text: str) -> str:
    lowered = text.lower()
    for name, case_id in CASES_BY_NAME.items():
        if name in lowered:
            return case_id
    return DEFAULT_CASE


def backend_unavailable(err: Exception) -> str:
    if isinstance(err, BackendError) and err.status_code == 404:
        return ("No case exists for that resident yet. Start the simulated Zone 3 readiness check first; "
                "cases are created only by a verified simulated warning.")
    if isinstance(err, BackendError):
        return f"The case service refused the request ({err.code}: {err.detail}). Nothing was changed."
    return "The case service is unreachable right now, so I can't show verified status. Nothing was changed."


async def case_status(case_id: str, correlation_id: str) -> str | Card:
    try:
        case = await get_backend().get_case_status(case_id, correlation_id)
    except (BackendError, OSError) as err:
        return backend_unavailable(err)
    return case_card_from_status(case)


PROGRESS = ("REQUESTED", "PROVIDER_ACCEPTED", "PICKUP_CONFIRMED", "ARRIVAL_CONFIRMED")


def case_card_from_status(case: dict[str, Any]) -> Card:
    """Map B's case view to the case card. Status words are copied from B, never derived
    from wording. v2 sends progress_steps; v1 cases fall back to B's evidence flags."""
    if case.get("progress_steps"):
        steps = [(s["step"], bool(s["done"]), s.get("at")) for s in case["progress_steps"]]
    else:
        evidence = case.get("evidence", {})
        steps = [("REQUESTED", case.get("resident_status") not in (None, "UNKNOWN"), None),
                 ("PROVIDER_ACCEPTED", bool(evidence.get("provider_accepted")), None),
                 ("PICKUP_CONFIRMED", bool(evidence.get("pickup_confirmed")), None),
                 ("ARRIVAL_CONFIRMED", bool(evidence.get("arrival_confirmed")), None)]
    card_map = case.get("map") or {}
    return case_card(
        case_id=case["case_id"], display_name=case.get("display_name", case["case_id"]),
        map_color=card_map.get("color"), map_label=card_map.get("label") or case.get("resident_status"),
        zone_status=case.get("zone_status") or case.get("zone_rule"), steps=steps,
        next_step=case.get("next_step"), communication_status=case.get("communication_status"))

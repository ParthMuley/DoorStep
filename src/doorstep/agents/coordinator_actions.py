"""Coordinator actions behind ASI:One commands. Each returns the reply text.

Case state always comes from Developer B's backend; provider capacity always comes from
the independent provider agents over Fetch.ai; eligibility always comes from B's
deterministic matching. Nothing here decides safety or eligibility itself.
"""

from typing import Any

from uagents import Context

from doorstep.agents.provider_client import OfferResult, request_all_offers
from doorstep.workflows.backend_client import (
    BackendError,
    DoorstepBackend,
    destination_requirements,
    transport_requirements,
)

DEMO_ZONE = "zone_3"
SCENARIO_ID = "la_hacks_demo_v1"
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


async def start_readiness_check(correlation_id: str) -> str:
    backend = get_backend()
    try:
        result = await backend.start_demo_warning(DEMO_ZONE, SCENARIO_ID, correlation_id)
    except (BackendError, OSError) as err:
        return backend_unavailable(err)
    if not result.get("verified"):
        return "The alert was not verified as a simulated official warning, so no check-ins were sent."
    lines = [f"Simulated official warning verified for {result['zone_id']}. Check-ins sent (simulated SMS):"]
    for c in result.get("checkins", []):
        lines.append(f"- {c['case_id']}: {c['communication_status']} ({c['language']})")
    lines.append("No resident is assumed to need help until they reply.")
    return "\n".join(lines)


async def case_status(case_id: str, correlation_id: str) -> str:
    try:
        case = await get_backend().get_case_status(case_id, correlation_id)
    except (BackendError, OSError) as err:
        return backend_unavailable(err)
    return case.get("summary_text") or f"{case_id}: resident status {case.get('resident_status')}."


def _format_evaluation(label: str, result: OfferResult, evaluation: dict[str, Any] | None,
                       refusal: str | None) -> list[str]:
    if result.response is None:
        return [f"{label} agent did not answer ({result.status_detail}). Treated as unavailable, not as declined."]
    lines = [f"{label} agent returned {len(result.response.offers)} offers over Fetch.ai."]
    if refusal:
        return lines + [f"{label} matching refused: {refusal}"]
    for e in evaluation.get("eligible", []):
        lines.append(f"  ELIGIBLE #{e.get('rank')}: {e['provider_id']} ({', '.join(e.get('match_reasons', []))})")
    for r in evaluation.get("rejected", []):
        lines.append(f"  not suitable: {r['provider_id']} ({', '.join(r.get('reasons', []))})")
    return lines


async def show_suitable_providers(ctx: Context, case_id: str, correlation_id: str) -> str:
    backend = get_backend()
    try:
        case = await backend.get_case_status(case_id, correlation_id)
    except (BackendError, OSError) as err:
        return backend_unavailable(err)
    name = case.get("display_name", case_id)
    if not case.get("needs_confirmed"):
        return (f"{name}: needs are not confirmed by the resident yet, so I have not asked any provider. "
                f"Communication status: {case.get('communication_status')}.")

    t_req, d_req = transport_requirements(case), destination_requirements(case)
    if t_req is None or d_req is None:
        return f"{name}: the resident has not consented to share transport/destination needs. No provider was contacted."

    transport, destination = await request_all_offers(
        ctx, case_id, case["zone_id"], t_req, d_req, correlation_id)

    evaluations: dict[str, tuple[dict | None, str | None]] = {}
    for label, result, evaluate in (
        ("Transport", transport, backend.evaluate_transport),
        ("Destination", destination, backend.evaluate_destination),
    ):
        if result.response is None:
            evaluations[label] = (None, None)
            continue
        try:
            evaluations[label] = (
                await evaluate(case_id, result.response.request_id, result.response.offers, correlation_id), None)
        except BackendError as err:
            evaluations[label] = (None, f"{err.code} {' '.join(err.reasons)}".strip())
        except OSError as err:
            return backend_unavailable(err)

    lines = [f"{name} ({case_id}), zone rule: {case.get('zone_rule')}."]
    lines += _format_evaluation("Transport", transport, *evaluations["Transport"])
    lines += _format_evaluation("Destination", destination, *evaluations["Destination"])
    t_eval = evaluations["Transport"][0] or {}
    if t_eval.get("escalation_required"):
        lines.append("Ordinary volunteer transport is blocked for this case. It needs simulated authorized "
                     "escalation; assistance is NOT confirmed.")
    else:
        lines.append("Nothing is assigned yet. A provider must accept before any ride is confirmed.")
    return "\n".join(lines)

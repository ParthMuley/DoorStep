"""Resident-status and communication-status transition guards.

A request is not an assignment. An assignment is not a pickup. A pickup is not
an arrival. Each guarded transition demands its own persisted evidence.
"""

from __future__ import annotations

from typing import Optional

from doorstep.models import (
    Assignment,
    CommunicationStatus as C,
    ProviderResponse,
    ResidentStatus as R,
    ServiceStatus,
    ServiceType,
)

from .errors import InvalidTransition
from .safety_rules import assignment_safety_violations

RESIDENT_TRANSITIONS: dict[str, set[str]] = {
    R.UNKNOWN: {R.NEEDS_ASSISTANCE, R.REQUIRES_COORDINATOR},
    R.NEEDS_ASSISTANCE: {R.PROVIDER_ACCEPTED, R.REQUIRES_COORDINATOR},
    # Provider canceling after acceptance sends the case back to NEEDS_ASSISTANCE.
    R.PROVIDER_ACCEPTED: {R.PICKUP_CONFIRMED, R.NEEDS_ASSISTANCE, R.REQUIRES_COORDINATOR},
    R.PICKUP_CONFIRMED: {R.ARRIVAL_CONFIRMED, R.REQUIRES_COORDINATOR},
    R.ARRIVAL_CONFIRMED: set(),
    R.REQUIRES_COORDINATOR: {R.NEEDS_ASSISTANCE},
}

COMMUNICATION_TRANSITIONS: dict[str, set[str]] = {
    C.NOT_SENT: {C.SENT, C.DELIVERY_FAILED, C.REPLIED, C.UNKNOWN},
    C.SENT: {C.DELIVERED, C.DELIVERY_FAILED, C.REPLIED, C.NO_REPLY_AFTER_DEADLINE, C.UNKNOWN},
    C.DELIVERED: {C.REPLIED, C.NO_REPLY_AFTER_DEADLINE},
    # A failed delivery is NOT "no reply": it can only be retried or replied to.
    C.DELIVERY_FAILED: {C.SENT, C.REPLIED},
    C.REPLIED: {C.REPLIED, C.SENT},
    C.NO_REPLY_AFTER_DEADLINE: {C.REPLIED, C.SENT},
    C.UNKNOWN: {C.SENT, C.REPLIED, C.DELIVERED, C.DELIVERY_FAILED},
}


def check_resident_transition(current: str, target: str, assignment: Optional[Assignment] = None) -> None:
    """Raise InvalidTransition unless ``current -> target`` is allowed *and* backed by evidence."""
    if target not in RESIDENT_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"Resident status {current} -> {target} is not allowed")

    if target == R.PROVIDER_ACCEPTED:
        if assignment is None or assignment.service_type != ServiceType.ACCESSIBLE_TRANSPORT:
            raise InvalidTransition("PROVIDER_ACCEPTED requires an accepted transport assignment")
        if assignment.status != ServiceStatus.ACCEPTED or assignment.provider_response != ProviderResponse.ACCEPTED:
            raise InvalidTransition("Assignment has not been accepted by the provider")
        violations = assignment_safety_violations(assignment)
        if violations:
            raise InvalidTransition("Assignment fails the safety gate", reasons=violations)

    elif target == R.PICKUP_CONFIRMED:
        if assignment is None or not assignment.confirmed_pickup_at:
            raise InvalidTransition("PICKUP_CONFIRMED requires recorded pickup evidence")

    elif target == R.ARRIVAL_CONFIRMED:
        if assignment is None or not assignment.confirmed_pickup_at or not assignment.confirmed_arrival_at:
            raise InvalidTransition("ARRIVAL_CONFIRMED requires pickup and arrival evidence")


def check_communication_transition(current: str, target: str) -> None:
    if target not in COMMUNICATION_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"Communication status {current} -> {target} is not allowed")


ACTIVE_ASSIGNMENT_STATES = {ServiceStatus.PROPOSED, ServiceStatus.AWAITING_PROVIDER, ServiceStatus.ACCEPTED}
TERMINAL_ASSIGNMENT_STATES = {ServiceStatus.DECLINED, ServiceStatus.CANCELED, ServiceStatus.COMPLETED,
                              ServiceStatus.UNRESOLVED}

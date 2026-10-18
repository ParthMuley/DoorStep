"""Shared primitives: schema version, enums, envelope base, ID + time helpers.

All IDs are synthetic opaque strings. All timestamps are UTC ISO-8601.
See Doorstep_Two_Developer_Execution_Plan.md Section 2 and master spec Section 4/6.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


def utc_now_iso() -> str:
    """UTC ISO-8601 timestamp with a trailing Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Opaque synthetic id, e.g. ``event_3f1c...``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --- Agreed state enums (plan Section 2 / master spec Section 4) ---


class ResidentStatus(str, Enum):
    NEEDS_ASSISTANCE = "NEEDS_ASSISTANCE"
    PROVIDER_ACCEPTED = "PROVIDER_ACCEPTED"
    PICKUP_CONFIRMED = "PICKUP_CONFIRMED"
    ARRIVAL_CONFIRMED = "ARRIVAL_CONFIRMED"
    REQUIRES_COORDINATOR = "REQUIRES_COORDINATOR"
    UNKNOWN = "UNKNOWN"


class CommunicationStatus(str, Enum):
    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    REPLIED = "REPLIED"
    NO_REPLY_AFTER_DEADLINE = "NO_REPLY_AFTER_DEADLINE"
    UNKNOWN = "UNKNOWN"


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    AWAITING_PROVIDER = "AWAITING_PROVIDER"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"
    UNRESOLVED = "UNRESOLVED"


class ServiceType(str, Enum):
    ACCESSIBLE_TRANSPORT = "accessible_transport"
    ACCESSIBLE_DESTINATION = "accessible_destination"
    RECOVERY_SUPPORT = "recovery_support"


class ZoneRule(str, Enum):
    OUTSIDE_ACTIVE_ORDER = "OUTSIDE_ACTIVE_ORDER"
    INSIDE_ACTIVE_ORDER = "INSIDE_ACTIVE_ORDER"
    UNVERIFIED = "UNVERIFIED"


class ProviderResponse(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class EscalationStatus(str, Enum):
    # A simulated acknowledgment means ONLY "request received" -- never dispatch.
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED_REQUEST_ONLY = "ACKNOWLEDGED_REQUEST_ONLY"
    NO_ACKNOWLEDGMENT = "NO_ACKNOWLEDGMENT"


class Language(str, Enum):
    EN = "en"
    ES = "es"


class DoorstepModel(BaseModel):
    """Base model: strict validation, enum values serialized as their value."""

    model_config = ConfigDict(use_enum_values=True, extra="forbid", validate_default=True, validate_assignment=True)


class Envelope(DoorstepModel):
    """Common envelope fields carried on messages/events where relevant."""

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: new_id("event"))
    correlation_id: str = Field(default_factory=lambda: new_id("corr"))
    created_at: str = Field(default_factory=utc_now_iso)


class ResponseIntent(str, Enum):
    """Parsed resident reply to the check-in. Self-reported, never verified."""

    NEED_HELP = "NEED_HELP"
    HAS_PLAN = "HAS_PLAN"
    ALREADY_LEFT = "ALREADY_LEFT"
    CALL_ME = "CALL_ME"
    CONFIRM_YES = "CONFIRM_YES"
    CONFIRM_NO = "CONFIRM_NO"
    PICKUP_CONFIRMED = "PICKUP_CONFIRMED"  # resident/caregiver texts PICKED UP / RECOGIDO
    UNPARSED = "UNPARSED"


class EvidenceParty(str, Enum):
    RESIDENT = "resident"
    CAREGIVER = "caregiver"
    VOLUNTEER = "volunteer"
    SHELTER = "shelter"
    TRANSPORT_PROVIDER = "transport_provider"
    DESTINATION_PROVIDER = "destination_provider"


class EscalationReason(str, Enum):
    ACTIVE_EVACUATION_ORDER_ZONE = "ACTIVE_EVACUATION_ORDER_ZONE"
    NO_ELIGIBLE_PROVIDER = "NO_ELIGIBLE_PROVIDER"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    NO_REPLY_AFTER_DEADLINE = "NO_REPLY_AFTER_DEADLINE"
    NO_AVAILABLE_VOLUNTEER = "NO_AVAILABLE_VOLUNTEER"
    NO_SUITABLE_VOLUNTEER = "NO_SUITABLE_VOLUNTEER"
    VOLUNTEER_TIMEOUT = "VOLUNTEER_TIMEOUT"
    COORDINATOR_REQUESTED = "COORDINATOR_REQUESTED"


class ReferralStatus(str, Enum):
    # A referral is NOT completed assistance; COMPLETED needs evidence.
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    UNRESOLVED = "UNRESOLVED"


class MessageDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


def map_color(status: "ResidentStatus | str") -> tuple[str, str]:
    """(color, accessible text label) for a resident status. Green == arrival only."""
    value = status.value if isinstance(status, Enum) else status
    return {
        "NEEDS_ASSISTANCE": ("red", "Assistance needed"),
        "PROVIDER_ACCEPTED": ("yellow", "Provider accepted (not yet picked up)"),
        "PICKUP_CONFIRMED": ("blue", "Pickup confirmed (not yet arrived)"),
        "ARRIVAL_CONFIRMED": ("green", "Arrival confirmed at agreed destination"),
        "REQUIRES_COORDINATOR": ("black", "Coordinator attention: assistance not confirmed"),
        "UNKNOWN": ("gray", "Status unknown"),
    }[value]

"""Timeline and evidence models: status events, messages, verification,
escalation, and recovery referral.

Every displayed state must be explainable from these persisted records.
Event ``data`` holds ids and statuses only -- no message bodies or needs.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from .common import (
    SCHEMA_VERSION,
    CommunicationStatus,
    DoorstepModel,
    EscalationReason,
    EscalationStatus,
    EvidenceParty,
    Language,
    MessageDirection,
    ReferralStatus,
    new_id,
    utc_now_iso,
)


class StatusEvent(DoorstepModel):
    """One entry in the append-only, replayable case timeline."""

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: new_id("event"))
    seq: Optional[int] = None  # assigned by the event log on insert
    case_id: Optional[str] = None
    correlation_id: str = ""
    event_type: str
    actor: str = "system"
    # For RESIDENT_STATUS_CHANGED / COMMUNICATION_STATUS_CHANGED events.
    dimension: Optional[str] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class MessageEvent(DoorstepModel):
    """A simulated SMS. Every outbound body starts with ``DOORSTEP DEMO``."""

    schema_version: str = SCHEMA_VERSION
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    case_id: Optional[str] = None
    direction: MessageDirection
    channel: str = "simulator"
    sender: str
    recipient: str
    body: str
    language: Language = Language.EN
    # Inbound dedup key (provider message id). Unique per inbound message.
    external_id: Optional[str] = None
    status: CommunicationStatus = CommunicationStatus.SENT
    template_id: Optional[str] = None
    correlation_id: str = ""
    simulated: bool = True
    created_at: str = Field(default_factory=utc_now_iso)


class Confirmation(DoorstepModel):
    """One identified party's confirmation (proposed contract v1.1)."""

    party: EvidenceParty
    party_id: str


class Evidence(DoorstepModel):
    """Pickup / arrival evidence (contract v1.0 sections 3.8-3.9).

    A one-time code helps confirm contact; it never proves safety.
    ``confirmations`` (party ids) is optional; when present every id is checked.
    """

    type: str  # v1: PROVIDER_AND_RESIDENT_CONFIRMATION | DESTINATION_CHECKIN
    #            v2: VOLUNTEER_AND_RESIDENT_CONFIRMATION | SHELTER_CHECKIN
    provider_confirmed: bool = False
    volunteer_confirmed: bool = False
    shelter_confirmed: bool = False
    shelter_org_id: Optional[str] = None
    site_id: Optional[str] = None
    report_id: Optional[str] = None
    resident_confirmed: bool = False
    caregiver_confirmed: bool = False
    code_verified: bool = False
    destination_provider_id: Optional[str] = None
    source: str = "SIMULATED"
    confirmations: list[Confirmation] = Field(default_factory=list)


class VerificationEvent(DoorstepModel):
    schema_version: str = SCHEMA_VERSION
    verification_id: str = Field(default_factory=lambda: new_id("verif"))
    case_id: str
    assignment_id: str
    kind: str  # "pickup" | "arrival"
    evidence: Evidence
    party_ids_verified: bool = False  # True only when identified confirmations were checked
    correlation_id: str = ""
    created_at: str = Field(default_factory=utc_now_iso)


class Escalation(DoorstepModel):
    """Simulated escalation. Acknowledgment means ONLY 'request received'."""

    schema_version: str = SCHEMA_VERSION
    escalation_id: str = Field(default_factory=lambda: new_id("esc"))
    case_id: str
    reason: EscalationReason
    recipient: str = "SIMULATED_AUTHORIZED_RESPONSE_SERVICE"
    status: EscalationStatus = EscalationStatus.NO_ACKNOWLEDGMENT
    assistance_confirmed: bool = False  # never set True by an acknowledgment
    idempotency_key: str = ""
    correlation_id: str = ""
    simulated: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    acknowledged_at: Optional[str] = None


class RecoveryReferral(DoorstepModel):
    """Consent-scoped recovery request. Not housing secured, not assistance done."""

    schema_version: str = SCHEMA_VERSION
    referral_id: str = Field(default_factory=lambda: new_id("ref"))
    case_id: str
    provider_id: str = "recovery_org_demo"
    status: ReferralStatus = ReferralStatus.REQUESTED
    # Exactly what was shared with the recovery provider (and nothing more).
    shared_fields: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""
    correlation_id: str = ""
    simulated: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: Optional[str] = None

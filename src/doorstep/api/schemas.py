"""Request bodies for docs/interface-contract.md v1.0. Unknown fields are rejected."""

from __future__ import annotations

from typing import Literal, Optional

from doorstep.models import (
    Consent,
    DestinationOfferIn,
    DoorstepModel,
    EscalationReason,
    Evidence,
    Language,
    Resident,
    TransportOfferIn,
)


class Body(DoorstepModel):
    schema_version: str = "1.0"
    correlation_id: Optional[str] = None


class WarningBody(Body):
    zone_id: str
    scenario_id: Optional[str] = None
    alert_source: str = "SIMULATED_OFFICIAL"


class RegisterResidentBody(Body):
    profile: Resident
    consent: Optional[Consent] = None


class ResponseBody(Body):
    text: str
    sender: str
    language: Optional[Language] = None
    # Optional dedup key for repeated deliveries of the same inbound message.
    external_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class TransportEvaluateBody(Body):
    request_id: Optional[str] = None
    service_type: Literal["accessible_transport"] = "accessible_transport"
    candidate_offers: list[TransportOfferIn]


class DestinationEvaluateBody(Body):
    request_id: Optional[str] = None
    service_type: Literal["accessible_destination"] = "accessible_destination"
    candidate_offers: list[DestinationOfferIn]


class ProposeBody(Body):
    transport_offer_id: Optional[str] = None
    destination_offer_id: Optional[str] = None
    authorization: str = "SIMULATED_PREAPPROVED"
    idempotency_key: Optional[str] = None


class AcceptanceBody(Body):
    provider_id: str
    provider_agent_address: Optional[str] = None
    decision: Literal["ACCEPTED", "DECLINED"]
    idempotency_key: Optional[str] = None


class EvidenceBody(Body):
    evidence: Evidence
    idempotency_key: Optional[str] = None


class RecoveryConsent(DoorstepModel):
    share_recovery_needs: bool
    granted_by: str  # "RESIDENT" | "CAREGIVER" (or the party id)
    granted_at: Optional[str] = None


class RecoveryBody(Body):
    consent: RecoveryConsent
    idempotency_key: Optional[str] = None


class RecoveryResponseBody(Body):
    provider_id: str
    decision: Literal["ACCEPTED", "DECLINED"]


class EscalateBody(Body):
    reason: EscalationReason
    idempotency_key: Optional[str] = None


class InboundSmsBody(Body):
    sender: str
    text: str
    external_id: Optional[str] = None
    language: Optional[Language] = None


class DeliveryBody(Body):
    message_id: str
    delivered: bool


class EscalationAckBody(Body):
    acknowledge: bool

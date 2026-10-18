"""Request bodies for docs/interface-contract.md v1.0. Unknown fields are rejected."""

from __future__ import annotations

from typing import Any, Literal, Optional

from doorstep.models import (
    DestinationOfferIn,
    DoorstepModel,
    EscalationReason,
    Evidence,
    Language,
    Organization,
    Region,
    ResidentProfile,
    ShelterSite,
    TransportOfferIn,
    Volunteer,
)


class Body(DoorstepModel):
    schema_version: str = "1.0"
    correlation_id: Optional[str] = None


class WarningBody(Body):
    zone_id: str
    scenario_id: Optional[str] = None
    alert_source: str = "SIMULATED_OFFICIAL"


class RegisterResidentBody(Body):
    resident: ResidentProfile


class RegisterOrganizationBody(Body):
    organization: Organization


class AddVolunteerBody(Body):
    volunteer: Volunteer


class RegionBody(Body):
    region: Region


class SiteBody(Body):
    site: ShelterSite


class AvailabilityBody(Body):
    org_id: str
    available: bool
    responded_at: Optional[str] = None
    idempotency_key: Optional[str] = None


class AgentAddressBody(Body):
    agent_address: str


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


# ---- contract v2.0 §5.3 / §5.4 (alerts + outreach) ----
class FeedSource(DoorstepModel):
    source_id: str
    source_type: Literal["OFFICIAL_SIMULATION", "REAL_WORLD"]
    url: Optional[str] = None
    fetched_at: Optional[str] = None


class AlertIngestBody(Body):
    source: FeedSource
    fetch_ok: bool = True
    http_status: Optional[int] = None
    error: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    idempotency_key: Optional[str] = None


class AlertTriggerBody(Body):
    action: Literal["ISSUE", "UPDATE", "CANCEL", "EXPIRE", "FREEZE_FEED", "UNFREEZE_FEED"]
    preset: Optional[str] = None
    zone_id: Optional[str] = None
    status: Optional[str] = None  # raw Cal OES string, e.g. "Evacuation Order"
    event_type: Optional[str] = None
    geometry: Optional[dict[str, Any]] = None
    expires_in_minutes: Optional[int] = None
    freeze_age_minutes: int = 0  # FREEZE_FEED: backdate the frozen timestamp (demo staleness)
    poll_now: bool = False


class OutreachBody(Body):
    idempotency_key: Optional[str] = None
    max_orgs: Optional[int] = None


# ---- contract v2.0 §5.6 / §5.7 (matching, acceptance, escalation) ----
class MatchSelect(DoorstepModel):
    volunteer_id: Optional[str] = None
    site_id: Optional[str] = None


class ProposeMatchBody(Body):
    case_id: str
    idempotency_key: Optional[str] = None
    create_proposal: bool = True
    authorization: str = "SIMULATED_PREAPPROVED"
    select: Optional[MatchSelect] = None


class AcceptV2Body(Body):
    org_id: str
    volunteer_id: Optional[str] = None
    site_id: Optional[str] = None
    decision: Literal["ACCEPTED", "DECLINED"]
    idempotency_key: Optional[str] = None


class EscalationAckBodyV2(Body):
    status: Literal["ACKNOWLEDGED_REQUEST_ONLY", "NO_ACKNOWLEDGMENT"]
    recipient_agent_address: Optional[str] = None
    idempotency_key: Optional[str] = None

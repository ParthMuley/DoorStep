"""Request bodies for docs/interface-contract.md v1.0. Unknown fields are rejected."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import field_validator

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
    sender: Optional[str] = None  # v2.2: the volunteer's linked ASI:One address, if the answer came from ASI:One


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


class ClosureTriggerBody(Body):
    action: Literal["PUBLISH_OFFICIAL", "LIFT_OFFICIAL", "PUBLISH_NEWS"]
    road_name: str
    status: str = "CLOSED"
    headline: Optional[str] = None
    body: Optional[str] = None
    expires_in_minutes: int = 360


class ClosureSource(DoorstepModel):
    source_id: str
    source_type: Literal["OFFICIAL_SIMULATION", "NEWS", "REAL_WORLD_CONTEXT"]
    url: Optional[str] = None
    fetched_at: Optional[str] = None


class ClosureCandidate(DoorstepModel):
    road_name: Optional[str] = None
    claimed_status: Optional[str] = None
    location_text: Optional[str] = None


class ClosureItem(DoorstepModel):
    source_item_id: str
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None
    url: Optional[str] = None
    headline: Optional[str] = None
    raw_text: Optional[str] = None
    extraction_method: Literal["STRUCTURED_FEED", "ASI_ONE_EXTRACTION", "KEYWORD_EXTRACTION"] = "STRUCTURED_FEED"
    candidate: ClosureCandidate


class ClosureIngestBody(Body):
    source: ClosureSource
    items: list[ClosureItem]
    idempotency_key: Optional[str] = None


class RouteConstraintsBody(Body):
    assignment_id: str
    idempotency_key: Optional[str] = None


class RoutePreviewBody(Body):
    route_request_id: str
    provider: str = "HERE"
    polyline: Optional[dict[str, Any]] = None
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None
    provider_notices: list[Any] = []
    computed_at: Optional[str] = None
    idempotency_key: Optional[str] = None


class RecoveryV2Body(Body):
    consent: RecoveryConsent
    help_types: list[str]
    idempotency_key: Optional[str] = None


class RecoveryRespondBody(Body):
    org_id: str
    decision: Literal["ACCEPTED", "DECLINED", "COMPLETED"]
    evidence: Optional[dict[str, Any]] = None
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
    # Optional drive times (minutes) per volunteer_id, e.g. from HERE via the Matching agent.
    # Re-orders eligible volunteers only; never changes eligibility (contract v2.2 §5.6).
    drive_minutes: Optional[dict[str, float]] = None

    @field_validator("drive_minutes")
    @classmethod
    def _drive(cls, v: Optional[dict[str, float]]) -> Optional[dict[str, float]]:
        if v is None:
            return v
        if len(v) > 200:
            raise ValueError("drive_minutes: at most 200 volunteers")
        for vid, minutes in v.items():
            if not (minutes == minutes and 0 <= minutes <= 600):  # rejects NaN, negatives, > 10 h
                raise ValueError(f"drive_minutes[{vid}] must be between 0 and 600")
        return v


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


# ---- contract v2.2: ASI:One linking, registration, invites, approval, deadlines (plan rev 4-6)
class LinkBody(Body):
    code: str
    asi_one_address: str


class UnlinkBody(Body):
    asi_one_address: str


class RegisterBody(Body):
    role: Literal["RESIDENT", "VOLUNTEER"]
    asi_one_address: str
    profile: dict[str, Any]
    org_id: Optional[str] = None


class InviteBody(Body):
    volunteer_id: str
    display_name: Optional[str] = None


class ApproveBody(Body):
    approved: bool = True


class SweepBody(Body):
    pass

"""Request bodies for the HTTP contract (Pydantic-validated)."""

from __future__ import annotations

from typing import Optional

from doorstep.models import Consent, DoorstepModel, EscalationReason, Evidence, Language, Needs, Resident


class WarningBody(DoorstepModel):
    zone_id: str
    scenario_id: Optional[str] = None
    correlation_id: Optional[str] = None


class ReportBody(DoorstepModel):
    zone_id: str
    text: str
    reporter: str = "public"


class RegisterResidentBody(DoorstepModel):
    profile: Resident
    consent: Optional[Consent] = None


class ResponseBody(DoorstepModel):
    text: str
    sender: str  # must be the resident's or caregiver's synthetic channel
    language: Optional[Language] = None
    external_id: Optional[str] = None  # inbound dedup key
    correlation_id: Optional[str] = None


class ConfirmNeedsBody(DoorstepModel):
    confirmed: bool
    confirmed_by: str  # resident_id or caregiver_id
    needs: Optional[Needs] = None
    correlation_id: Optional[str] = None


class FindBody(DoorstepModel):
    case_id: str
    correlation_id: Optional[str] = None


class ProposeBody(DoorstepModel):
    case_id: str
    offer_id: str
    correlation_id: Optional[str] = None


class ProviderResponseBody(DoorstepModel):
    provider_id: str
    accept: bool = True
    correlation_id: Optional[str] = None


class EvidenceBody(DoorstepModel):
    evidence: Evidence
    correlation_id: Optional[str] = None


class RecoveryBody(DoorstepModel):
    consent: bool
    granted_by: str  # resident_id or caregiver_id
    correlation_id: Optional[str] = None


class EscalateBody(DoorstepModel):
    reason: EscalationReason
    correlation_id: Optional[str] = None


class InboundSmsBody(DoorstepModel):
    sender: str
    text: str
    external_id: Optional[str] = None
    language: Optional[Language] = None


class DeliveryBody(DoorstepModel):
    message_id: str
    delivered: bool


class EscalationAckBody(DoorstepModel):
    acknowledge: bool

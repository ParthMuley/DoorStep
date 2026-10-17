"""Case aggregate and the alert that activates a check-in."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .common import (
    SCHEMA_VERSION,
    CommunicationStatus,
    DoorstepModel,
    ResidentStatus,
    ResponseIntent,
    new_id,
)
from .resident import Consent, Needs


class AlertEvent(DoorstepModel):
    """A simulated official warning. Only officially-verified alerts activate.

    A user report creates ``official_verified=False`` and stays report-only.
    """

    schema_version: str = SCHEMA_VERSION
    alert_id: str = Field(default_factory=lambda: new_id("alert"))
    zone_id: str
    official_verified: bool
    scenario_id: Optional[str] = None
    simulated: bool = True
    message: str = ""
    created_at: Optional[str] = None


class Case(DoorstepModel):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    resident_id: str
    zone_id: str
    sector_id: Optional[str] = None
    scenario_id: Optional[str] = None
    needs: Needs = Field(default_factory=Needs)
    consent: Consent = Field(default_factory=Consent)
    # Silence is not evidence of anything: a new case starts UNKNOWN.
    resident_status: ResidentStatus = ResidentStatus.UNKNOWN
    communication_status: CommunicationStatus = CommunicationStatus.NOT_SENT
    response_intent: Optional[ResponseIntent] = None
    # Needs extracted from free text wait here until the resident confirms.
    pending_candidate_needs: Optional[Needs] = None
    needs_confirmed: bool = False
    next_step: str = ""
    correlation_id: str = ""
    alert_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    simulated: bool = True

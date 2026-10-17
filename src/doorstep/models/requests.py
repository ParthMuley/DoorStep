"""Service requests and provider offers passed across the agent boundary."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .common import (
    SCHEMA_VERSION,
    DoorstepModel,
    ServiceStatus,
    ServiceType,
    new_id,
)


class TransportRequirements(DoorstepModel):
    wheelchair_accessible_vehicle: bool = False
    transfer_assistance: bool = False
    portable_oxygen_equipment: bool = False
    pet_count: int = 0
    service_animal: bool = False


class DestinationRequirements(DoorstepModel):
    step_free_entry: bool = False
    accessible_restroom: bool = False
    pets_allowed: bool = False
    service_animal: bool = False
    oxygen_friendly: bool = False
    capacity_needed: int = 1


class ServiceRequest(DoorstepModel):
    schema_version: str = SCHEMA_VERSION
    request_id: str = Field(default_factory=lambda: new_id("req"))
    case_id: str
    service_type: ServiceType
    zone_id: str
    # One of the requirement blocks is populated depending on service_type.
    transport_requirements: Optional[TransportRequirements] = None
    destination_requirements: Optional[DestinationRequirements] = None
    status: ServiceStatus = ServiceStatus.AWAITING_PROVIDER
    idempotency_key: str


class Offer(DoorstepModel):
    """A provider's eligible offer. Consent-scoped; never a confirmed reservation."""

    schema_version: str = SCHEMA_VERSION
    offer_id: str = Field(default_factory=lambda: new_id("offer"))
    request_id: str
    case_id: str
    provider_id: str
    service_type: ServiceType
    eligible: bool
    reasons: list[str] = Field(default_factory=list)  # why eligible / rejected
    # Non-safety ranking hints only (availability, distance within safe area).
    estimated_distance_km: Optional[float] = None

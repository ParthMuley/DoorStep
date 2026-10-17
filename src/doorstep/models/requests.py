"""Service requests and provider offers passed across the agent boundary."""

from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict, Field

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


class TransportOfferIn(DoorstepModel):
    """Raw offer from a Transport provider agent (contract v1.0 section 3.4).

    Extra provider fields (e.g. ``approved_by_partner``, ``base_node``) are
    IGNORED, never trusted: approval and location come from B's registry.
    """

    model_config = ConfigDict(extra="ignore")

    offer_id: str
    provider_id: str
    provider_agent_address: Optional[str] = None
    vehicle_id: Optional[str] = None
    wheelchair_accessible: bool = False
    transfer_assistance: bool = False
    oxygen_handling: bool = False
    pets_allowed: bool = False
    service_animals_allowed: Optional[bool] = None  # not in v1.0; None == unknown
    seats_available: int = 0
    wheelchair_spaces_available: int = 0
    service_area_zones: list[str] = Field(default_factory=list)
    eta_minutes: Optional[int] = None
    valid_until: Optional[str] = None
    base_zone: Optional[str] = None  # proposed v1.1; registry value used if absent


class DestinationOfferIn(DoorstepModel):
    """Raw offer from a Destination provider agent (contract v1.0 section 3.5).
    Extra provider fields are ignored, never trusted."""

    model_config = ConfigDict(extra="ignore")

    offer_id: str
    provider_id: str
    provider_agent_address: Optional[str] = None
    destination_id: Optional[str] = None
    step_free_entry: bool = False
    accessible_restroom: bool = False
    pets_allowed: bool = False
    service_animals_allowed: bool = True
    beds_available: int = 0
    oxygen_power_outlets: bool = False
    valid_until: Optional[str] = None
    zone_id: Optional[str] = None  # registry value used if absent


class Offer(DoorstepModel):
    """An offer after B's deterministic evaluation. Never a confirmed reservation."""

    schema_version: str = SCHEMA_VERSION
    offer_id: str
    request_id: str
    case_id: str
    provider_id: str
    service_type: ServiceType
    eligible: bool
    rank: Optional[int] = None
    reasons: list[str] = Field(default_factory=list)  # rejection codes
    match_reasons: list[str] = Field(default_factory=list)
    # Non-safety ranking hints only.
    eta_minutes: Optional[int] = None
    estimated_distance_km: Optional[float] = None
    raw: dict = Field(default_factory=dict)  # provider's raw offer, re-checked at proposal

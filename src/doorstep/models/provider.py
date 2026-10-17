"""Provider, vehicle capability, and destination models (synthetic inventories).

Providers are preapproved by a fictional partner organization -- NOT verified by
an LLM. Each provider agent keeps its own inventory; the coordinator DB never
stores provider-private rows.
"""

from __future__ import annotations

from pydantic import Field

from .common import DoorstepModel, ServiceType


class VehicleCapability(DoorstepModel):
    wheelchair_accessible: bool = False
    transfer_assistance: bool = False
    oxygen_equipment_handling: bool = False
    seating_capacity: int = 0
    pet_capacity: int = 0
    service_animal_ok: bool = False


class TransportProvider(DoorstepModel):
    provider_id: str
    display_name: str
    service_type: ServiceType = ServiceType.ACCESSIBLE_TRANSPORT
    approved: bool = True  # preapproved by fictional partner org
    service_area_zones: list[str] = Field(default_factory=list)
    # Zones this provider will NOT enter (e.g. active evacuation-order zones).
    restricted_zones: list[str] = Field(default_factory=list)
    vehicle: VehicleCapability = Field(default_factory=VehicleCapability)
    base_zone: str = ""  # synthetic graph node the vehicle starts from
    available: bool = True
    available_trips: int = 1  # capacity: trips it can still accept
    simulated: bool = True


class Destination(DoorstepModel):
    provider_id: str
    display_name: str
    service_type: ServiceType = ServiceType.ACCESSIBLE_DESTINATION
    approved: bool = True
    zone_id: str = ""  # where the destination physically sits
    step_free_entry: bool = False
    accessible_restroom: bool = False
    pets_allowed: bool = False
    service_animal_ok: bool = True
    oxygen_friendly: bool = False
    total_capacity: int = 0
    available_capacity: int = 0
    simulated: bool = True


class Organization(DoorstepModel):
    """Fictional partner organization that preapproves providers."""

    organization_id: str
    display_name: str
    role: str  # "community_support" | "transport" | "destination" | "recovery"
    simulated: bool = True

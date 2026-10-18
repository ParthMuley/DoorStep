"""Contract v2.0 registration documents (the two MongoDB databases).

* ``ResidentProfile`` → ``doorstep_users.residents``
* ``Organization`` with embedded ``Volunteer`` / ``ShelterSite`` → ``doorstep_orgs.organizations``

All people, organizations and addresses are fictional (synthetic demo data).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, field_validator, model_validator

from .common import DoorstepModel
from .needs import validate_codes


class Address(DoorstepModel):
    label: str  # synthetic, e.g. "SYNTHETIC: 12 Example Way"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    geocode_confidence: str = "HIGH"  # HIGH | LOW | FAILED (LOW/FAILED -> zone UNKNOWN)

    @field_validator("geocode_confidence")
    @classmethod
    def _confidence(cls, v: str) -> str:
        v = v.upper()
        if v not in ("HIGH", "LOW", "FAILED"):
            raise ValueError("geocode_confidence must be HIGH, LOW or FAILED")
        return v


class Location(DoorstepModel):
    label: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class GeoPoint(DoorstepModel):
    """GeoJSON Point; coordinates are [lon, lat]."""

    type: str = "Point"
    coordinates: list[float]

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v != "Point":
            raise ValueError("location must be a GeoJSON Point")
        return v

    @field_validator("coordinates")
    @classmethod
    def _coords(cls, v: list[float]) -> list[float]:
        if len(v) != 2 or not (-180 <= v[0] <= 180) or not (-90 <= v[1] <= 90):
            raise ValueError("coordinates must be [lon, lat]")
        return v

    @property
    def lon(self) -> float:
        return self.coordinates[0]

    @property
    def lat(self) -> float:
        return self.coordinates[1]


def point(lat: float, lon: float) -> GeoPoint:
    return GeoPoint(coordinates=[lon, lat])


class EmergencyContact(DoorstepModel):
    contact_id: Optional[str] = None  # assigned by B if missing
    name: str
    phone: str  # simulator id, e.g. "sim_phone_ana"
    relationship: str = ""


PURPOSES = ("CHECKIN", "TRANSPORT", "DESTINATION", "RECOVERY")


class ResidentProfile(DoorstepModel):
    resident_id: Optional[str] = None  # assigned by B if missing
    name: str
    phone: str
    language: str = "en"
    address: Address
    emergency_contacts: list[EmergencyContact] = Field(default_factory=list)
    needs: list[int] = Field(default_factory=list)
    pet_count: int = Field(default=0, ge=0)
    wants_help_contact: bool = True
    consents: dict[str, bool] = Field(default_factory=lambda: {p: False for p in PURPOSES})
    registered_at: Optional[str] = None
    simulated: bool = True

    @field_validator("needs")
    @classmethod
    def _needs(cls, v: list[int]) -> list[int]:
        return validate_codes(v)

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        return v if v in ("en", "es") else "en"

    @model_validator(mode="after")
    def _consents(self) -> "ResidentProfile":
        unknown = set(self.consents) - set(PURPOSES)
        if unknown:
            raise ValueError(f"Unknown consent purposes {sorted(unknown)}")
        full = {p: bool(self.consents.get(p, False)) for p in PURPOSES}
        if not self.wants_help_contact:
            full["CHECKIN"] = False  # never contacted if they opted out
        object.__setattr__(self, "consents", full)
        if self.pet_count and 4 not in self.needs:
            object.__setattr__(self, "needs", sorted(set(self.needs) | {4}))
        return self


class CalamityType(str, Enum):
    WILDFIRE = "WILDFIRE"
    FLOOD = "FLOOD"
    EARTHQUAKE = "EARTHQUAKE"
    STORM = "STORM"
    HEAT = "HEAT"
    OTHER = "OTHER"
    ANY = "ANY"  # org helps with every calamity type


class OrgService(str, Enum):
    TRANSPORT = "TRANSPORT"
    SHELTER = "SHELTER"
    RECOVERY_HOUSING = "RECOVERY_HOUSING"
    INSURANCE_GUIDANCE = "INSURANCE_GUIDANCE"
    SUPPLIES = "SUPPLIES"
    MEDICAL_EQUIPMENT_REPLACEMENT = "MEDICAL_EQUIPMENT_REPLACEMENT"
    CASEWORK = "CASEWORK"


class RecoveryHelpType(str, Enum):
    """What a resident can ask for after evacuation (contract v2.0 §2 recovery help_type)."""
    TEMPORARY_HOUSING = "TEMPORARY_HOUSING"
    INSURANCE_GUIDANCE = "INSURANCE_GUIDANCE"
    SUPPLIES = "SUPPLIES"
    MEDICAL_EQUIPMENT_REPLACEMENT = "MEDICAL_EQUIPMENT_REPLACEMENT"
    CASEWORK = "CASEWORK"


class AvailabilityState(str, Enum):
    UNASKED = "UNASKED"
    ASKED = "ASKED"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NO_REPLY = "NO_REPLY"


class VolunteerAvailability(DoorstepModel):
    alert_id: str
    state: AvailabilityState
    responded_at: Optional[str] = None


class Volunteer(DoorstepModel):
    volunteer_id: str
    name: str
    phone: str
    location: GeoPoint  # where the volunteer is (decides their region)
    vehicle_type: str = "SEDAN"  # free label: WHEELCHAIR_VAN, MINIVAN, SEDAN, SUV, BUS
    vehicle_seats: int = Field(default=1, ge=0)
    wheelchair_spaces: int = Field(default=0, ge=0)
    pet_capacity: int = Field(default=0, ge=0)
    needs_they_can_cater: list[int] = Field(default_factory=list)
    approved: bool = False  # simulated partner preapproval, never decided by an LLM
    availability: Optional[VolunteerAvailability] = None  # per alert; set by outreach / answers
    reserved_case_id: Optional[str] = None
    simulated: bool = True

    @field_validator("needs_they_can_cater")
    @classmethod
    def _caps(cls, v: list[int]) -> list[int]:
        return validate_codes(v)


class ShelterSite(DoorstepModel):
    site_id: str
    name: str
    location: GeoPoint
    beds_available: int = Field(default=0, ge=0)
    features: list[int] = Field(default_factory=list)

    @field_validator("features")
    @classmethod
    def _features(cls, v: list[int]) -> list[int]:
        return validate_codes(v)


class Organization(DoorstepModel):
    """Canonical org record (doorstep_partners.organizations). No volunteers here:
    they live in the region where they are (plan rev 3)."""

    org_id: str
    name: str
    calamity_types: list[CalamityType] = Field(default_factory=list)
    services: list[OrgService] = Field(default_factory=list)
    approved: bool = False  # simulated partner preapproval, never decided by an LLM
    service_radius_km: float = Field(default=25, gt=0)
    recovery_services: list[RecoveryHelpType] = Field(default_factory=list)
    simulated: bool = True


ORG_FACT_FIELDS = ("name", "calamity_types", "services", "approved", "service_radius_km", "recovery_services")


class RegionOrg(DoorstepModel):
    """An org's presence in ONE region: a copy of its canonical facts plus only
    the volunteers and shelter sites located in that region."""

    org_id: str
    name: str
    calamity_types: list[CalamityType] = Field(default_factory=list)
    services: list[OrgService] = Field(default_factory=list)
    approved: bool = False
    service_radius_km: float = Field(default=25, gt=0)
    recovery_services: list[RecoveryHelpType] = Field(default_factory=list)
    volunteers: list[Volunteer] = Field(default_factory=list)
    shelter_sites: list[ShelterSite] = Field(default_factory=list)

    @classmethod
    def from_org(cls, org: Organization) -> "RegionOrg":
        return cls(org_id=org.org_id, **{f: getattr(org, f) for f in ORG_FACT_FIELDS})


class Region(DoorstepModel):
    """doorstep_partners.regions: one document per area (location-first)."""

    region_id: str
    label: str
    center: GeoPoint
    area: dict  # GeoJSON Polygon
    orgs: list[RegionOrg] = Field(default_factory=list)
    simulated: bool = True

    @field_validator("area")
    @classmethod
    def _area(cls, v: dict) -> dict:
        if v.get("type") != "Polygon" or not v.get("coordinates"):
            raise ValueError("area must be a GeoJSON Polygon")
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> "Region":
        oids = [o.org_id for o in self.orgs]
        if len(oids) != len(set(oids)):
            raise ValueError("Duplicate org_id in region")
        vids = [v.volunteer_id for o in self.orgs for v in o.volunteers]
        if len(vids) != len(set(vids)):
            raise ValueError("Duplicate volunteer_id in region")
        return self

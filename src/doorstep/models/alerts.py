"""Contract v2.0 alert models: normalized evacuation-zone alerts, feed state,
awareness incidents. Real-world (live) alerts are display-only."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import Field

from .common import DoorstepModel


class AlertStatus(str, Enum):
    ORDER = "ORDER"
    WARNING = "WARNING"
    SHELTER_IN_PLACE = "SHELTER_IN_PLACE"
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"


class ZoneStatus(str, Enum):
    ORDER = "ORDER"
    WARNING = "WARNING"
    SHELTER_IN_PLACE = "SHELTER_IN_PLACE"
    OUTSIDE_KNOWN_ZONES = "OUTSIDE_KNOWN_ZONES"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


class Verification(str, Enum):
    OFFICIAL_SIMULATION = "OFFICIAL_SIMULATION"
    OFFICIAL_LIVE_DISPLAY_ONLY = "OFFICIAL_LIVE_DISPLAY_ONLY"


class SourceType(str, Enum):
    OFFICIAL_SIMULATION = "OFFICIAL_SIMULATION"  # synthetic feed: may trigger check-ins and outreach
    REAL_WORLD = "REAL_WORLD"                    # live Cal OES: display-only


class ZoneAlert(DoorstepModel):
    """One normalized evacuation-zone record from a feed."""

    alert_id: str
    source_id: str
    source_type: SourceType
    source_record_id: str
    source_url: Optional[str] = None
    version: int = 0  # EDIT_DATE (epoch ms) of the record
    status: AlertStatus
    raw_status: str
    calamity_type: str = "UNKNOWN"
    raw_event_type: Optional[str] = None
    zone_id: str
    zone_name: str = ""
    county: str = ""
    geometry: dict[str, Any]
    public_info: str = ""
    issued_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None
    fetched_at: Optional[str] = None
    verification: Verification
    is_simulation: bool
    active: bool = True
    missed_polls: int = 0  # consecutive successful ingests without this record
    canceled_at: Optional[str] = None
    cancel_reason: Optional[str] = None


class FeedState(DoorstepModel):
    source_id: str
    source_type: SourceType
    url: Optional[str] = None
    last_ingest_at: Optional[str] = None
    last_success_at: Optional[str] = None
    source_updated_at: Optional[str] = None  # STATEWIDE_LAST_UPDATED / latest EDIT_DATE
    consecutive_failures: int = 0


class IncidentPoint(DoorstepModel):
    """Awareness only: a radius around an incident never activates the evacuation flow."""

    incident_id: str
    calamity_type: str
    lat: float
    lon: float
    radius_km: float
    label: str = ""
    active: bool = True


class SyntheticFeature(DoorstepModel):
    """One record of B's synthetic feed (rendered in the exact Cal OES shape)."""

    object_id: int
    global_id: str
    zone_id: str
    zone_name: str
    status: str  # raw Cal OES string, e.g. "Evacuation Order"
    event_type: Optional[str] = "Wildfire (SIMULATED)"
    geometry: dict[str, Any]
    edit_date_ms: int
    expires_in_minutes: Optional[int] = None


class SyntheticFeedState(DoorstepModel):
    version: int = 0
    features: list[SyntheticFeature] = Field(default_factory=list)
    incidents: list[IncidentPoint] = Field(default_factory=list)
    frozen_at_ms: Optional[int] = None  # FREEZE_FEED: STATEWIDE_LAST_UPDATED stops advancing

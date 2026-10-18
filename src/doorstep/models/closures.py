"""Road closures and route previews (contract v2.1 §5.9–§5.10).
Only OFFICIAL_CONFIRMED closures block roads; no report never means a road is open.
Routes are ILLUSTRATIVE ONLY, never "safe"."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import Field

from .common import DoorstepModel


class ClosureState(str, Enum):
    OFFICIAL_CONFIRMED = "OFFICIAL_CONFIRMED"
    UNVERIFIED_REPORT = "UNVERIFIED_REPORT"
    CONFLICTING = "CONFLICTING"
    EXPIRED = "EXPIRED"


class ClosureSourceType(str, Enum):
    OFFICIAL_SIMULATION = "OFFICIAL_SIMULATION"
    NEWS = "NEWS"
    REAL_WORLD_CONTEXT = "REAL_WORLD_CONTEXT"  # display-only


class ClaimedStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class ClosureClaim(DoorstepModel):
    source_id: str
    source_type: ClosureSourceType
    source_item_id: str
    claimed_status: ClaimedStatus
    road_name: str
    location_text: str = ""
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None
    url: Optional[str] = None
    headline: str = ""
    raw_text: str = ""
    extraction_method: str = "STRUCTURED_FEED"  # or ASI_ONE_EXTRACTION
    received_at: Optional[str] = None


class Closure(DoorstepModel):
    closure_id: str
    road_name: str
    segment_id: Optional[str] = None  # None = unmapped: shown, never used for routing
    display_only: bool = False        # REAL_WORLD_CONTEXT records
    state: ClosureState
    claimed_status: ClaimedStatus
    used_for_routing: bool = False
    conflicting_reports: int = 0
    claims: list[ClosureClaim] = Field(default_factory=list)
    first_seen_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None


class RouteRequest(DoorstepModel):
    route_request_id: str
    case_id: str
    assignment_id: str
    status: str  # OK | REFUSED
    refusal_reasons: list[str] = Field(default_factory=list)
    stops: list[dict[str, Any]] = Field(default_factory=list)
    avoid_area_ids: list[str] = Field(default_factory=list)
    caution_ids: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class RoutePreview(DoorstepModel):
    route_preview_id: str
    route_request_id: str
    case_id: str
    assignment_id: str
    provider: str = "HERE"
    status: str  # ILLUSTRATIVE_ONLY | REFUSED | NO_ROUTE_CONFIRMED
    refusal_reason: Optional[str] = None
    crosses: list[str] = Field(default_factory=list)
    cautions_on_path: list[str] = Field(default_factory=list)
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None
    polyline: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None

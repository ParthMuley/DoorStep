"""Assignment model. A match is NOT a pickup; a pickup is NOT an arrival."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .common import (
    SCHEMA_VERSION,
    DoorstepModel,
    ProviderResponse,
    ServiceStatus,
    ServiceType,
    ZoneRule,
    new_id,
)


class Assignment(DoorstepModel):
    schema_version: str = SCHEMA_VERSION
    assignment_id: str = Field(default_factory=lambda: new_id("assign"))
    case_id: str
    request_id: str
    offer_id: str
    provider_id: str
    service_type: ServiceType
    provider_approved: bool
    service_area_allowed: bool
    zone_rule: ZoneRule
    authorization: str = "SIMULATED_PREAPPROVED"
    provider_response: ProviderResponse = ProviderResponse.PENDING
    status: ServiceStatus = ServiceStatus.PROPOSED
    idempotency_key: str
    # A proposal can pair transport + destination; each is its own row, linked.
    linked_assignment_id: Optional[str] = None
    confirmed_pickup_at: Optional[str] = None
    confirmed_arrival_at: Optional[str] = None
    correlation_id: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

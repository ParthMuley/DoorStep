"""Fetch.ai agent-to-agent message models and agent addressing.

uagents `Model` is pydantic v1 (see docs/integration-decisions.md). These types are
for Fetch.ai messaging only; Developer B's API models (pydantic v2) stay separate and
are converted at the boundary as plain dicts/JSON.

Providers only ever receive consent-scoped needs: no names, phone numbers, or
pickup points until a provider has accepted (and then only via B's backend).
"""

import os
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from uagents import Model
from uagents.crypto import Identity

SCHEMA_VERSION = "1.0"

ServiceType = Literal["accessible_transport", "accessible_destination"]
Decision = Literal["ACCEPTED", "DECLINED"]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_correlation_id() -> str:
    return f"corr_{uuid4().hex[:12]}"


class OfferRequest(Model):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    request_id: str
    correlation_id: str
    service_type: ServiceType
    zone_id: str
    requirements: dict[str, Any]
    created_at: str


class OfferResponse(Model):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    request_id: str
    correlation_id: str
    agent_role: ServiceType
    offers: list[dict[str, Any]]
    note: str
    created_at: str


class AcceptRequest(Model):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    assignment_id: str
    offer_id: str
    provider_id: str
    correlation_id: str
    idempotency_key: str
    shared_needs: dict[str, Any]
    created_at: str


class AcceptResponse(Model):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    assignment_id: str
    offer_id: str
    provider_id: str
    correlation_id: str
    idempotency_key: str
    decision: Decision
    reason: str
    created_at: str


def agent_address(role: str) -> str:
    """Address for `transport` / `destination`: explicit env override, else derived
    from that agent's seed (same derivation uagents uses at startup)."""
    explicit = os.getenv(f"{role.upper()}_AGENT_ADDRESS", "").strip()
    if explicit:
        return explicit
    seed = os.getenv(f"{role.upper()}_SEED", "").strip()
    if not seed:
        raise RuntimeError(f"Set {role.upper()}_AGENT_ADDRESS or {role.upper()}_SEED")
    return Identity.from_seed(seed, 0).address

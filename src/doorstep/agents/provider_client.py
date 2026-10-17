"""Coordinator-side calls to independent provider agents over Fetch.ai messaging."""

import asyncio
from dataclasses import dataclass
from typing import Any

from uagents import Context

from doorstep.integrations.fetch_adapter import (
    AcceptRequest,
    AcceptResponse,
    OfferRequest,
    OfferResponse,
    ServiceType,
    agent_address,
    utc_now,
)

PROVIDER_TIMEOUT_SECONDS = 20

ROLE_FOR_SERVICE: dict[ServiceType, str] = {
    "accessible_transport": "transport",
    "accessible_destination": "destination",
}


@dataclass
class OfferResult:
    service_type: ServiceType
    response: OfferResponse | None
    status_detail: str  # delivery status / timeout reason when response is None


async def request_offers(
    ctx: Context,
    service_type: ServiceType,
    case_id: str,
    request_id: str,
    zone_id: str,
    requirements: dict[str, Any],
    correlation_id: str,
) -> OfferResult:
    address = agent_address(ROLE_FOR_SERVICE[service_type])
    request = OfferRequest(
        case_id=case_id,
        request_id=request_id,
        correlation_id=correlation_id,
        service_type=service_type,
        zone_id=zone_id,
        requirements=requirements,
        created_at=utc_now(),
    )
    response, status = await ctx.send_and_receive(
        address, request, response_type=OfferResponse, timeout=PROVIDER_TIMEOUT_SECONDS
    )
    if response is not None and response.correlation_id != correlation_id:
        return OfferResult(service_type, None, "MISMATCHED_CORRELATION_ID")
    return OfferResult(service_type, response, str(status.status.value if status else "UNKNOWN"))


async def request_all_offers(
    ctx: Context,
    case_id: str,
    zone_id: str,
    transport_requirements: dict[str, Any],
    destination_requirements: dict[str, Any],
    correlation_id: str,
) -> tuple[OfferResult, OfferResult]:
    """Query Transport and Destination agents concurrently."""
    transport, destination = await asyncio.gather(
        request_offers(ctx, "accessible_transport", case_id, f"req_{case_id}_transport", zone_id,
                       transport_requirements, correlation_id),
        request_offers(ctx, "accessible_destination", case_id, f"req_{case_id}_destination", zone_id,
                       destination_requirements, correlation_id),
    )
    return transport, destination


async def request_acceptance(
    ctx: Context,
    service_type: ServiceType,
    case_id: str,
    assignment_id: str,
    offer_id: str,
    provider_id: str,
    shared_needs: dict[str, Any],
    correlation_id: str,
) -> AcceptResponse | None:
    """Ask the provider agent to accept. None means no answer: callers must check case
    status before retrying (no blind retry of a non-idempotent action)."""
    address = agent_address(ROLE_FOR_SERVICE[service_type])
    request = AcceptRequest(
        case_id=case_id,
        assignment_id=assignment_id,
        offer_id=offer_id,
        provider_id=provider_id,
        correlation_id=correlation_id,
        idempotency_key=f"{assignment_id}:acceptance:{provider_id}",
        shared_needs=shared_needs,
        created_at=utc_now(),
    )
    response, _ = await ctx.send_and_receive(
        address, request, response_type=AcceptResponse, timeout=PROVIDER_TIMEOUT_SECONDS
    )
    return response

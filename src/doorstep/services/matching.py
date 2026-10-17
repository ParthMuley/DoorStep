"""Deterministic matching. Plain code, no LLM, no ranking of people.

Every provider in the inventory is evaluated and returned with reasons, so the
coordinator can show *why* each one matches or is rejected. Eligible offers are
ranked only by non-safety factors (route distance on the fictional graph).

These functions are pure: Developer A's provider agents can call them against
their own local inventories.
"""

from __future__ import annotations

from typing import Callable

from doorstep.demo.synthetic_zone_graph import ZoneGraph
from doorstep.models import (
    Destination,
    DestinationRequirements,
    Offer,
    ServiceRequest,
    ServiceType,
    TransportProvider,
    TransportRequirements,
)

from .safety_rules import check_route


def evaluate_transport(
    req: TransportRequirements, zone_id: str, provider: TransportProvider, graph: ZoneGraph
) -> tuple[list[str], float | None]:
    """(rejection reasons, route distance). No reasons == eligible."""
    reasons: list[str] = []
    v = provider.vehicle
    if not provider.approved:
        reasons.append("PROVIDER_NOT_APPROVED")
    if graph.is_active_order(zone_id):
        reasons.append("INSIDE_ACTIVE_ORDER_ZONE")
    if zone_id not in provider.service_area_zones:
        reasons.append("OUTSIDE_SERVICE_AREA")
    if not provider.available or provider.available_trips < 1:
        reasons.append("NO_AVAILABLE_CAPACITY")
    if req.wheelchair_accessible_vehicle and not v.wheelchair_accessible:
        reasons.append("NOT_WHEELCHAIR_ACCESSIBLE")
    if req.transfer_assistance and not v.transfer_assistance:
        reasons.append("NO_TRANSFER_ASSISTANCE")
    if req.portable_oxygen_equipment and not v.oxygen_equipment_handling:
        reasons.append("NO_OXYGEN_EQUIPMENT_HANDLING")
    if req.pet_count > v.pet_capacity:
        reasons.append("INSUFFICIENT_PET_CAPACITY")
    if req.service_animal and not v.service_animal_ok:
        reasons.append("SERVICE_ANIMAL_NOT_ACCOMMODATED")
    if v.seating_capacity < 1:
        reasons.append("NO_SEATING_CAPACITY")
    distance = None
    if not graph.is_active_order(zone_id):
        route = check_route(graph, provider.base_zone, zone_id)
        if route.ok:
            distance = route.distance_km
        else:
            reasons.append(route.reason)
    return reasons, distance


def evaluate_destination(
    req: DestinationRequirements, pickup_zone: str, dest: Destination, graph: ZoneGraph
) -> tuple[list[str], float | None]:
    reasons: list[str] = []
    if not dest.approved:
        reasons.append("PROVIDER_NOT_APPROVED")
    if graph.is_active_order(dest.zone_id):
        reasons.append("DESTINATION_IN_ACTIVE_ORDER_ZONE")
    if dest.available_capacity < req.capacity_needed:
        reasons.append("NO_AVAILABLE_CAPACITY")
    if req.step_free_entry and not dest.step_free_entry:
        reasons.append("NOT_STEP_FREE")
    if req.accessible_restroom and not dest.accessible_restroom:
        reasons.append("NO_ACCESSIBLE_RESTROOM")
    if req.pets_allowed and not dest.pets_allowed:
        reasons.append("PETS_NOT_ALLOWED")
    if req.service_animal and not dest.service_animal_ok:
        reasons.append("SERVICE_ANIMAL_NOT_ACCOMMODATED")
    if req.oxygen_friendly and not dest.oxygen_friendly:
        reasons.append("NOT_OXYGEN_FRIENDLY")
    distance = None
    if not graph.is_active_order(pickup_zone):
        route = check_route(graph, pickup_zone, dest.zone_id)
        if route.ok:
            distance = route.distance_km
        else:
            reasons.append(route.reason)
    return reasons, distance


def _rank(offers: list[Offer]) -> list[Offer]:
    # Eligible first, then shortest fictional route; provider_id breaks ties.
    return sorted(offers, key=lambda o: (not o.eligible,
                                         o.estimated_distance_km if o.estimated_distance_km is not None else 1e9,
                                         o.provider_id))


def _offer(request: ServiceRequest, provider_id: str, reasons: list[str], distance: float | None,
           make_id: Callable[[str], str] | None) -> Offer:
    kwargs = {"offer_id": make_id(provider_id)} if make_id else {}
    return Offer(
        request_id=request.request_id,
        case_id=request.case_id,
        provider_id=provider_id,
        service_type=request.service_type,
        eligible=not reasons,
        reasons=reasons or ["MEETS_ALL_HARD_CONSTRAINTS"],
        estimated_distance_km=distance,
        **kwargs,
    )


def find_transport(request: ServiceRequest, providers: list[TransportProvider], graph: ZoneGraph,
                   make_id: Callable[[str], str] | None = None) -> list[Offer]:
    assert request.service_type == ServiceType.ACCESSIBLE_TRANSPORT
    req = request.transport_requirements or TransportRequirements()
    offers = []
    for p in providers:
        reasons, distance = evaluate_transport(req, request.zone_id, p, graph)
        offers.append(_offer(request, p.provider_id, reasons, distance, make_id))
    return _rank(offers)


def find_destination(request: ServiceRequest, destinations: list[Destination], graph: ZoneGraph,
                     make_id: Callable[[str], str] | None = None) -> list[Offer]:
    assert request.service_type == ServiceType.ACCESSIBLE_DESTINATION
    req = request.destination_requirements or DestinationRequirements()
    offers = []
    for d in destinations:
        reasons, distance = evaluate_destination(req, request.zone_id, d, graph)
        offers.append(_offer(request, d.provider_id, reasons, distance, make_id))
    return _rank(offers)

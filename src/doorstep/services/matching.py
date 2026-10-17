"""Deterministic evaluation of RAW provider offers. Plain code, no LLM.

Provider agents (Developer A) send raw offers; this module decides eligibility
and explains every rejection. Approval and base location come from B's partner
registry -- never from the offer's own claims. Eligible offers are ranked only
by non-safety factors (ETA, then fictional route distance). Nothing here ranks
people.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from doorstep.demo.synthetic_zone_graph import ZoneGraph
from doorstep.models import (
    DestinationOfferIn,
    DestinationRequirements,
    Offer,
    ProviderRegistration,
    ServiceType,
    TransportOfferIn,
    TransportRequirements,
    ZoneRule,
)

from .safety_rules import check_route, zone_rule

TRANSPORT = ServiceType.ACCESSIBLE_TRANSPORT.value
DESTINATION = ServiceType.ACCESSIBLE_DESTINATION.value


def _expired(valid_until: Optional[str], now: datetime) -> bool:
    if not valid_until:
        return False
    try:
        ts = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except ValueError:
        return True  # unparseable expiry is treated as expired (fail closed)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts <= now


def _approval_reasons(reg: Optional[ProviderRegistration], service_type: str) -> list[str]:
    if reg is None or not reg.approved or reg.service_type != service_type:
        return ["PROVIDER_NOT_APPROVED"]
    return []


def _zone_reasons(rule: str) -> list[str]:
    if rule == ZoneRule.INSIDE_ACTIVE_ORDER:
        return ["ACTIVE_ORDER_ZONE"]
    if rule == ZoneRule.UNVERIFIED:
        return ["ZONE_UNVERIFIED"]
    return []


def evaluate_transport(req: TransportRequirements, zone_id: str, sector_id: Optional[str],
                       offer: TransportOfferIn, reg: Optional[ProviderRegistration], graph: ZoneGraph,
                       now: Optional[datetime] = None) -> tuple[list[str], list[str], Optional[float]]:
    """(rejection reasons, match reasons, route km). No rejection reasons == eligible."""
    now = now or datetime.now(timezone.utc)
    location = sector_id or zone_id
    rule = zone_rule(graph, location)
    reasons = _approval_reasons(reg, TRANSPORT) + _zone_reasons(rule)
    match: list[str] = []

    if zone_id in offer.service_area_zones or location in offer.service_area_zones:
        match.append("in_service_area")
    else:
        reasons.append("OUTSIDE_SERVICE_AREA")
    if _expired(offer.valid_until, now):
        reasons.append("OFFER_EXPIRED")
    if offer.seats_available < 1:
        reasons.append("NO_SEATS_AVAILABLE")

    if req.wheelchair_accessible_vehicle:
        if not offer.wheelchair_accessible:
            reasons.append("NOT_WHEELCHAIR_ACCESSIBLE")
        elif offer.wheelchair_spaces_available < 1:
            reasons.append("NO_WHEELCHAIR_SPACE_AVAILABLE")
        else:
            match.append("wheelchair_accessible")
    if req.transfer_assistance:
        if offer.transfer_assistance:
            match.append("transfer_assistance")
        else:
            reasons.append("NO_TRANSFER_ASSISTANCE")
    if req.portable_oxygen_equipment:
        if offer.oxygen_handling:
            match.append("oxygen_handling")
        else:
            reasons.append("NO_OXYGEN_HANDLING")
    if req.pet_count > 0:
        if offer.pets_allowed:
            match.append("pets_allowed")
        else:
            reasons.append("PETS_NOT_ALLOWED")
    if req.service_animal:
        if offer.service_animals_allowed is True:
            match.append("service_animal_allowed")
        elif offer.service_animals_allowed is False:
            reasons.append("SERVICE_ANIMAL_NOT_ACCOMMODATED")
        else:
            reasons.append("SERVICE_ANIMAL_UNCONFIRMED")

    distance = None
    if rule == ZoneRule.OUTSIDE_ACTIVE_ORDER:
        base = (reg.base_zone if reg else None) or offer.base_zone
        if not base:
            reasons.append("PROVIDER_BASE_UNKNOWN")
        else:
            route = check_route(graph, base, location)
            if route.ok:
                distance = route.distance_km
                match.append("route_avoids_closed_roads")
            else:
                reasons.append(route.reason)
    if not reasons:
        match.append("provider_approved")
    return reasons, match, distance


def evaluate_destination(req: DestinationRequirements, zone_id: str, sector_id: Optional[str],
                         offer: DestinationOfferIn, reg: Optional[ProviderRegistration], graph: ZoneGraph,
                         now: Optional[datetime] = None) -> tuple[list[str], list[str], Optional[float]]:
    now = now or datetime.now(timezone.utc)
    location = sector_id or zone_id
    rule = zone_rule(graph, location)
    reasons = _approval_reasons(reg, DESTINATION) + _zone_reasons(rule)
    match: list[str] = []
    dest_zone = (reg.base_zone if reg else None) or offer.zone_id

    if dest_zone and graph.is_active_order(dest_zone):
        reasons.append("DESTINATION_IN_ACTIVE_ORDER_ZONE")
    if _expired(offer.valid_until, now):
        reasons.append("OFFER_EXPIRED")
    if offer.beds_available < req.capacity_needed:
        reasons.append("NO_BEDS_AVAILABLE")
    checks = [
        (req.step_free_entry, offer.step_free_entry, "step_free_entry", "NOT_STEP_FREE"),
        (req.accessible_restroom, offer.accessible_restroom, "accessible_restroom", "NO_ACCESSIBLE_RESTROOM"),
        (req.pets_allowed, offer.pets_allowed, "pets_allowed", "PETS_NOT_ALLOWED"),
        (req.service_animal, offer.service_animals_allowed, "service_animals_allowed",
         "SERVICE_ANIMAL_NOT_ACCOMMODATED"),
        (req.oxygen_friendly, offer.oxygen_power_outlets, "oxygen_power_outlets", "NO_OXYGEN_POWER"),
    ]
    for needed, has, ok_code, bad_code in checks:
        if needed:
            (match if has else reasons).append(ok_code if has else bad_code)

    distance = None
    if rule == ZoneRule.OUTSIDE_ACTIVE_ORDER:
        if not dest_zone:
            reasons.append("DESTINATION_LOCATION_UNKNOWN")
        else:
            route = check_route(graph, location, dest_zone)
            if route.ok:
                distance = route.distance_km
                match.append("route_avoids_closed_roads")
            else:
                reasons.append(route.reason)
    if not reasons:
        match.append("provider_approved")
    return reasons, match, distance


def _rank(offers: list[Offer]) -> list[Offer]:
    def key(o: Offer):
        return (not o.eligible,
                o.eta_minutes if o.eta_minutes is not None else 10**6,
                o.estimated_distance_km if o.estimated_distance_km is not None else 1e9,
                o.offer_id)

    ranked = sorted(offers, key=key)
    n = 0
    for o in ranked:
        if o.eligible:
            n += 1
            o.rank = n
    return ranked


def evaluate_transport_offers(case_id: str, request_id: str, req: TransportRequirements, zone_id: str,
                              sector_id: Optional[str], offers: list[TransportOfferIn],
                              registry: dict[str, ProviderRegistration], graph: ZoneGraph,
                              now: Optional[datetime] = None) -> list[Offer]:
    out = []
    for raw in offers:
        reasons, match, km = evaluate_transport(req, zone_id, sector_id, raw, registry.get(raw.provider_id),
                                                graph, now)
        out.append(Offer(offer_id=raw.offer_id, request_id=request_id, case_id=case_id,
                         provider_id=raw.provider_id, service_type=TRANSPORT, eligible=not reasons,
                         reasons=reasons, match_reasons=match if not reasons else [],
                         eta_minutes=raw.eta_minutes, estimated_distance_km=km, raw=raw.model_dump()))
    return _rank(out)


def evaluate_destination_offers(case_id: str, request_id: str, req: DestinationRequirements, zone_id: str,
                                sector_id: Optional[str], offers: list[DestinationOfferIn],
                                registry: dict[str, ProviderRegistration], graph: ZoneGraph,
                                now: Optional[datetime] = None) -> list[Offer]:
    out = []
    for raw in offers:
        reasons, match, km = evaluate_destination(req, zone_id, sector_id, raw, registry.get(raw.provider_id),
                                                  graph, now)
        out.append(Offer(offer_id=raw.offer_id, request_id=request_id, case_id=case_id,
                         provider_id=raw.provider_id, service_type=DESTINATION, eligible=not reasons,
                         reasons=reasons, match_reasons=match if not reasons else [],
                         estimated_distance_km=km, raw=raw.model_dump()))
    return _rank(out)

"""Deterministic evaluation of raw offers: hard constraints are never relaxed."""

from datetime import datetime, timedelta, timezone

import pytest

from doorstep.demo import seed
from doorstep.demo.synthetic_zone_graph import build_demo_graph
from doorstep.models import DestinationOfferIn, DestinationRequirements, TransportOfferIn, TransportRequirements
from doorstep.services import matching

REG = {r.provider_id: r for r in seed.provider_registry()}
SECTOR_B = ("zone_3", "zone_3_sector_b")
SECTOR_A = ("zone_3", "zone_3_sector_a")
FUTURE = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


@pytest.fixture
def graph():
    return build_demo_graph()


def van(**kw):
    base = dict(offer_id="o1", provider_id="transport_org_a", wheelchair_accessible=True, transfer_assistance=True,
                oxygen_handling=True, pets_allowed=True, service_animals_allowed=True, seats_available=2,
                wheelchair_spaces_available=1, service_area_zones=["zone_3"], eta_minutes=10, valid_until=FUTURE)
    base.update(kw)
    return TransportOfferIn(**base)


def reasons(req, offer, graph, where=SECTOR_B):
    return matching.evaluate_transport(req, *where, offer, REG.get(offer.provider_id), graph)[0]


def test_wheelchair_user_never_matched_to_non_accessible_vehicle(graph):
    req = TransportRequirements(wheelchair_accessible_vehicle=True)
    assert "NOT_WHEELCHAIR_ACCESSIBLE" in reasons(req, van(wheelchair_accessible=False), graph)
    assert "NO_WHEELCHAIR_SPACE_AVAILABLE" in reasons(req, van(wheelchair_spaces_available=0), graph)
    assert reasons(req, van(), graph) == []


def test_transfer_support_required(graph):
    assert "NO_TRANSFER_ASSISTANCE" in reasons(TransportRequirements(transfer_assistance=True),
                                               van(transfer_assistance=False), graph)


def test_oxygen_requires_specialized_handling(graph):
    assert "NO_OXYGEN_HANDLING" in reasons(TransportRequirements(portable_oxygen_equipment=True),
                                           van(oxygen_handling=False), graph)


def test_pets_and_service_animals_respected(graph):
    assert "PETS_NOT_ALLOWED" in reasons(TransportRequirements(pet_count=1), van(pets_allowed=False), graph)
    req = TransportRequirements(service_animal=True)
    assert "SERVICE_ANIMAL_NOT_ACCOMMODATED" in reasons(req, van(service_animals_allowed=False), graph)
    assert "SERVICE_ANIMAL_UNCONFIRMED" in reasons(req, van(service_animals_allowed=None), graph)


def test_unapproved_or_unknown_provider_rejected(graph):
    assert "PROVIDER_NOT_APPROVED" in reasons(TransportRequirements(), van(provider_id="transport_org_c"), graph)
    assert "PROVIDER_NOT_APPROVED" in reasons(TransportRequirements(), van(provider_id="unknown_org"), graph)
    # A destination provider cannot pose as a transport provider.
    assert "PROVIDER_NOT_APPROVED" in reasons(TransportRequirements(), van(provider_id="destination_org_a"), graph)


def test_active_order_zone_blocks_every_offer(graph):
    assert "ACTIVE_ORDER_ZONE" in reasons(TransportRequirements(), van(), graph, where=SECTOR_A)


def test_unknown_location_fails_closed(graph):
    assert "ZONE_UNVERIFIED" in reasons(TransportRequirements(), van(), graph, where=("zone_9", "nowhere"))


def test_outside_service_area_rejected(graph):
    assert "OUTSIDE_SERVICE_AREA" in reasons(TransportRequirements(), van(service_area_zones=["zone_5"]), graph)


def test_capacity_and_expiry(graph):
    assert "NO_SEATS_AVAILABLE" in reasons(TransportRequirements(), van(seats_available=0), graph)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert "OFFER_EXPIRED" in reasons(TransportRequirements(), van(valid_until=past), graph)
    assert "OFFER_EXPIRED" in reasons(TransportRequirements(), van(valid_until="not-a-date"), graph)


def test_route_avoids_closed_road_and_detours(graph):
    # transport_org_e is based in zone_4: the direct road is closed and sector A is an active order zone.
    r, _, km = matching.evaluate_transport(TransportRequirements(), *SECTOR_B, van(provider_id="transport_org_e"),
                                           REG["transport_org_e"], graph)
    assert r == [] and km == 11.0  # zone_4 -> zone_5 -> zone_2 -> sector_b


def test_no_route_means_rejection(graph):
    graph.closed_edges.add(frozenset(("zone_2", "zone_3_sector_b")))
    assert "NO_PATH_AVOIDING_CLOSED_ROADS_AND_ORDER_ZONES" in reasons(TransportRequirements(), van(), graph)


def test_registry_base_wins_over_offer_claim(graph):
    # The offer claims to be next door, but the registry says zone_2: route is computed from zone_2.
    _, _, km = matching.evaluate_transport(TransportRequirements(), *SECTOR_B, van(base_zone="zone_3_sector_b"),
                                           REG["transport_org_a"], graph)
    assert km == 4.0


def dest(**kw):
    base = dict(offer_id="d1", provider_id="destination_org_a", step_free_entry=True, accessible_restroom=True,
                pets_allowed=True, service_animals_allowed=True, beds_available=5, oxygen_power_outlets=True,
                valid_until=FUTURE)
    base.update(kw)
    return DestinationOfferIn(**base)


def test_destination_accessibility_respected(graph):
    def r(req, d):
        return matching.evaluate_destination(req, *SECTOR_B, d, REG.get(d.provider_id), graph)[0]

    assert "NOT_STEP_FREE" in r(DestinationRequirements(step_free_entry=True), dest(step_free_entry=False))
    assert "PETS_NOT_ALLOWED" in r(DestinationRequirements(pets_allowed=True), dest(pets_allowed=False))
    assert "NO_OXYGEN_POWER" in r(DestinationRequirements(oxygen_friendly=True), dest(oxygen_power_outlets=False))
    assert "NO_BEDS_AVAILABLE" in r(DestinationRequirements(), dest(beds_available=0))
    assert "PROVIDER_NOT_APPROVED" in r(DestinationRequirements(), dest(provider_id="nope"))
    assert r(DestinationRequirements(step_free_entry=True, pets_allowed=True), dest()) == []


def test_ranking_depends_only_on_offers_not_on_who_the_resident_is(graph):
    offers = [van(offer_id="slow", eta_minutes=30), van(offer_id="fast", eta_minutes=5)]

    def ranked(case_id):
        out = matching.evaluate_transport_offers(case_id, "req", TransportRequirements(), *SECTOR_B, offers, REG, graph)
        return [(o.offer_id, o.rank) for o in out]

    assert ranked("case_x") == ranked("case_y") == [("fast", 1), ("slow", 2)]


def test_every_offer_is_reported_with_reasons(graph):
    out = matching.evaluate_transport_offers(
        "c", "r", TransportRequirements(wheelchair_accessible_vehicle=True), *SECTOR_B,
        [van(offer_id="ok"), van(offer_id="bad", wheelchair_accessible=False)], REG, graph)
    assert [(o.offer_id, o.eligible) for o in out] == [("ok", True), ("bad", False)]
    assert "provider_approved" in out[0].match_reasons and out[1].rank is None

"""Deterministic matching: hard constraints are never relaxed."""

import pytest

from doorstep.demo.synthetic_zone_graph import build_demo_graph
from doorstep.models import (
    Destination,
    DestinationRequirements,
    ServiceRequest,
    TransportProvider,
    TransportRequirements,
    VehicleCapability,
)
from doorstep.services import matching


@pytest.fixture
def graph():
    return build_demo_graph()


def van(**overrides):
    vehicle = dict(wheelchair_accessible=True, transfer_assistance=True, oxygen_equipment_handling=True,
                   seating_capacity=2, pet_capacity=2, service_animal_ok=True)
    vehicle.update(overrides.pop("vehicle", {}))
    base = dict(provider_id="p", display_name="P (DEMO)", service_area_zones=["zone_2", "zone_3"],
                base_zone="zone_2", vehicle=VehicleCapability(**vehicle))
    base.update(overrides)
    return TransportProvider(**base)


def reasons(req, provider, graph, zone="zone_3"):
    return matching.evaluate_transport(req, zone, provider, graph)[0]


def test_wheelchair_user_never_matched_to_non_accessible_vehicle(graph):
    req = TransportRequirements(wheelchair_accessible_vehicle=True)
    assert "NOT_WHEELCHAIR_ACCESSIBLE" in reasons(req, van(vehicle={"wheelchair_accessible": False}), graph)
    assert reasons(req, van(), graph) == []


def test_transfer_support_required(graph):
    req = TransportRequirements(transfer_assistance=True)
    assert "NO_TRANSFER_ASSISTANCE" in reasons(req, van(vehicle={"transfer_assistance": False}), graph)


def test_oxygen_requires_specialized_handling(graph):
    req = TransportRequirements(portable_oxygen_equipment=True)
    assert "NO_OXYGEN_EQUIPMENT_HANDLING" in reasons(req, van(vehicle={"oxygen_equipment_handling": False}), graph)


def test_pets_and_service_animals_respected(graph):
    assert "INSUFFICIENT_PET_CAPACITY" in reasons(TransportRequirements(pet_count=1),
                                                  van(vehicle={"pet_capacity": 0}), graph)
    assert "SERVICE_ANIMAL_NOT_ACCOMMODATED" in reasons(TransportRequirements(service_animal=True),
                                                        van(vehicle={"service_animal_ok": False}), graph)


def test_unapproved_provider_rejected(graph):
    assert "PROVIDER_NOT_APPROVED" in reasons(TransportRequirements(), van(approved=False), graph)


def test_active_order_zone_blocks_every_provider(graph):
    r = reasons(TransportRequirements(), van(service_area_zones=["zone_3n"]), graph, zone="zone_3n")
    assert "INSIDE_ACTIVE_ORDER_ZONE" in r


def test_outside_service_area_rejected(graph):
    assert "OUTSIDE_SERVICE_AREA" in reasons(TransportRequirements(), van(service_area_zones=["zone_5"]), graph)


def test_no_capacity_rejected(graph):
    assert "NO_AVAILABLE_CAPACITY" in reasons(TransportRequirements(), van(available_trips=0), graph)
    assert "NO_AVAILABLE_CAPACITY" in reasons(TransportRequirements(), van(available=False), graph)


def test_route_avoids_closed_road_and_detours(graph):
    # zone_4 -> zone_3 direct edge is closed; via zone_3n is an active order zone.
    provider = van(base_zone="zone_4", service_area_zones=["zone_3"])
    r, distance = matching.evaluate_transport(TransportRequirements(), "zone_3", provider, graph)
    assert r == []
    assert distance == 11.0  # zone_4 -> zone_5 -> zone_2 -> zone_3


def test_no_route_means_rejection(graph):
    graph.closed_edges.add(frozenset(("zone_2", "zone_3")))
    r = reasons(TransportRequirements(), van(), graph)
    assert "NO_PATH_AVOIDING_CLOSED_ROADS_AND_ORDER_ZONES" in r


def _dest(**kw):
    base = dict(provider_id="d", display_name="D (DEMO)", zone_id="zone_5", step_free_entry=True,
                accessible_restroom=True, pets_allowed=True, oxygen_friendly=True,
                total_capacity=5, available_capacity=5)
    base.update(kw)
    return Destination(**base)


def test_destination_accessibility_respected(graph):
    def r(req, d):
        return matching.evaluate_destination(req, "zone_3", d, graph)[0]

    assert "NOT_STEP_FREE" in r(DestinationRequirements(step_free_entry=True), _dest(step_free_entry=False))
    assert "PETS_NOT_ALLOWED" in r(DestinationRequirements(pets_allowed=True), _dest(pets_allowed=False))
    assert "NOT_OXYGEN_FRIENDLY" in r(DestinationRequirements(oxygen_friendly=True), _dest(oxygen_friendly=False))
    assert "NO_AVAILABLE_CAPACITY" in r(DestinationRequirements(), _dest(available_capacity=0))
    assert "PROVIDER_NOT_APPROVED" in r(DestinationRequirements(), _dest(approved=False))
    assert "DESTINATION_IN_ACTIVE_ORDER_ZONE" in r(DestinationRequirements(), _dest(zone_id="zone_3n"))
    assert r(DestinationRequirements(step_free_entry=True, pets_allowed=True), _dest()) == []


def test_ranking_depends_only_on_requirements_not_on_who_the_resident_is(graph):
    providers = [van(provider_id="far", base_zone="zone_5", service_area_zones=["zone_3"]),
                 van(provider_id="near", base_zone="zone_2")]

    def ranked(case_id):
        req = ServiceRequest(case_id=case_id, service_type="accessible_transport", zone_id="zone_3",
                             transport_requirements=TransportRequirements(), idempotency_key=case_id)
        return [o.provider_id for o in matching.find_transport(req, providers, graph)]

    assert ranked("case_x") == ranked("case_y") == ["near", "far"]


def test_every_provider_is_reported_with_reasons(graph):
    req = ServiceRequest(case_id="c", service_type="accessible_transport", zone_id="zone_3",
                         transport_requirements=TransportRequirements(wheelchair_accessible_vehicle=True),
                         idempotency_key="k")
    offers = matching.find_transport(req, [van(provider_id="ok"), van(provider_id="bad",
                                     vehicle={"wheelchair_accessible": False})], graph)
    assert [o.eligible for o in offers] == [True, False]
    assert offers[0].reasons == ["MEETS_ALL_HARD_CONSTRAINTS"]

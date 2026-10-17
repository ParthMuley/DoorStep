"""Safety gate, synthetic graph, and consent."""

import pytest

from doorstep.demo.synthetic_zone_graph import build_demo_graph
from doorstep.models import Assignment, Case, Consent
from doorstep.services import consent
from doorstep.services.errors import ConsentRequired, SafetyRejection, Unauthorized
from doorstep.services.safety_rules import assignment_safety_violations

from .conftest import DAVID, MARIA, david_confirmed, eligible, maria_accepted, maria_confirmed, maria_proposed


def test_closed_edge_never_used_by_route_planner():
    g = build_demo_graph()
    path, _ = g.shortest_path("zone_3", "zone_5")
    hops = {frozenset(p) for p in zip(path, path[1:])}
    assert frozenset(("zone_3", "zone_4")) not in hops
    assert "zone_3n" not in path


def test_route_into_active_order_zone_is_refused():
    assert build_demo_graph().shortest_path("zone_2", "zone_3n") is None


def test_safety_gate_blocks_inside_order_zone_assignment():
    a = Assignment(case_id="c", request_id="r", offer_id="o", provider_id="p",
                   service_type="accessible_transport", provider_approved=True, service_area_allowed=True,
                   zone_rule="INSIDE_ACTIVE_ORDER", idempotency_key="k")
    assert "INSIDE_ACTIVE_ORDER_ZONE" in assignment_safety_violations(a)


def test_inside_order_zone_volunteer_assignment_always_blocked(svc):
    david_confirmed(svc)
    result = svc.find_transport(DAVID)
    assert result["eligible_count"] == 0
    for offer in result["offers"]:
        with pytest.raises(SafetyRejection):
            svc.propose_assignment(DAVID, offer["offer_id"])
    assert svc.store.assignments_for_case(DAVID) == []


def test_unapproved_provider_cannot_be_assigned(svc):
    maria_confirmed(svc)
    t = svc.find_transport(MARIA)
    unapproved = next(o for o in t["offers"] if o["provider_id"] == "transport_org_c")
    with pytest.raises(SafetyRejection) as exc:
        svc.propose_assignment(MARIA, unapproved["offer_id"])
    assert "PROVIDER_NOT_APPROVED" in exc.value.reasons


def test_unapproved_provider_cannot_access_pickup_point(svc):
    ta, _ = maria_accepted(svc)
    with pytest.raises(Unauthorized):
        svc.get_pickup_details(ta.assignment_id, "transport_org_c")
    details = svc.get_pickup_details(ta.assignment_id, ta.provider_id)
    assert details["pickup_point"].startswith("DEMO")


def test_pickup_point_withheld_before_acceptance(svc):
    ta, _ = maria_proposed(svc)
    with pytest.raises(Unauthorized):
        svc.get_pickup_details(ta.assignment_id, ta.provider_id)


def test_stale_offer_rechecked_at_proposal(svc):
    maria_confirmed(svc)
    t = svc.find_transport(MARIA)
    offer = eligible(t)
    provider = svc.store.get_transport_provider(offer["provider_id"])
    provider.available_trips = 0
    svc.store.save_transport_provider(provider)
    with pytest.raises(SafetyRejection) as exc:
        svc.propose_assignment(MARIA, offer["offer_id"])
    assert "NO_AVAILABLE_CAPACITY" in exc.value.reasons


def test_missing_transport_consent_blocks_offer_request(svc):
    maria_confirmed(svc)
    case = svc.store.get_case(MARIA)
    case.consent = Consent(contact_for_checkins=True)
    svc.store.save_case(case)
    with pytest.raises(ConsentRequired):
        svc.find_transport(MARIA)


def test_recovery_details_not_shared_without_consent(svc):
    maria_confirmed(svc)
    out = svc.request_recovery_handoff(MARIA, consent=False, granted_by="resident_001")
    assert out["referral"] is None and out["shared_fields"] == {}
    assert svc.store.referrals_for_case(MARIA) == []
    with pytest.raises(ConsentRequired):
        consent.recovery_payload(svc.store.get_case(MARIA))


def test_recovery_payload_is_minimal(svc):
    maria_confirmed(svc)
    out = svc.request_recovery_handoff(MARIA, consent=True, granted_by="resident_001")
    assert set(out["shared_fields"]) == {"case_id", "preferred_language", "wheelchair_accessible",
                                         "destination_accessibility", "pet_count", "service_animal"}


def test_consent_only_from_resident_or_caregiver(svc):
    maria_confirmed(svc)
    with pytest.raises(Unauthorized):
        svc.request_recovery_handoff(MARIA, consent=True, granted_by="transport_org_a")


def test_provider_payload_has_no_identity():
    case = Case(case_id="c", resident_id="r", zone_id="zone_3",
                consent=Consent(share_transport_needs=True, share_destination_needs=True))
    dumped = consent.transport_requirements(case).model_dump()
    assert not {"resident_id", "display_name", "contact_channel", "pickup_point"} & set(dumped)

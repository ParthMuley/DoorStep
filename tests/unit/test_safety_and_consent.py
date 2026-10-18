"""Safety gate, synthetic graph, and consent."""

import pytest

from doorstep.demo.synthetic_zone_graph import build_demo_graph
from doorstep.models import Assignment, Case, Consent
from doorstep.services import consent
from doorstep.services.errors import ConsentRequired, SafetyRejection, Unauthorized
from doorstep.services.safety_rules import assignment_safety_violations

from .conftest import (DAVID, MARIA, d_offers, david_confirmed, maria_accepted, maria_confirmed, maria_evaluated,
                       maria_proposed, t_offers)


def test_closed_edge_never_used_by_route_planner():
    path, _ = build_demo_graph().shortest_path("zone_3_sector_b", "zone_5")
    hops = {frozenset(p) for p in zip(path, path[1:])}
    assert frozenset(("zone_3_sector_b", "zone_4")) not in hops
    assert "zone_3_sector_a" not in path


def test_route_into_active_order_zone_is_refused():
    assert build_demo_graph().shortest_path("zone_2", "zone_3_sector_a") is None


def test_safety_gate_blocks_inside_and_unverified_zones():
    for rule in ("INSIDE_ACTIVE_ORDER", "UNVERIFIED"):
        a = Assignment(case_id="c", request_id="r", offer_id="o", provider_id="p",
                       service_type="accessible_transport", provider_approved=True, service_area_allowed=True,
                       zone_rule=rule, idempotency_key="k")
        assert "INSIDE_ACTIVE_ORDER_ZONE" in assignment_safety_violations(a)


def test_inside_order_zone_volunteer_assignment_always_blocked(svc):
    david_confirmed(svc)
    result = svc.evaluate_transport(DAVID, t_offers(), "req_101")
    assert result["eligible"] == [] and result["escalation_required"]
    for offer in result["rejected"]:
        with pytest.raises(SafetyRejection) as exc:
            svc.propose_assignment(DAVID, transport_offer_id=offer["offer_id"])
        assert exc.value.code == "UNSAFE_ZONE"
    assert svc.store.assignments_for_case(DAVID) == []


def test_unapproved_provider_cannot_be_assigned(svc):
    maria_evaluated(svc)
    with pytest.raises(SafetyRejection) as exc:
        svc.propose_assignment(MARIA, transport_offer_id="offer_t_003")
    assert exc.value.code == "PROVIDER_NOT_APPROVED"


def test_only_preapproved_authorization_proposes(svc):
    maria_evaluated(svc)
    with pytest.raises(SafetyRejection) as exc:
        svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", authorization="SOMETHING_ELSE")
    assert exc.value.code == "NOT_AUTHORIZED"


def test_pickup_point_only_after_acceptance_and_only_to_that_provider(svc):
    aid = maria_proposed(svc)
    with pytest.raises(Unauthorized):
        svc.get_pickup_details(aid, "transport_org_a")
    view, _ = svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", destination_offer_id="offer_d_001",
                                     idempotency_key=f"{MARIA}:transport:v1")
    assert "pickup_point" not in view["shared_with_provider"]
    svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")
    with pytest.raises(Unauthorized):
        svc.get_pickup_details(aid, "transport_org_c")
    assert svc.get_pickup_details(aid, "transport_org_a")["pickup_point"].startswith("SYNTHETIC")


def test_expired_offer_rechecked_at_proposal(svc):
    maria_confirmed(svc)
    svc.evaluate_transport(MARIA, t_offers(offer_t_001={"valid_until": "2000-01-01T00:00:00Z"}), "req_001")
    with pytest.raises(SafetyRejection) as exc:
        svc.propose_assignment(MARIA, transport_offer_id="offer_t_001")
    assert "OFFER_EXPIRED" in exc.value.reasons


def test_approval_revoked_after_evaluation_blocks_proposal(svc):
    maria_evaluated(svc)
    reg = svc.store.get_registration("transport_org_a")
    reg.approved = False
    svc.store.save_registration(reg)
    with pytest.raises(SafetyRejection) as exc:
        svc.propose_assignment(MARIA, transport_offer_id="offer_t_001")
    assert exc.value.code == "PROVIDER_NOT_APPROVED"


def test_missing_transport_consent_blocks_evaluation(svc):
    maria_confirmed(svc)
    case = svc.store.get_case(MARIA)
    case.consent = Consent(contact_for_checkins=True)
    svc.store.save_case(case)
    with pytest.raises(ConsentRequired) as exc:
        svc.evaluate_transport(MARIA, t_offers())
    assert exc.value.code == "CONSENT_MISSING"


def test_recovery_details_not_shared_without_consent(svc):
    maria_confirmed(svc)
    with pytest.raises(ConsentRequired):
        svc.request_recovery_handoff(MARIA, share_recovery_needs=False, granted_by="RESIDENT")
    assert svc.store.referrals_for_case(MARIA) == []
    assert svc.store.consent_grants_for_case(MARIA)[-1].granted is False  # decision still recorded


def test_recovery_payload_is_minimal(svc):
    maria_accepted(svc)
    view, created = svc.request_recovery_handoff(MARIA, share_recovery_needs=True, granted_by="RESIDENT")
    assert created and view["housing_secured"] is False
    assert view["shared_fields"] == ["destination_accessibility", "pet_count", "preferred_language",
                                     "service_animal", "wheelchair_accessible_vehicle"]


def test_consent_only_from_resident_or_caregiver(svc):
    maria_confirmed(svc)
    with pytest.raises(Unauthorized):
        svc.request_recovery_handoff(MARIA, share_recovery_needs=True, granted_by="transport_org_a")
    # Maria's emergency contact (Ana) may act as caregiver; the grant is attributed to her contact id.
    svc.request_recovery_handoff(MARIA, share_recovery_needs=True, granted_by="CAREGIVER")
    assert svc.store.consent_grants_for_case(MARIA)[-1].granted_by == "contact_ana_001"


def test_provider_payload_has_no_identity():
    case = Case(case_id="c", resident_id="r", zone_id="zone_3",
                consent=Consent(share_transport_needs=True, share_destination_needs=True))
    dumped = consent.transport_requirements(case).model_dump()
    assert not {"resident_id", "display_name", "contact_channel", "pickup_point"} & set(dumped)


def test_destination_evaluation_needs_destination_consent(svc):
    maria_confirmed(svc)
    case = svc.store.get_case(MARIA)
    case.consent = case.consent.model_copy(update={"share_destination_needs": False})
    svc.store.save_case(case)
    with pytest.raises(ConsentRequired):
        svc.evaluate_destination(MARIA, d_offers())

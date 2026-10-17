"""A request is not an assignment; an assignment is not a pickup; a pickup is not an arrival."""

import pytest

from doorstep.models import Assignment, Confirmation, Evidence
from doorstep.services.errors import Conflict, InsufficientEvidence, InvalidTransition
from doorstep.services.transitions import check_communication_transition, check_resident_transition

from .conftest import MARIA, arrival_evidence, maria_accepted, maria_proposed, pickup_evidence


def _assignment(**kw):
    base = dict(case_id="c", request_id="r", offer_id="o", provider_id="p", service_type="accessible_transport",
                provider_approved=True, service_area_allowed=True, zone_rule="OUTSIDE_ACTIVE_ORDER",
                idempotency_key="k", status="ACCEPTED", provider_response="ACCEPTED")
    base.update(kw)
    return Assignment(**base)


def test_provider_accepted_requires_accepted_assignment():
    with pytest.raises(InvalidTransition):
        check_resident_transition("NEEDS_ASSISTANCE", "PROVIDER_ACCEPTED", None)
    with pytest.raises(InvalidTransition):
        check_resident_transition("NEEDS_ASSISTANCE", "PROVIDER_ACCEPTED",
                                  _assignment(status="AWAITING_PROVIDER", provider_response="PENDING"))
    check_resident_transition("NEEDS_ASSISTANCE", "PROVIDER_ACCEPTED", _assignment())


def test_cannot_skip_states():
    for current, target in [("NEEDS_ASSISTANCE", "PICKUP_CONFIRMED"), ("NEEDS_ASSISTANCE", "ARRIVAL_CONFIRMED"),
                            ("PROVIDER_ACCEPTED", "ARRIVAL_CONFIRMED"), ("UNKNOWN", "PROVIDER_ACCEPTED"),
                            ("ARRIVAL_CONFIRMED", "NEEDS_ASSISTANCE")]:
        with pytest.raises(InvalidTransition):
            check_resident_transition(current, target, _assignment(confirmed_pickup_at="t", confirmed_arrival_at="t"))


def test_failed_delivery_cannot_become_no_reply():
    with pytest.raises(InvalidTransition):
        check_communication_transition("DELIVERY_FAILED", "NO_REPLY_AFTER_DEADLINE")


def test_proposal_does_not_change_resident_status(svc):
    maria_proposed(svc)
    assert svc.store.get_case(MARIA).resident_status == "NEEDS_ASSISTANCE"


def test_provider_acceptance_does_not_set_pickup_or_arrival(svc):
    ta, _ = maria_accepted(svc)
    assert svc.store.get_case(MARIA).resident_status == "PROVIDER_ACCEPTED"
    assert ta.confirmed_pickup_at is None and ta.confirmed_arrival_at is None
    view = svc.get_case_status(MARIA)
    assert view["map"]["color"] == "yellow"
    assert not view["evidence"]["pickup_confirmed"] and not view["evidence"]["arrival_confirmed"]


def test_pickup_does_not_set_arrival(svc):
    ta, _ = maria_accepted(svc)
    out = svc.confirm_pickup(ta.assignment_id, pickup_evidence(ta))
    assert out["resident_status"] == "PICKUP_CONFIRMED"
    assert out["assignment"]["confirmed_arrival_at"] is None
    assert svc.get_case_status(MARIA)["map"]["color"] == "blue"


def test_arrival_requires_pickup_first(svc):
    ta, da = maria_accepted(svc)
    with pytest.raises(InvalidTransition):
        svc.confirm_arrival(ta.assignment_id, arrival_evidence(da))


def test_arrival_requires_agreed_destination(svc):
    ta, da = maria_proposed(svc)
    svc.respond_assignment(ta.assignment_id, ta.provider_id, True)
    ta = svc.store.get_assignment(ta.assignment_id)
    svc.confirm_pickup(ta.assignment_id, pickup_evidence(ta))
    with pytest.raises(Conflict):
        svc.confirm_arrival(ta.assignment_id, arrival_evidence(da))
    assert svc.store.get_case(MARIA).resident_status == "PICKUP_CONFIRMED"


def test_green_only_after_arrival_evidence(svc):
    ta, da = maria_accepted(svc)
    svc.confirm_pickup(ta.assignment_id, pickup_evidence(ta))
    svc.confirm_arrival(ta.assignment_id, arrival_evidence(da))
    view = svc.get_case_status(MARIA)
    assert view["map"]["color"] == "green"
    assert view["evidence"]["timeline_replay_matches_status"]


def test_pickup_evidence_needs_provider_and_resident(svc):
    ta, _ = maria_accepted(svc)
    only_provider = Evidence(confirmations=[Confirmation(party="transport_provider", party_id=ta.provider_id)])
    with pytest.raises(InsufficientEvidence):
        svc.confirm_pickup(ta.assignment_id, only_provider)
    impostor = Evidence(confirmations=[Confirmation(party="transport_provider", party_id="transport_org_b"),
                                       Confirmation(party="resident", party_id="resident_001")])
    with pytest.raises(InsufficientEvidence):
        svc.confirm_pickup(ta.assignment_id, impostor)
    assert svc.store.get_case(MARIA).resident_status == "PROVIDER_ACCEPTED"


def test_duplicate_pickup_confirmation_is_idempotent(svc):
    ta, _ = maria_accepted(svc)
    svc.confirm_pickup(ta.assignment_id, pickup_evidence(ta))
    again = svc.confirm_pickup(ta.assignment_id, pickup_evidence(ta))
    assert again["duplicate"] is True
    assert len([v for v in svc.store.verifications_for_case(MARIA) if v.kind == "pickup"]) == 1

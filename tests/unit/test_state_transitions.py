"""A request is not an assignment; an assignment is not a pickup; a pickup is not an arrival."""

import pytest

from doorstep.models import Assignment, Confirmation
from doorstep.services.errors import InsufficientEvidence, InvalidTransition
from doorstep.services.transitions import check_communication_transition, check_resident_transition

from .conftest import MARIA, arrival_ev, maria_accepted, maria_proposed, pickup_ev


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
    aid = maria_accepted(svc)
    view = svc.get_case_status(MARIA)
    assert view["resident_status"] == "PROVIDER_ACCEPTED" and view["map"]["color"] == "yellow"
    assert view["active_assignment"]["assignment_id"] == aid
    assert view["active_assignment"]["confirmed_pickup_at"] is None
    assert view["active_assignment"]["confirmed_arrival_at"] is None


def test_pickup_before_acceptance_rejected(svc):
    aid = maria_proposed(svc)
    with pytest.raises(InvalidTransition):
        svc.confirm_pickup(aid, pickup_ev())


def test_pickup_does_not_set_arrival(svc):
    aid = maria_accepted(svc)
    out = svc.confirm_pickup(aid, pickup_ev())
    assert out["resident_status"] == "PICKUP_CONFIRMED" and out["confirmed_arrival_at"] is None
    assert svc.get_case_status(MARIA)["map"]["color"] == "blue"


def test_arrival_requires_pickup_first(svc):
    aid = maria_accepted(svc)
    with pytest.raises(InvalidTransition):
        svc.confirm_arrival(aid, arrival_ev())


def test_arrival_requires_accepted_destination(svc):
    aid = maria_proposed(svc)
    svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")  # destination never accepts
    svc.confirm_pickup(aid, pickup_ev())
    with pytest.raises(InvalidTransition) as exc:
        svc.confirm_arrival(aid, arrival_ev())
    assert "NO_AGREED_DESTINATION" in exc.value.reasons
    assert svc.store.get_case(MARIA).resident_status == "PICKUP_CONFIRMED"


def test_green_only_after_arrival_evidence(svc):
    aid = maria_accepted(svc)
    svc.confirm_pickup(aid, pickup_ev())
    out = svc.confirm_arrival(aid, arrival_ev())
    assert out["service_status"] == "COMPLETED"
    view = svc.get_case_status(MARIA)
    assert view["map"]["color"] == "green" and view["evidence"]["timeline_replay_matches_status"]


def test_pickup_evidence_needs_provider_and_resident(svc):
    aid = maria_accepted(svc)
    with pytest.raises(InsufficientEvidence):
        svc.confirm_pickup(aid, pickup_ev(resident_confirmed=False))
    with pytest.raises(InsufficientEvidence):
        svc.confirm_pickup(aid, pickup_ev(provider_confirmed=False))
    assert svc.store.get_case(MARIA).resident_status == "PROVIDER_ACCEPTED"


def test_identified_confirmations_are_checked(svc):
    aid = maria_accepted(svc)
    impostor = pickup_ev(confirmations=[Confirmation(party="transport_provider", party_id="transport_org_b")])
    with pytest.raises(InsufficientEvidence):
        svc.confirm_pickup(aid, impostor)
    good = pickup_ev(confirmations=[Confirmation(party="transport_provider", party_id="transport_org_a"),
                                    Confirmation(party="resident", party_id="resident_001")])
    svc.confirm_pickup(aid, good)
    assert svc.store.verifications_for_case(MARIA)[-1].party_ids_verified is True


def test_arrival_checkin_must_come_from_agreed_destination(svc):
    aid = maria_accepted(svc)
    svc.confirm_pickup(aid, pickup_ev())
    with pytest.raises(InsufficientEvidence):
        svc.confirm_arrival(aid, arrival_ev(destination_provider_id="destination_org_b"))
    with pytest.raises(InsufficientEvidence):
        svc.confirm_arrival(aid, arrival_ev(provider_confirmed=False))


def test_duplicate_pickup_confirmation_is_idempotent(svc):
    aid = maria_accepted(svc)
    svc.confirm_pickup(aid, pickup_ev())
    assert svc.confirm_pickup(aid, pickup_ev())["duplicate"] is True
    assert len([v for v in svc.store.verifications_for_case(MARIA) if v.kind == "pickup"]) == 1

"""Atomic acceptance, idempotency, delayed replies, declines."""

import pytest

from doorstep.services.errors import Conflict, InvalidTransition, Unauthorized

from .conftest import MARIA, maria_confirmed, maria_evaluated, maria_proposed, t_offers


def test_duplicate_acceptance_is_idempotent(svc):
    aid = maria_proposed(svc)
    svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")
    again = svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")
    assert again["duplicate"] is True
    accepted = [a for a in svc.store.assignments_for_case(MARIA, "accessible_transport") if a.status == "ACCEPTED"]
    assert len(accepted) == 1


def test_repeated_idempotency_key_returns_original(svc):
    maria_evaluated(svc)
    v1, created1 = svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", idempotency_key="k1")
    v2, created2 = svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", idempotency_key="k1")
    assert (created1, created2) == (True, False) and v1["assignment_id"] == v2["assignment_id"]


def test_only_one_accepted_assignment_and_late_reply_cannot_revive(svc):
    maria_evaluated(svc)
    a, _ = svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", idempotency_key="ka")
    e, _ = svc.propose_assignment(MARIA, transport_offer_id="offer_t_005", idempotency_key="ke")
    svc.respond_assignment(a["assignment_id"], "transport_org_a", "ACCEPTED")
    assert svc.store.get_assignment(e["assignment_id"]).status == "CANCELED"
    with pytest.raises(InvalidTransition):
        svc.respond_assignment(e["assignment_id"], "transport_org_e", "ACCEPTED")  # delayed acceptance
    accepted = [x for x in svc.store.assignments_for_case(MARIA, "accessible_transport") if x.status == "ACCEPTED"]
    assert [x.provider_id for x in accepted] == ["transport_org_a"]
    assert any(ev.event_type == "LATE_RESPONSE_IGNORED" for ev in svc.events.for_case(MARIA))


def test_cannot_propose_after_acceptance(svc):
    aid = maria_proposed(svc)
    svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")
    with pytest.raises(Conflict):
        svc.propose_assignment(MARIA, transport_offer_id="offer_t_005", idempotency_key="other")


def test_wrong_provider_cannot_respond(svc):
    aid = maria_proposed(svc)
    with pytest.raises(Unauthorized):
        svc.respond_assignment(aid, "transport_org_b", "ACCEPTED")
    assert svc.store.get_assignment(aid).status == "AWAITING_PROVIDER"


def test_destination_provider_responds_on_same_assignment_id(svc):
    aid = maria_proposed(svc)
    out = svc.respond_assignment(aid, "destination_org_a", "ACCEPTED")
    assert out["service_type"] == "accessible_destination" and out["pickup_details"] is None
    assert out["resident_status"] == "NEEDS_ASSISTANCE"  # destination acceptance is not transport acceptance


def test_decline_offers_alternate_provider(svc):
    aid = maria_proposed(svc)
    out = svc.respond_assignment(aid, "transport_org_a", "DECLINED")
    assert out["service_status"] == "DECLINED" and out["resident_status"] == "NEEDS_ASSISTANCE"
    assert "offer_t_005" in out["next_step"]
    alt, _ = svc.propose_assignment(MARIA, transport_offer_id="offer_t_005", idempotency_key="alt")
    assert alt["service_status"] == "AWAITING_PROVIDER"
    with pytest.raises(Conflict):  # declined provider is not silently re-proposed
        svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", idempotency_key="again")


def test_all_providers_decline_leaves_case_unresolved(svc):
    maria_evaluated(svc)
    for oid, pid in (("offer_t_001", "transport_org_a"), ("offer_t_005", "transport_org_e")):
        view, _ = svc.propose_assignment(MARIA, transport_offer_id=oid, idempotency_key=oid)
        svc.respond_assignment(view["assignment_id"], pid, "DECLINED")
    view = svc.get_case_status(MARIA)
    assert view["resident_status"] == "REQUIRES_COORDINATOR" and view["unresolved"] is True
    assert view["evidence"]["provider_accepted"] is False


def test_provider_cancel_after_acceptance_returns_to_needs_assistance(svc):
    aid = maria_proposed(svc)
    svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")
    out = svc.respond_assignment(aid, "transport_org_a", "DECLINED")
    assert out["service_status"] == "CANCELED" and out["resident_status"] == "NEEDS_ASSISTANCE"


def test_no_eligible_offers_means_unresolved(svc):
    maria_confirmed(svc)
    out = svc.evaluate_transport(MARIA, [], "req_empty")
    assert out["eligible"] == [] and out["escalation_required"] is True
    assert svc.store.get_case(MARIA).resident_status == "REQUIRES_COORDINATOR"


def test_offer_ids_are_scoped_per_case(svc):
    maria_evaluated(svc)
    from .conftest import david_confirmed
    david_confirmed(svc)
    svc.evaluate_transport("case_david_002", t_offers(), "req_101")
    assert svc.store.get_offer(MARIA, "offer_t_001").eligible is True
    assert svc.store.get_offer("case_david_002", "offer_t_001").eligible is False

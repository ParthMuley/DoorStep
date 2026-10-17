"""Atomic acceptance, idempotency, delayed replies, declines."""

import pytest

from doorstep.services.errors import Conflict, Unauthorized

from .conftest import MARIA, eligible, maria_confirmed, maria_proposed


def test_duplicate_acceptance_is_idempotent(svc):
    ta, _ = maria_proposed(svc)
    svc.respond_assignment(ta.assignment_id, ta.provider_id, True)
    again = svc.respond_assignment(ta.assignment_id, ta.provider_id, True)
    assert again["duplicate"] is True
    accepted = [a for a in svc.store.assignments_for_case(MARIA, "accessible_transport") if a.status == "ACCEPTED"]
    assert len(accepted) == 1
    assert svc.store.get_transport_provider(ta.provider_id).available_trips == 0  # decremented once


def test_duplicate_proposal_returns_same_assignment(svc):
    maria_confirmed(svc)
    offer = eligible(svc.find_transport(MARIA))
    a1 = svc.propose_assignment(MARIA, offer["offer_id"])
    a2 = svc.propose_assignment(MARIA, offer["offer_id"])
    assert a1.assignment_id == a2.assignment_id


def test_only_one_accepted_assignment_and_late_reply_cannot_revive(svc):
    maria_confirmed(svc)
    t = svc.find_transport(MARIA)
    a = svc.propose_assignment(MARIA, eligible(t, "transport_org_a")["offer_id"])
    e = svc.propose_assignment(MARIA, eligible(t, "transport_org_e")["offer_id"])
    svc.respond_assignment(a.assignment_id, a.provider_id, True)
    assert svc.store.get_assignment(e.assignment_id).status == "CANCELED"
    with pytest.raises(Conflict):
        svc.respond_assignment(e.assignment_id, e.provider_id, True)  # delayed acceptance
    accepted = [x for x in svc.store.assignments_for_case(MARIA, "accessible_transport") if x.status == "ACCEPTED"]
    assert [x.provider_id for x in accepted] == ["transport_org_a"]
    assert any(ev.event_type == "LATE_RESPONSE_IGNORED" for ev in svc.events.for_case(MARIA))


def test_wrong_provider_cannot_respond(svc):
    ta, _ = maria_proposed(svc)
    with pytest.raises(Unauthorized):
        svc.respond_assignment(ta.assignment_id, "transport_org_b", True)
    assert svc.store.get_assignment(ta.assignment_id).status == "AWAITING_PROVIDER"


def test_decline_offers_alternate_provider(svc):
    ta, _ = maria_proposed(svc)
    out = svc.respond_assignment(ta.assignment_id, ta.provider_id, False)
    assert out["assignment"]["status"] == "DECLINED"
    assert out["resident_status"] == "NEEDS_ASSISTANCE"
    assert "transport_org_e" in out["next_step"]
    t = svc.find_transport(MARIA)
    alt = svc.propose_assignment(MARIA, eligible(t, "transport_org_e")["offer_id"])
    assert alt.status == "AWAITING_PROVIDER"
    with pytest.raises(Conflict):  # declined provider cannot be silently re-proposed
        svc.propose_assignment(MARIA, eligible(t, "transport_org_a")["offer_id"])


def test_all_providers_decline_leaves_case_unresolved(svc):
    maria_confirmed(svc)
    t = svc.find_transport(MARIA)
    for pid in ("transport_org_a", "transport_org_e"):
        a = svc.propose_assignment(MARIA, eligible(t, pid)["offer_id"])
        svc.respond_assignment(a.assignment_id, pid, False)
    view = svc.get_case_status(MARIA)
    assert view["case"]["resident_status"] == "REQUIRES_COORDINATOR"
    assert view["unresolved"] is True
    assert view["evidence"]["assistance_confirmed"] is False


def test_provider_cancel_after_acceptance_returns_to_needs_assistance(svc):
    ta, _ = maria_proposed(svc)
    svc.respond_assignment(ta.assignment_id, ta.provider_id, True)
    out = svc.respond_assignment(ta.assignment_id, ta.provider_id, False)
    assert out["assignment"]["status"] == "CANCELED"
    assert out["resident_status"] == "NEEDS_ASSISTANCE"

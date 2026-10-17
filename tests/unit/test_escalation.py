"""Escalation acknowledgment is never assistance."""

import pytest

from doorstep.services.errors import Conflict

from .conftest import DAVID, MARIA, david_confirmed, maria_confirmed


def test_ack_does_not_imply_assistance(svc):
    david_confirmed(svc)
    svc.find_transport(DAVID)
    esc = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert esc.status == "ACKNOWLEDGED_REQUEST_ONLY"
    assert esc.assistance_confirmed is False
    view = svc.get_case_status(DAVID)
    assert view["unresolved"] is True
    assert view["evidence"]["assistance_confirmed"] is False
    assert view["case"]["resident_status"] == "REQUIRES_COORDINATOR"
    assert "UNRESOLVED" in view["summary_text"]


def test_no_acknowledgment_stays_unresolved_with_next_step(svc):
    david_confirmed(svc)
    svc.set_escalation_ack(False)
    esc = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert esc.status == "NO_ACKNOWLEDGMENT"
    view = svc.get_case_status(DAVID)
    assert view["unresolved"] and "follow up" in view["next_step"]


def test_escalation_is_idempotent(svc):
    david_confirmed(svc)
    a = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    b = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert a.escalation_id == b.escalation_id
    assert len(svc.store.escalations_for_case(DAVID)) == 1


def test_active_order_reason_must_match_zone(svc):
    maria_confirmed(svc)
    with pytest.raises(Conflict):
        svc.escalate_case(MARIA, "ACTIVE_EVACUATION_ORDER_ZONE")

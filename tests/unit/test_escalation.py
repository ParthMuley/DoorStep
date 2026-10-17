"""Escalation acknowledgment is never assistance."""

import pytest

from doorstep.services.errors import Conflict

from .conftest import DAVID, MARIA, david_confirmed, maria_confirmed, t_offers, warn


def test_ack_does_not_imply_assistance(svc):
    david_confirmed(svc)
    svc.evaluate_transport(DAVID, t_offers(), "req_101")
    esc, created = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert created and esc["status"] == "ACKNOWLEDGED_REQUEST_ONLY" and esc["assistance_confirmed"] is False
    assert esc["resident_status"] == "REQUIRES_COORDINATOR" and esc["service_status"] == "UNRESOLVED"
    view = svc.get_case_status(DAVID)
    assert view["unresolved"] and view["evidence"]["provider_accepted"] is False
    assert "UNRESOLVED" in view["summary_text"]


def test_no_acknowledgment_stays_unresolved_with_next_step(svc):
    david_confirmed(svc)
    svc.set_escalation_ack(False)
    esc, _ = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert esc["status"] == "NO_ACKNOWLEDGMENT"
    view = svc.get_case_status(DAVID)
    assert view["unresolved"] and "follow up" in view["next_step"]


def test_escalation_is_idempotent(svc):
    david_confirmed(svc)
    a, c1 = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE", idempotency_key="k")
    b, c2 = svc.escalate_case(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE", idempotency_key="k")
    assert (c1, c2) == (True, False) and a["escalation_id"] == b["escalation_id"]
    assert len(svc.store.escalations_for_case(DAVID)) == 1


def test_active_order_reason_must_match_zone(svc):
    maria_confirmed(svc)
    with pytest.raises(Conflict):
        svc.escalate_case(MARIA, "ACTIVE_EVACUATION_ORDER_ZONE")


def test_no_reply_escalation_only_after_deadline(svc):
    warn(svc)
    with pytest.raises(Conflict):
        svc.escalate_case(MARIA, "NO_REPLY_AFTER_DEADLINE")
    svc.mark_no_reply_deadline(MARIA)
    esc, _ = svc.escalate_case(MARIA, "NO_REPLY_AFTER_DEADLINE")
    assert esc["assistance_confirmed"] is False and esc["resident_status"] == "REQUIRES_COORDINATOR"

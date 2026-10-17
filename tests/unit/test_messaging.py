"""Message semantics: unknown senders, duplicates, silence, failures, DEMO labels."""

import pytest

from doorstep.services.errors import Conflict, Unauthorized

from .conftest import t_offers
from .conftest import DAVID, DAVID_CAREGIVER_SENDER, MARIA, MARIA_SENDER, warn


def test_every_outbound_message_is_demo_labeled_and_localized(svc):
    warn(svc)
    out = [m for m in svc.store.list_messages() if m.direction == "outbound"]
    assert out and all(m.body.startswith("DOORSTEP DEMO") for m in out)
    assert all("simulation" in m.body.lower() or "simulación" in m.body.lower() for m in out)
    maria = next(m for m in out if m.case_id == MARIA)
    assert maria.language == "es" and "NECESITO AYUDA" in maria.body


def test_new_case_starts_unknown(svc):
    warn(svc)
    assert svc.store.get_case(MARIA).resident_status == "UNKNOWN"
    assert svc.store.get_case(MARIA).communication_status == "SENT"


def test_unknown_sender_cannot_update_case(svc):
    warn(svc)
    before = svc.store.get_case(MARIA)
    with pytest.raises(Unauthorized):
        svc.submit_resident_response(MARIA, "1", "es", sender="sim_phone_stranger")
    with pytest.raises(Unauthorized):
        svc.inbound_sms("sim_phone_stranger", "1 NEED HELP")
    after = svc.store.get_case(MARIA)
    assert after.resident_status == before.resident_status
    assert after.communication_status == before.communication_status


def test_caregiver_may_reply_for_resident(svc):
    warn(svc)
    out = svc.submit_resident_response(DAVID, "1", "en", sender=DAVID_CAREGIVER_SENDER)
    assert out["resident_status"] == "NEEDS_ASSISTANCE"


def test_duplicate_inbound_message_is_ignored(svc):
    warn(svc)
    svc.submit_resident_response(MARIA, "1", "es", sender=MARIA_SENDER, external_id="dup-1")
    events_before = len([e for e in svc.events.for_case(MARIA) if e.event_type == "RESIDENT_REPLIED"])
    again = svc.submit_resident_response(MARIA, "1", "es", sender=MARIA_SENDER, external_id="dup-1")
    assert again["duplicate"] is True
    events_after = len([e for e in svc.events.for_case(MARIA) if e.event_type == "RESIDENT_REPLIED"])
    assert events_before == events_after == 1


def test_no_reply_does_not_imply_danger_or_safety(svc):
    warn(svc)
    out = svc.mark_no_reply_deadline(MARIA)
    case = svc.store.get_case(MARIA)
    assert case.communication_status == "NO_REPLY_AFTER_DEADLINE"
    assert case.resident_status == "UNKNOWN"  # neither NEEDS_ASSISTANCE nor safe
    assert "not evidence" in out["next_step"].lower()
    assert svc.get_case_status(MARIA)["map"]["color"] == "gray"


def test_failed_delivery_does_not_imply_no_reply(svc):
    warn(svc)
    checkin = next(m for m in svc.store.list_messages(MARIA) if m.direction == "outbound")
    svc.set_delivery_outcome(checkin.message_id, delivered=False)
    svc.mark_no_reply_deadline(MARIA)
    case = svc.store.get_case(MARIA)
    assert case.communication_status == "DELIVERY_FAILED"
    assert case.resident_status == "UNKNOWN"


def test_delivery_receipts_are_never_invented(svc):
    warn(svc)
    checkin = next(m for m in svc.store.list_messages(MARIA) if m.direction == "outbound")
    assert checkin.status == "SENT"


def test_unverified_report_never_activates_checkins(svc):
    out = svc.start_demo_warning("zone_3", alert_source="USER_REPORT")
    assert out["verified"] is False and out["case_ids"] == [] and out["checkins"] == []
    assert svc.store.list_cases() == []
    assert svc.store.list_messages() == []


def test_needs_used_only_after_confirmation(svc):
    warn(svc)
    svc.submit_resident_response(MARIA, "Necesito ayuda, uso silla de ruedas", "es", sender=MARIA_SENDER)
    with pytest.raises(Conflict) as exc:
        svc.evaluate_transport(MARIA, t_offers())
    assert exc.value.code == "NEEDS_NOT_CONFIRMED"
    case = svc.store.get_case(MARIA)
    assert case.pending_candidate_needs is not None and not case.needs_confirmed


def test_resident_saying_no_routes_to_coordinator(svc):
    warn(svc)
    svc.submit_resident_response(MARIA, "1", "es", sender=MARIA_SENDER)
    out = svc.submit_resident_response(MARIA, "No", "es", sender=MARIA_SENDER)
    assert out["resident_status"] == "REQUIRES_COORDINATOR"
    assert out["needs_confirmed"] is False


def test_original_text_preserved(svc):
    warn(svc)
    text = "Tengo un perro y uso silla de ruedas"
    out = svc.submit_resident_response(MARIA, text, "es", sender=MARIA_SENDER)
    assert out["original_text"] == text
    inbound = [m for m in svc.store.list_messages(MARIA) if m.direction == "inbound"]
    assert inbound[-1].body == text


def test_has_plan_is_self_reported_not_resolved(svc):
    warn(svc)
    out = svc.submit_resident_response(MARIA, "2", "es", sender=MARIA_SENDER)
    assert out["resident_status"] == "UNKNOWN"
    assert "not verified" in out["next_step"]

"""Card payloads follow the documented ASI:One card transport and limits."""

import json

import pytest

from doorstep.integrations.asi_cards import (
    Card,
    CardValidationError,
    case_card,
    escalation_card,
    info_card,
    match_card,
    parse_card_selection,
)


def metadata_of(card: Card) -> tuple[str, dict]:
    msg = card.to_message()
    text = msg.content[0].text
    meta = msg.content[1].metadata
    return text, meta


def test_case_card_message_shape_and_fallback():
    card = case_card(case_id="case_maria_001", display_name="Maria (synthetic)", map_color="yellow",
                     map_label="Volunteer accepted (not yet picked up)", zone_status="WARNING",
                     steps=[("REQUESTED", True, "18:02Z"), ("PROVIDER_ACCEPTED", True, "18:06Z"),
                            ("PICKUP_CONFIRMED", False, None), ("ARRIVAL_CONFIRMED", False, None)],
                     next_step="Awaiting pickup confirmation.", communication_status="REPLIED")
    text, meta = metadata_of(card)
    assert meta["card_protocol_version"] == "1"
    assert meta["card_kind"] == "detail"
    assert meta["requires_card_interaction"] == "true"
    assert all(isinstance(v, str) for v in meta.values())
    payload = json.loads(meta["card_payload"])
    assert payload["title"].startswith("SIMULATION")
    assert payload["ctas"][0]["selection"] == {"action": "case_status", "case_id": "case_maria_001"}
    # Plain-text fallback carries the same facts.
    assert text.startswith("DOORSTEP DEMO - SIMULATION ONLY.")
    assert "YELLOW - volunteer accepted" in text and "Pickup Confirmed: not yet" in text


def test_match_card_is_review_with_approve_selection():
    card = match_card(case_id="case_maria_001", display_name="Maria (synthetic)",
                      chosen=[{"label": "volunteer_sarah (WHEELCHAIR_VAN)", "reasons": ["WHEELCHAIR_OK", "PET_OK"]}],
                      rejected=[{"label": "volunteer_joe (SEDAN)", "reasons": ["NO_WHEELCHAIR_SPACE"]}],
                      shelter={"label": "dest_center_a", "reasons": ["STEP_FREE_OK"]},
                      assignment_id="assign_001", escalation_required=False, no_match_reason=None)
    text, meta = metadata_of(card)
    payload = json.loads(meta["card_payload"])
    assert meta["card_kind"] == "review"
    assert payload["approve_cta"]["selection"]["action"] == "approve"
    assert "nothing is confirmed until the volunteer accepts" in text
    assert "NO_WHEELCHAIR_SPACE" in text


def test_no_match_never_shows_approve():
    card = match_card(case_id="case_david_002", display_name="David (synthetic)", chosen=[], rejected=[],
                      shelter=None, assignment_id=None, escalation_required=True, no_match_reason="ORDER_ZONE")
    text, meta = metadata_of(card)
    payload = json.loads(meta["card_payload"])
    assert meta["card_kind"] == "detail"
    assert "approve_cta" not in payload
    assert "assistance not confirmed" in text


def test_escalation_card_never_claims_assistance():
    text, _ = metadata_of(escalation_card(case_id="case_david_002", display_name="David (synthetic)",
                                          reason="ACTIVE_EVACUATION_ORDER_ZONE", status="ACKNOWLEDGED_REQUEST_ONLY",
                                          next_step="Coordinator follow-up"))
    assert "UNRESOLVED" in text and "receipt only" in text


def test_info_card_is_terminal():
    _, meta = metadata_of(info_card("Data health", [("Feed", "STALE")], "Feed is stale.", "SYNTHETIC_CALOES"))
    assert meta["is_terminal"] == "true"
    assert meta["requires_card_interaction"] == "false"


def test_validation_rejects_bad_cards():
    with pytest.raises(CardValidationError):
        Card("detail", {"title": "No sim prefix", "summary_rows": []}, "x").to_message()
    with pytest.raises(CardValidationError):
        Card("detail", {"title": "SIMULATION big", "summary_rows": [{"label": "a", "value": "x" * 70000}]},
             "x").to_message()
    with pytest.raises(CardValidationError):
        Card("review", {"title": "SIMULATION", "summary_rows": []}, "x").to_message()


def test_parse_card_selection():
    assert parse_card_selection('{"action": "approve", "case_id": "case_maria_001"}') == {
        "action": "approve", "case_id": "case_maria_001"}
    assert parse_card_selection('@doorstep {"action":"case_status","case_id":"c1"}')["case_id"] == "c1"
    assert parse_card_selection("approve the arrangement for Maria") is None
    assert parse_card_selection("{not json}") is None

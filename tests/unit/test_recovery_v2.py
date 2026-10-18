"""B5: post-calamity help (contract v2.1 §5.8). A referral is not completed assistance."""

import pytest

from doorstep.models import Evidence
from doorstep.services.errors import Conflict, ConsentRequired, InvalidTransition, Unauthorized

from .test_matching_v2 import MARIA, MARIA_SENDER, accept, accept_shelter, propose, ready

NETWORK = {"X-Agent-Token": "change-me-network-agent-token"}
HOUSING_EVIDENCE = {"type": "SIMULATED_SERVICE_CONFIRMED", "reference": "res_sim_001"}


def arrived(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    accept_shelter(svc, aid)
    svc.confirm_pickup(aid, Evidence(type="VOLUNTEER_AND_RESIDENT_CONFIRMATION", volunteer_confirmed=True,
                                     resident_confirmed=True))
    svc.confirm_arrival(aid, Evidence(type="SHELTER_CHECKIN", shelter_org_id="civic_shelter_demo",
                                      site_id="dest_center_a", shelter_confirmed=True))


def request(svc, types=("TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"), consent=True, key=None, granted_by="RESIDENT"):
    view, _ = svc.recovery.request(MARIA, share_recovery_needs=consent, granted_by=granted_by,
                                   help_types=list(types), idempotency_key=key)
    return view


def test_only_after_arrival(svc):
    ready(svc)
    with pytest.raises(InvalidTransition):
        request(svc)


def test_self_reported_departure_may_request(svc):
    from .test_matching_v2 import alert_and_outreach
    alert_and_outreach(svc)
    svc.submit_resident_response(MARIA, "3 ya salí", "es", sender=MARIA_SENDER, external_id="left")
    assert request(svc, types=["INSURANCE_GUIDANCE"])["referrals"][0]["status"] == "REQUESTED"


def test_no_consent_shares_nothing(svc):
    arrived(svc)
    with pytest.raises(ConsentRequired):
        request(svc, consent=False)
    assert [r for r in svc.store.referrals_for_case(MARIA) if r.help_type] == []
    assert svc.store.consent_grants_for_case(MARIA)[-1].granted is False


def test_one_referral_per_type_nearest_org_minimal_payload(svc):
    arrived(svc)
    view = request(svc)
    refs = {r["help_type"]: r for r in view["referrals"]}
    housing, insurance = refs["TEMPORARY_HOUSING"], refs["INSURANCE_GUIDANCE"]
    assert housing["org_id"] == "red_cross_demo" and housing["region_id"] == "la_county:east_valley"
    # Housing gets accessibility needs (transfer help 2 is a transport-only need) and pets; insurance only language.
    assert housing["shared_payload"]["needs"] == [1, 4, 6] and housing["shared_payload"]["pet_count"] == 1
    assert set(insurance["shared_payload"]) == {"referral_id", "help_type", "language"}
    for r in view["referrals"]:
        assert not {"phone", "address", "name", "resident_id", "emergency_contacts"} & set(r["shared_payload"])
    assert view["recovery_status"] == "REQUESTED" and view["housing_secured"] is False


def test_requests_are_idempotent_and_never_duplicated(svc):
    arrived(svc)
    first = request(svc, key="k1")
    assert request(svc, key="k1")["duplicate"] is True
    again = request(svc, key="k2")  # new key, same help types: existing referrals are reused
    assert {r["referral_id"] for r in again["referrals"]} == {r["referral_id"] for r in first["referrals"]}
    assert len([r for r in svc.store.referrals_for_case(MARIA) if r.help_type]) == 2


def test_unknown_help_type_rejected_and_unmatched_listed(svc):
    arrived(svc)
    with pytest.raises(ValueError):
        request(svc, types=["FREE_MONEY"])
    view = request(svc, types=["SUPPLIES"])  # nobody offers supplies in the seed
    assert view["referrals"] == [] and view["unmatched_help_types"] == ["SUPPLIES"]


def test_respond_lifecycle_and_housing_secured(svc):
    arrived(svc)
    refs = {r["help_type"]: r for r in request(svc)["referrals"]}
    h = refs["TEMPORARY_HOUSING"]
    with pytest.raises(Unauthorized):
        svc.recovery.respond(h["referral_id"], org_id="recovery_housing_demo", decision="ACCEPTED")
    acc = svc.recovery.respond(h["referral_id"], org_id=h["org_id"], decision="ACCEPTED")
    assert acc["status"] == "ACCEPTED" and acc["housing_secured"] is False
    assert any(m.template_id == "recovery_accepted" for m in svc.store.list_messages(MARIA))
    with pytest.raises(Conflict) as exc:
        svc.recovery.respond(h["referral_id"], org_id=h["org_id"], decision="COMPLETED")
    assert exc.value.code == "INSUFFICIENT_EVIDENCE"
    done = svc.recovery.respond(h["referral_id"], org_id=h["org_id"], decision="COMPLETED", evidence=HOUSING_EVIDENCE)
    assert done["housing_secured"] is True
    with pytest.raises(InvalidTransition):
        svc.recovery.respond(h["referral_id"], org_id=h["org_id"], decision="DECLINED")
    i = refs["INSURANCE_GUIDANCE"]
    assert svc.recovery.respond(i["referral_id"], org_id=i["org_id"], decision="COMPLETED",
                                evidence=HOUSING_EVIDENCE)["housing_secured"] is False  # only housing can secure housing
    view = svc.get_case_status(MARIA)["recovery"]
    assert view["status"] == "COMPLETED" and view["housing_secured"] is True


def test_decline_suggests_next_org_and_rerequest_goes_there(svc):
    arrived(svc)
    h = next(r for r in request(svc, types=["TEMPORARY_HOUSING"], key="a")["referrals"])
    out = svc.recovery.respond(h["referral_id"], org_id=h["org_id"], decision="DECLINED")
    assert out["status"] == "UNRESOLVED" and out["next_alternate"]["org_id"] == "recovery_housing_demo"
    again = request(svc, types=["TEMPORARY_HOUSING"], key="b")["referrals"][0]
    assert again["org_id"] == "recovery_housing_demo" and again["referral_id"] != h["referral_id"]


def test_sms_reply_after_arrival_records_consent(svc):
    arrived(svc)
    svc.submit_resident_response(MARIA, "SI", "es", sender=MARIA_SENDER, external_id="si-recovery")
    assert svc.store.get_resident_profile("resident_001").consents["RECOVERY"] is True
    assert svc.store.consent_grants_for_case(MARIA)[-1].granted_by == "resident_001"
    svc.submit_resident_response(MARIA, "NO", "es", sender=MARIA_SENDER, external_id="no-recovery")
    assert svc.store.get_resident_profile("resident_001").consents["RECOVERY"] is False
    assert svc.get_case_status(MARIA)["resident_status"] == "ARRIVAL_CONFIRMED"  # NO doesn't send her to coordinator


def test_caregiver_can_consent(svc):
    arrived(svc)
    request(svc, types=["INSURANCE_GUIDANCE"], granted_by="CAREGIVER")
    assert svc.store.consent_grants_for_case(MARIA)[-1].granted_by == "contact_ana_001"


def test_http_respond_needs_network_token(client):
    svc = client.app.state.service
    arrived(svc)
    r = client.post(f"/cases/{MARIA}/recovery", json={"consent": {"share_recovery_needs": True, "granted_by": "RESIDENT"},
                                                    "help_types": ["TEMPORARY_HOUSING"]})
    assert r.status_code == 201 and r.json()["schema_version"] == "2.0"
    ref = r.json()["referrals"][0]
    body = {"org_id": ref["org_id"], "decision": "ACCEPTED"}
    assert client.post(f"/recovery/{ref['referral_id']}/respond", json=body).status_code == 403
    assert client.post(f"/recovery/{ref['referral_id']}/respond", json=body, headers=NETWORK).status_code == 200
    bad = client.post(f"/cases/{MARIA}/recovery", json={"consent": {"share_recovery_needs": True,
                                                                  "granted_by": "RESIDENT"}, "help_types": ["NOPE"]})
    assert bad.status_code == 422

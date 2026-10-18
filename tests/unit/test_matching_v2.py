"""B4: matching against org-DB volunteers, reservation, accept/decline, escalation."""

import pytest

from doorstep.models import ResidentProfile
from doorstep.services.errors import Conflict, InsufficientEvidence, InvalidTransition, SafetyRejection, Unauthorized

from .conftest import DAVID, DAVID_SENDER, MARIA, MARIA_SENDER

SIM = "SYNTHETIC_CALOES"


def ingest(svc):
    return svc.alerts.ingest(source_id=SIM, source_type="OFFICIAL_SIMULATION", url="t", fetched_at=None,
                             fetch_ok=True, http_status=200, error=None,
                             payload=svc.alerts.feed.render_caloes(), idempotency_key=None)


def alert_and_outreach(svc, replies=None):
    svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_WILDFIRE")
    poll = ingest(svc)
    alert_id = next(a["alert_id"] for a in poll["new_alerts"] if a["status"] == "WARNING")
    for org in ("neighbor_sedans_demo", "eastside_rides_demo", "red_cross_demo"):
        svc.alerts.start_outreach(org, alert_id)
    replies = replies if replies is not None else {"sim_phone_sarah": "YES", "sim_phone_joe": "YES",
                                                   "sim_phone_maya": "NO", "sim_phone_lee": "YES"}
    for phone, text in replies.items():
        svc.inbound_sms(phone, text, external_id=f"x-{phone}")
    return alert_id


def confirm(svc, case_id=MARIA, sender=MARIA_SENDER):
    svc.submit_resident_response(case_id, "1 necesito ayuda", None, sender=sender, external_id=f"{case_id}-1")
    svc.submit_resident_response(case_id, "SI", None, sender=sender, external_id=f"{case_id}-2")


def ready(svc, **kw):
    alert_id = alert_and_outreach(svc, **kw)
    confirm(svc)
    return alert_id


def propose(svc, case_id=MARIA, **kw):
    view, _ = svc.matching.propose(case_id, **kw)
    return view


def accept(svc, aid, org="eastside_rides_demo", volunteer="volunteer_sarah", decision="ACCEPTED", **kw):
    return svc.matching.accept(aid, org_id=org, volunteer_id=volunteer, decision=decision, **kw)


def accept_shelter(svc, aid, org="civic_shelter_demo", site="dest_center_a"):
    return svc.matching.accept(aid, org_id=org, site_id=site, decision="ACCEPTED")


def volunteer(svc, org, vid):
    return next(v for v in svc.store.get_organization(org).volunteers if v.volunteer_id == vid)


# ------------------------------------------------------------ eligibility
def test_evaluation_explains_every_volunteer(svc):
    ready(svc)
    ev = propose(svc, create_proposal=False)["evaluation"]["volunteers"]
    assert [v["volunteer_id"] for v in ev["eligible"]] == ["volunteer_sarah", "volunteer_lee"]
    rejected = {v["volunteer_id"]: v for v in ev["rejected"]}
    assert rejected["volunteer_joe"]["missing_needs"] == [1, 2]
    assert "NO_WHEELCHAIR_SPACE" in rejected["volunteer_joe"]["reason_codes"]
    assert rejected["volunteer_maya"]["reason_codes"][0] == "UNAVAILABLE"
    assert "ORG_NOT_APPROVED" in rejected["volunteer_tom"]["reason_codes"]
    assert "CALAMITY_TYPE_NOT_SUPPORTED" in rejected["volunteer_rina"]["reason_codes"]
    # Evaluation only: nobody is reserved.
    assert volunteer(svc, "eastside_rides_demo", "volunteer_sarah").reserved_case_id is None


def test_spanish_speaker_code_never_blocks(svc):
    ready(svc)
    svc.registry.register_resident(ResidentProfile(
        resident_id="resident_rosa", name="Rosa (synthetic)", phone="sim_phone_rosa", language="es",
        address={"label": "SYNTHETIC", "lat": 34.1000, "lon": -118.0950}, needs=[4, 7], pet_count=1,
        consents={"CHECKIN": True, "TRANSPORT": True, "DESTINATION": True}))
    # Maya can't do code 7? She can; Lee can't (caps [1,2,4,5]) yet must stay eligible for a Spanish speaker.
    svc.alerts.feed.trigger("UPDATE", preset="ZONE_3_WILDFIRE")
    ingest(svc)
    confirm(svc, case_id="case_resident_rosa", sender="sim_phone_rosa")
    ev = propose(svc, case_id="case_resident_rosa", create_proposal=False)["evaluation"]["volunteers"]
    assert "volunteer_lee" in [v["volunteer_id"] for v in ev["eligible"]]


def test_availability_must_be_for_this_alert(svc):
    ready(svc, replies={})  # asked, nobody answered
    ev = propose(svc, create_proposal=False)["evaluation"]["volunteers"]["rejected"]
    assert next(v for v in ev if v["volunteer_id"] == "volunteer_sarah")["reason_codes"][0] == "AWAITING_REPLY"
    view = propose(svc)
    assert view["match"] is None and view["no_match_reason"] == "NO_AVAILABLE_VOLUNTEER"


def test_only_unsuitable_volunteers_available(svc):
    ready(svc, replies={"sim_phone_joe": "YES"})
    view = propose(svc)
    assert view["no_match_reason"] == "NO_SUITABLE_VOLUNTEER"
    assert svc.store.get_case(MARIA).resident_status == "REQUIRES_COORDINATOR"


def test_route_through_order_zone_is_rejected(svc):
    ready(svc)
    org = svc.store.get_organization("eastside_rides_demo")
    org.volunteers[0].address.lat, org.volunteers[0].address.lon = 34.1150, -118.0950  # north of the ORDER zone
    svc.store.save_organization(org)
    rejected = propose(svc, create_proposal=False)["evaluation"]["volunteers"]["rejected"]
    assert "ROUTE_THROUGH_ORDER_ZONE" in next(v for v in rejected if v["volunteer_id"] == "volunteer_sarah")["reason_codes"]


def test_caregiver_rides_along_needs_two_seats(svc):
    ready(svc)
    p = svc.store.get_resident_profile("resident_001")
    svc.store.save_resident_profile(p.model_copy(update={"needs": p.needs + [10]}))
    org = svc.store.get_organization("eastside_rides_demo")
    org.volunteers[0].vehicle_seats = 1
    svc.store.save_organization(org)
    rejected = propose(svc, create_proposal=False)["evaluation"]["volunteers"]["rejected"]
    assert "NO_SEATS" in next(v for v in rejected if v["volunteer_id"] == "volunteer_sarah")["reason_codes"]


# ------------------------------------------------------------ proposal + reservation
def test_match_reserves_volunteer_and_is_idempotent(svc):
    ready(svc)
    view = propose(svc, idempotency_key="k1")
    m = view["match"]
    assert m["volunteer_id"] == "volunteer_sarah" and m["site_id"] == "dest_center_a" and m["status"] == "PROPOSED"
    assert "pickup_point" not in str(m)  # never before acceptance
    assert volunteer(svc, "eastside_rides_demo", "volunteer_sarah").reserved_case_id == MARIA
    assert propose(svc, idempotency_key="k1")["duplicate"] is True
    with pytest.raises(Conflict) as exc:
        propose(svc, idempotency_key="k2")
    assert exc.value.code == "MATCH_PENDING"


def test_volunteer_reserved_only_once(svc):
    alert_id = ready(svc)
    assert svc.store.reserve_volunteer("eastside_rides_demo", "volunteer_sarah", "case_a", alert_id)
    assert not svc.store.reserve_volunteer("eastside_rides_demo", "volunteer_sarah", "case_b", alert_id)
    # Maria's match skips Sarah (reserved elsewhere) and gets Lee.
    view = propose(svc)
    assert view["match"]["volunteer_id"] == "volunteer_lee"
    with pytest.raises(Conflict):
        svc.matching.propose(MARIA, idempotency_key="other", select_volunteer="volunteer_sarah")


def test_needs_confirmation_and_consent_required(svc):
    alert_and_outreach(svc)
    with pytest.raises(Conflict) as exc:
        propose(svc)
    assert exc.value.code in ("NEEDS_NOT_CONFIRMED", "NO_ASSISTANCE_REQUESTED")


# ------------------------------------------------------------ accept / decline
def test_accept_sends_help_on_the_way_and_pickup_details(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    out = accept(svc, aid)
    assert out["resident_status"] == "PROVIDER_ACCEPTED" and out["help_on_the_way_sent"]
    assert out["eta"]["label"].startswith("Illustrative") and out["pickup_details"]["resident_phone"] == MARIA_SENDER
    msg = [m for m in svc.store.list_messages(MARIA) if m.template_id == "help_on_the_way"]
    assert msg and "estimación" in msg[0].body  # Maria gets Spanish text
    assert accept(svc, aid)["duplicate"] is True


def test_wrong_org_or_volunteer_cannot_accept(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    with pytest.raises(Unauthorized):
        accept(svc, aid, org="red_cross_demo")
    with pytest.raises(Unauthorized):
        accept(svc, aid, volunteer="volunteer_lee")


def test_decline_names_next_volunteer_and_releases_reservation(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    out = accept(svc, aid, decision="DECLINED")
    assert out["assignment_status"] == "DECLINED" and out["resident_status"] == "NEEDS_ASSISTANCE"
    assert out["next_alternate"] == {"org_id": "red_cross_demo", "volunteer_id": "volunteer_lee"}
    assert volunteer(svc, "eastside_rides_demo", "volunteer_sarah").reserved_case_id is None
    with pytest.raises(InvalidTransition):  # late acceptance after declining
        accept(svc, aid)
    alt = svc.matching.propose(MARIA, idempotency_key="k2", select_volunteer="volunteer_lee")[0]["match"]
    assert alt["volunteer_id"] == "volunteer_lee"
    ev = propose(svc, create_proposal=False)["evaluation"]["volunteers"]["rejected"]
    assert "ALREADY_DECLINED" in next(v for v in ev if v["volunteer_id"] == "volunteer_sarah")["reason_codes"]


def test_all_decline_leaves_case_unresolved(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid, decision="DECLINED")
    aid2 = svc.matching.propose(MARIA, idempotency_key="k2")[0]["match"]["assignment_id"]
    out = accept(svc, aid2, org="red_cross_demo", volunteer="volunteer_lee", decision="DECLINED")
    assert out["next_alternate"] is None and out["resident_status"] == "REQUIRES_COORDINATOR"


def test_accept_rechecks_zone(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    # An evacuation ORDER is issued over Maria's sector after the match was proposed.
    svc.alerts.feed.trigger("UPDATE", zone_id="zone_3_sector_b", status="Evacuation Order")
    ingest(svc)
    with pytest.raises(SafetyRejection) as exc:
        accept(svc, aid)
    assert exc.value.code == "UNSAFE_ZONE"


def test_shelter_beds_and_shelter_checkin(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    beds = lambda: svc.store.get_organization("civic_shelter_demo").shelter_sites[0].beds_available  # noqa: E731
    before = beds()
    accept_shelter(svc, aid)
    assert beds() == before - 1
    from doorstep.models import Evidence
    svc.confirm_pickup(aid, Evidence(type="VOLUNTEER_AND_RESIDENT_CONFIRMATION", volunteer_confirmed=True,
                                     resident_confirmed=True))
    with pytest.raises(InsufficientEvidence):
        svc.confirm_arrival(aid, Evidence(type="SHELTER_CHECKIN", shelter_org_id="red_cross_demo",
                                          site_id="rc_shelter_1", shelter_confirmed=True))
    out = svc.confirm_arrival(aid, Evidence(type="SHELTER_CHECKIN", shelter_org_id="civic_shelter_demo",
                                            site_id="dest_center_a", shelter_confirmed=True))
    assert out["resident_status"] == "ARRIVAL_CONFIRMED"
    assert volunteer(svc, "eastside_rides_demo", "volunteer_sarah").reserved_case_id is None  # released


def test_pickup_rejects_wrong_volunteer_identity(svc):
    from doorstep.models import Confirmation, Evidence

    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    impostor = Evidence(type="VOLUNTEER_AND_RESIDENT_CONFIRMATION", resident_confirmed=True,
                        confirmations=[Confirmation(party="volunteer", party_id="volunteer_lee")])
    with pytest.raises(InsufficientEvidence):
        svc.confirm_pickup(aid, impostor)


def test_shelter_without_beds_is_not_matched(svc):
    ready(svc)
    for org_id in ("civic_shelter_demo", "red_cross_demo"):
        org = svc.store.get_organization(org_id)
        for site in org.shelter_sites:
            site.beds_available = 0
        svc.store.save_organization(org)
    view = propose(svc)
    assert view["no_match_reason"] == "NO_SHELTER"
    assert volunteer(svc, "eastside_rides_demo", "volunteer_sarah").reserved_case_id is None


# ------------------------------------------------------------ zone gates + escalation
def test_order_zone_blocks_and_escalation_is_receipt_only(svc, monkeypatch):
    monkeypatch.setenv("AUTO_ESCALATION_ACK", "false")
    alert_and_outreach(svc)
    confirm(svc, case_id=DAVID, sender=DAVID_SENDER)
    view = propose(svc, case_id=DAVID)
    assert view["no_match_reason"] == "ORDER_ZONE" and view["escalation_required"]
    rejected = view["evaluation"]["volunteers"]["rejected"]
    assert all(v["reason_codes"][0] == "ORDER_ZONE" for v in rejected)  # the real reason comes first
    assert all(v["reason_codes"] == ["ORDER_ZONE"] for v in rejected
               if v["volunteer_id"] in ("volunteer_sarah", "volunteer_lee"))
    with pytest.raises(SafetyRejection):
        svc.matching.propose(DAVID, idempotency_key="x", select_volunteer="volunteer_sarah")
    esc, created = svc.matching.escalate(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert created and esc["status"] == "REQUESTED" and esc["assistance_confirmed"] is False
    assert esc["case_summary_for_recipient"]["needs"] == [1]
    acked = svc.matching.acknowledge(esc["escalation_id"], "ACKNOWLEDGED_REQUEST_ONLY")
    assert acked["status"] == "ACKNOWLEDGED_REQUEST_ONLY" and acked["assistance_confirmed"] is False
    assert svc.matching.acknowledge(esc["escalation_id"], "ACKNOWLEDGED_REQUEST_ONLY")["duplicate"] is True
    with pytest.raises(InvalidTransition):
        svc.matching.acknowledge(esc["escalation_id"], "NO_ACKNOWLEDGMENT")
    assert svc.get_case_status(DAVID)["unresolved"] is True


def test_escalation_reason_must_be_true(svc):
    ready(svc)
    with pytest.raises(Conflict) as exc:
        svc.matching.escalate(MARIA, "ACTIVE_EVACUATION_ORDER_ZONE")
    assert exc.value.code == "REASON_MISMATCH"


def test_stale_feed_refuses_matching(svc):
    ready(svc)
    svc.alerts.feed.trigger("FREEZE_FEED", freeze_age_minutes=30)
    ingest(svc)
    view = propose(svc)
    assert view["no_match_reason"] == "ZONE_STALE" and view["match"] is None


# ------------------------------------------------------------ HTTP
def test_http_accept_requires_matching_org_header(client):
    svc = client.app.state.service
    ready(svc)
    aid = client.post("/matches/propose", json={"case_id": MARIA}).json()["match"]["assignment_id"]
    body = {"org_id": "eastside_rides_demo", "volunteer_id": "volunteer_sarah", "decision": "ACCEPTED"}
    assert client.post(f"/assignments/{aid}/accept", json=body).status_code == 403
    assert client.post(f"/assignments/{aid}/accept", json=body,
                       headers={"X-Org-Agent": "red_cross_demo"}).status_code == 403
    r = client.post(f"/assignments/{aid}/accept", json=body, headers={"X-Org-Agent": "eastside_rides_demo"})
    assert r.status_code == 200 and r.json()["schema_version"] == "2.0"


def test_v2_scenarios_end_to_end(client):
    from doorstep.demo.scenarios import run_scenario_a_v2, run_scenario_b_v2, run_scenario_c_v2

    quiet = lambda *a, **k: None  # noqa: E731
    assert run_scenario_a_v2(client, log=quiet)["resident_status"] == "ARRIVAL_CONFIRMED"
    assert run_scenario_b_v2(client, log=quiet)["unresolved"] is True
    client.post("/demo/reset")
    assert run_scenario_c_v2(client, log=quiet)["zone_status"] == "STALE"

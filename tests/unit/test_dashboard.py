"""B7: card data (contract v2.1 §5.11)."""

from doorstep.models import Evidence

from .test_matching_v2 import DAVID, DAVID_SENDER, MARIA, accept, accept_shelter, confirm, propose, ready


def steps(svc, case_id=MARIA):
    return {s["step"]: s for s in svc.get_case_status(case_id)["progress_steps"]}


def test_progress_steps_follow_evidence(svc):
    ready(svc)
    s = steps(svc)
    assert s["REQUESTED"]["done"] and not s["PROVIDER_ACCEPTED"]["done"] and s["REQUESTED"]["at"]
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    accept_shelter(svc, aid)
    s = steps(svc)
    assert s["PROVIDER_ACCEPTED"]["done"] and not s["PICKUP_CONFIRMED"]["done"]
    svc.confirm_pickup(aid, Evidence(type="VOLUNTEER_AND_RESIDENT_CONFIRMATION", volunteer_confirmed=True,
                                     resident_confirmed=True))
    s = steps(svc)
    assert s["PICKUP_CONFIRMED"]["done"] and s["PICKUP_CONFIRMED"]["evidence_ref"] and not s["ARRIVAL_CONFIRMED"]["done"]
    svc.confirm_arrival(aid, Evidence(type="SHELTER_CHECKIN", shelter_org_id="civic_shelter_demo",
                                      site_id="dest_center_a", shelter_confirmed=True))
    assert all(x["done"] for x in steps(svc).values())


def test_canceled_volunteer_undoes_accepted_step(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    accept(svc, aid, decision="DECLINED")  # volunteer cancels before pickup
    s = steps(svc)
    assert s["REQUESTED"]["done"] and not s["PROVIDER_ACCEPTED"]["done"]


def test_summary_counts_unresolved_and_health(client):
    svc = client.app.state.service
    ready(svc)
    confirm(svc, case_id=DAVID, sender=DAVID_SENDER)
    propose(svc, case_id=DAVID)
    svc.matching.escalate(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE")
    r = client.get("/dashboard/summary")
    body = r.json()
    assert r.status_code == 200 and body["schema_version"] == "2.0" and body["simulated"]
    counts = {c["status"]: c for c in body["counts_by_status"]}
    assert counts["NEEDS_ASSISTANCE"]["count"] == 1 and counts["REQUIRES_COORDINATOR"]["count"] == 1
    assert counts["ARRIVAL_CONFIRMED"]["color"] == "green" and counts["REQUIRES_COORDINATOR"]["label"]
    assert [u["case_id"] for u in body["unresolved"]] == [DAVID]
    assert body["unresolved"][0]["reason"] == "ACTIVE_EVACUATION_ORDER_ZONE"
    assert body["alerts"]["active_order"] == 1 and body["alerts"]["active_warning"] == 1
    assert body["alerts"]["feed_freshness"] == "FRESH"
    assert body["outreach"]["orgs_contacted"] == 3 and body["outreach"]["volunteers_available"] == 3
    health = client.get("/health").json()
    assert health["version"] == "2.1.0" and health["alerts"]["feed_freshness"] == "FRESH"


def test_dashboard_cases_are_coarse_and_never_green_early(client):
    svc = client.app.state.service
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    r = client.get("/dashboard/cases").json()
    maria = next(c for c in r["cases"] if c["case_id"] == MARIA)
    assert maria["coarse_location"] == {"lat": 34.1, "lon": -118.1}
    assert maria["map"]["color"] == "yellow" and not maria["progress_steps"][3]["done"]
    assert "pickup_point" not in str(r) and "meeting point" not in str(r) and "sim_phone" not in str(r)

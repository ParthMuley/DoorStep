"""B6: road closures (deterministic states) and route constraints + HERE post-check."""

from datetime import datetime, timedelta, timezone

import pytest

from doorstep.demo.scenarios import ROUTE_AVOIDING_RIDGE, ROUTE_THROUGH_RIDGE
from doorstep.services.errors import Conflict

from .test_matching_v2 import accept, accept_shelter, edit_volunteer, ingest, propose, ready


def item(item_id, road, status="CLOSED", **kw):
    return {"source_item_id": item_id, "candidate": {"road_name": road, "claimed_status": status}, **kw}


def ingest_closures(svc, source_type, items, source_id=None, key=None):
    return svc.closures.ingest(source_id=source_id or f"SRC_{source_type}", source_type=source_type, url=None,
                               fetched_at=None, items=items, idempotency_key=key)


def state(svc, road):
    return next(c for c in svc.closures.list_view()["closures"] if c["road_name"] == road)


# ------------------------------------------------------------------ closure states
def test_official_closure_blocks_and_aliases_map(svc):
    out = ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o1", "Ridge Avenue")])
    assert out["accepted"][0]["segment_id"] == "seg_ridge_ave" and out["new_official_closures"]
    c = state(svc, "Ridge Ave")
    assert c["state"] == "OFFICIAL_CONFIRMED" and c["used_for_routing"] is True


def test_news_is_never_official(svc):
    ingest_closures(svc, "NEWS", [item("n1", "Ridge Ave", extraction_method="ASI_ONE_EXTRACTION",
                                       headline="Officials say Ridge Ave closed")])
    c = state(svc, "Ridge Ave")
    assert c["state"] == "UNVERIFIED_REPORT" and c["used_for_routing"] is False


def test_conflicting_reports(svc):
    ingest_closures(svc, "NEWS", [item("n1", "Canyon Rd", "CLOSED"), item("n2", "Canyon Rd", "OPEN")])
    assert state(svc, "Canyon Rd")["state"] == "CONFLICTING"


def test_official_lift_vs_news(svc):
    ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o1", "Ridge Ave", "OPEN")])
    assert state(svc, "Ridge Ave")["state"] == "EXPIRED"  # officially lifted, no other claims
    ingest_closures(svc, "NEWS", [item("n1", "Ridge Ave", "CLOSED")])
    assert state(svc, "Ridge Ave")["state"] == "CONFLICTING"


def test_official_closed_wins_over_news_open(svc):
    ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o1", "Ridge Ave", "CLOSED")])
    ingest_closures(svc, "NEWS", [item("n1", "Ridge Ave", "OPEN")])
    c = state(svc, "Ridge Ave")
    assert c["state"] == "OFFICIAL_CONFIRMED" and c["conflicting_reports"] == 1 and c["used_for_routing"]


def test_expired_claims(svc):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o1", "Ridge Ave", expires_at=past)])
    c = state(svc, "Ridge Ave")
    assert c["state"] == "EXPIRED" and c["used_for_routing"] is False


def test_unmapped_and_real_world_never_route(svc):
    ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o1", "Nowhere Lane")])
    c = state(svc, "Nowhere Lane")
    assert c["segment_id"] is None and c["used_for_routing"] is False and c["state"] == "OFFICIAL_CONFIRMED"
    ingest_closures(svc, "REAL_WORLD_CONTEXT", [item("r1", "Ridge Ave")])
    real = next(c for c in svc.closures.list_view()["closures"] if c["display_only"])
    assert real["used_for_routing"] is False and real["segment_id"] is None
    assert svc.closures.blocking() == [] and svc.closures.cautions() == []


def test_rejections_idempotency_and_no_report_note(svc):
    assert svc.closures.list_view()["closures"] == []
    assert "does not mean a road is open" in svc.closures.list_view()["note"]
    out = ingest_closures(svc, "NEWS", [item("x", "", "CLOSED"), item("y", "Ridge Ave", "MAYBE")], key="k")
    assert sorted(r["reason"] for r in out["rejected"]) == ["MISSING_ROAD", "UNKNOWN_STATUS:MAYBE"]
    assert ingest_closures(svc, "NEWS", [], key="k")["duplicate"] is True


def test_agent_cannot_send_a_state(client):
    r = client.post("/closures/ingest", json={"source": {"source_id": "S", "source_type": "NEWS"},
                                              "items": [{"source_item_id": "1", "state": "OFFICIAL_CONFIRMED",
                                                         "candidate": {"road_name": "Ridge Ave"}}]})
    assert r.status_code == 422


def test_demo_feeds_and_trigger(client):
    assert client.get("/demo/feeds/closures").json()["closures"][0]["road_name"] == "Ridge Ave"
    assert client.get("/demo/feeds/news").json()["items"][0]["item_id"] == "news_001"
    client.post("/demo/closures/trigger", json={"action": "LIFT_OFFICIAL", "road_name": "Ridge Ave"})
    assert client.get("/demo/feeds/closures").json()["closures"][0]["status"] == "OPEN"
    client.post("/demo/closures/trigger", json={"action": "PUBLISH_NEWS", "road_name": "Civic Way"})
    assert len(client.get("/demo/feeds/news").json()["items"]) == 2


# ------------------------------------------------------------------ routes
def accepted(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    accept_shelter(svc, aid)
    return aid


def closures_demo(svc):
    ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o1", "Ridge Ave")])
    ingest_closures(svc, "NEWS", [item("n1", "Canyon Rd")])


def test_constraints_list_avoid_areas_and_cautions(svc):
    aid = accepted(svc)
    closures_demo(svc)
    c = svc.routes.constraints(aid, idempotency_key="r1")
    assert [s["role"] for s in c["stops"]] == ["VOLUNTEER_START", "PICKUP", "SHELTER"]
    assert sorted(a["kind"] for a in c["avoid_areas"]) == ["OFFICIAL_CLOSURE", "ORDER_ZONE"]
    assert [x["road_name"] for x in c["cautions"]] == ["Canyon Rd"]
    assert "NOT FOR LIVE EVACUATION" in c["label"] and "safe" not in c["label"].lower()
    assert svc.routes.constraints(aid, idempotency_key="r1")["duplicate"] is True


def test_constraints_refused_before_acceptance(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    with pytest.raises(Conflict) as exc:
        svc.routes.constraints(aid)
    assert exc.value.code == "ROUTE_REFUSED" and "ASSIGNMENT_NOT_ACCEPTED" in exc.value.reasons


def test_constraints_refused_on_stale_data(svc):
    aid = accepted(svc)
    svc.alerts.feed.trigger("FREEZE_FEED", freeze_age_minutes=30)
    ingest(svc)
    with pytest.raises(Conflict) as exc:
        svc.routes.constraints(aid)
    assert "ZONE_STALE" in exc.value.reasons


def test_constraints_refused_when_a_stop_is_in_an_order_zone(svc):
    from doorstep.models import point
    aid = accepted(svc)
    edit_volunteer(svc, "volunteer_sarah", location=point(34.1070, -118.0950))  # inside the ORDER zone
    with pytest.raises(Conflict) as exc:
        svc.routes.constraints(aid)
    assert "ORDER_ZONE" in exc.value.reasons


def test_too_many_avoid_areas_refused_not_truncated(svc, monkeypatch):
    aid = accepted(svc)
    closures_demo(svc)
    monkeypatch.setenv("ROUTE_MAX_AVOID_AREAS", "1")
    with pytest.raises(Conflict) as exc:
        svc.routes.constraints(aid)
    assert "TOO_MANY_AVOID_AREAS" in exc.value.reasons


def preview(svc, req_id, line, **kw):
    return svc.routes.preview(req_id, provider="HERE", polyline=line, distance_m=4600, duration_s=660,
                              provider_notices=kw.pop("notices", []), **kw)


def test_post_check(svc):
    aid = accepted(svc)
    closures_demo(svc)
    req = svc.routes.constraints(aid, idempotency_key="r1")["route_request_id"]
    bad = preview(svc, req, ROUTE_THROUGH_RIDGE, idempotency_key="p1")
    assert bad["status"] == "REFUSED" and bad["crosses"] and bad["eta"] is None
    through_order = {"type": "LineString", "coordinates": [[-118.110, 34.095], [-118.095, 34.108], [-118.070, 34.089]]}
    assert preview(svc, req, through_order, idempotency_key="p2")["status"] == "REFUSED"
    assert preview(svc, req, None, idempotency_key="p3")["status"] == "NO_ROUTE_CONFIRMED"
    assert preview(svc, req, ROUTE_AVOIDING_RIDGE, idempotency_key="p4",
                   notices=[{"code": "violatedAvoidArea"}])["status"] == "REFUSED"
    good = preview(svc, req, ROUTE_AVOIDING_RIDGE, idempotency_key="p5")
    assert good["status"] == "ILLUSTRATIVE_ONLY" and good["cautions_on_path"] and good["eta"]["minutes"] == 11
    assert svc.store.get_assignment(aid).eta_minutes == 11  # case ETA follows the route (still an estimate)
    assert svc.get_case_status("case_maria_001")["route"]["status"] == "ILLUSTRATIVE_ONLY"


def test_closure_published_after_constraints_is_still_caught(svc):
    aid = accepted(svc)
    req = svc.routes.constraints(aid, idempotency_key="r1")["route_request_id"]
    ingest_closures(svc, "OFFICIAL_SIMULATION", [item("o9", "Valley Blvd")])  # on Sarah's way to Maria
    line = {"type": "LineString", "coordinates": [[-118.110, 34.095], [-118.0964, 34.1012], [-118.093, 34.089],
                                                  [-118.070, 34.089]]}
    out = preview(svc, req, line)
    assert out["status"] == "REFUSED" and out["crosses"]


def test_preview_on_refused_request_is_rejected(svc):
    ready(svc)
    aid = propose(svc)["match"]["assignment_id"]
    with pytest.raises(Conflict):
        svc.routes.constraints(aid)
    req_id = svc.db.coll("route_requests").find_one({})["route_request_id"]
    with pytest.raises(Conflict):
        preview(svc, req_id, ROUTE_AVOIDING_RIDGE)


def test_news_agent_payload_shape_is_accepted_over_http(client):
    """Exactly what A's News agent sends: keyword fallback label and UNCLEAR status."""
    news = client.get("/demo/feeds/news").json()["items"][0]
    body = {"schema_version": "2.0", "idempotency_key": "news:k1",
            "source": {"source_id": "SYNTHETIC_NEWS", "source_type": "NEWS", "url": "/demo/feeds/news"},
            "items": [{"source_item_id": news["item_id"], "headline": news["headline"], "raw_text": news["body"],
                       "extraction_method": "KEYWORD_EXTRACTION",
                       "candidate": {"road_name": "Canyon Rd", "claimed_status": "CLOSED", "location_text": ""}},
                      {"source_item_id": "news_x", "extraction_method": "ASI_ONE_EXTRACTION",
                       "candidate": {"road_name": "Valley Blvd", "claimed_status": "UNCLEAR", "location_text": ""}}]}
    r = client.post("/closures/ingest", json=body)
    assert r.status_code == 200, r.text
    acc = {a["road_name"]: a for a in r.json()["accepted"]}
    assert acc["Canyon Rd"]["state"] == "UNVERIFIED_REPORT" and acc["Canyon Rd"]["claimed_status"] == "CLOSED"
    assert acc["Valley Blvd"]["claimed_status"] == "UNKNOWN" and acc["Valley Blvd"]["state"] != "OFFICIAL_CONFIRMED"
    assert r.json()["rejected"] == []
    listed = {c["road_name"]: c for c in client.get("/closures").json()["closures"]}
    assert listed["Canyon Rd"]["state"] == "UNVERIFIED_REPORT"  # a news report never blocks a route

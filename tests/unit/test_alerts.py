"""B3: synthetic Cal OES feed, /alerts/ingest, polygon geofencing, staleness,
check-ins, outreach-org selection and volunteer outreach (V2 plan §6 tests)."""

import copy

import pytest

from doorstep.models import ResidentProfile
from doorstep.services.alert_feed import ZONE_3_SECTOR_A
from doorstep.services.alerts import normalize_event_type, normalize_status
from doorstep.services.errors import Conflict, FeedInvalid

from .conftest import MARIA, warn  # noqa: F401

SIM = "SYNTHETIC_CALOES"


def ingest(svc, payload=None, key=None, source_id=SIM, source_type="OFFICIAL_SIMULATION", **kw):
    payload = svc.alerts.feed.render_caloes() if payload is None else payload
    return svc.alerts.ingest(source_id=source_id, source_type=source_type, url="test", fetched_at=None,
                             fetch_ok=kw.pop("fetch_ok", True), http_status=200, error=None, payload=payload,
                             idempotency_key=key, **kw)


def issue(svc, preset="ZONE_3_WILDFIRE"):
    svc.alerts.feed.trigger("ISSUE", preset=preset)
    return ingest(svc)


def feature(zone_id, status, geometry, gid=None, event="Wildfire", edit=1792281600000, statewide=None):
    return {"type": "Feature", "geometry": geometry,
            "properties": {"OBJECTID": 1, "ZONE_ID": zone_id, "ZONE_NAME": zone_id, "STATUS": status,
                           "EVENT_TYPE": event, "EDIT_DATE": edit, "STATEWIDE_LAST_UPDATED": statewide or edit,
                           "GlobalID": gid or f"g-{zone_id}"}}


def profile(lat, lon, confidence="HIGH", rid="resident_x"):
    return ResidentProfile(resident_id=rid, name="X (synthetic)", phone=f"sim_phone_{rid}",
                           address={"label": "SYNTHETIC", "lat": lat, "lon": lon, "geocode_confidence": confidence},
                           needs=[1], consents={"CHECKIN": True, "TRANSPORT": True})


# ------------------------------------------------------------ normalization
@pytest.mark.parametrize("raw,expected", [("Evacuation Order", "ORDER"), ("EVACUATION ORDER", "ORDER"),
                                          ("evacuation   warning", "WARNING"), ("Shelter-in-Place", "SHELTER_IN_PLACE"),
                                          ("NORMAL", "INACTIVE"), ("Clear to Repopulate", "INACTIVE")])
def test_status_normalized_case_insensitively(raw, expected):
    assert normalize_status(raw).value == expected


def test_unknown_status_is_never_guessed():
    assert normalize_status("Evacuation Advisory") is None and normalize_status(None) is None
    assert normalize_event_type(None) == "UNKNOWN" and normalize_event_type("Wildfire (SIMULATED)") == "WILDFIRE"


# ------------------------------------------------------------ geofencing
def test_inside_outside_and_edge(svc):
    issue(svc)
    a = svc.alerts
    assert a.zone_status_label(svc.store.get_resident_profile("resident_001")) == "WARNING"
    assert a.zone_status_label(svc.store.get_resident_profile("resident_002")) == "ORDER"
    assert a.zone_status_label(profile(34.20, -118.30)) == "OUTSIDE_KNOWN_ZONES"
    # Exactly on the shared edge of the WARNING and ORDER polygons: covered by both, ORDER dominates.
    edge = a.zone_for(profile(34.104, -118.095))
    assert edge["zone_status"] == "ORDER" and len(edge["zone_sources"]) == 2


def test_uncertain_geocode_is_unknown(svc):
    issue(svc)
    assert svc.alerts.zone_status_label(profile(34.1012, -118.0964, confidence="LOW")) == "UNKNOWN"


def test_no_feed_data_means_unknown_not_safe(svc):
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_001")) == "UNKNOWN"


def test_registration_after_feed_uses_polygons(client):
    client.post("/demo/alerts/trigger", json={"action": "ISSUE", "preset": "ZONE_3_WILDFIRE", "poll_now": True})
    base = {"name": "Rosa (synthetic)", "phone": "sim_phone_rosa", "needs": [1],
            "consents": {"CHECKIN": True}}
    inside = client.post("/residents", json={"resident": {**base, "address": {
        "label": "SYNTHETIC", "lat": 34.100, "lon": -118.095}}}).json()
    outside = client.post("/residents", json={"resident": {**base, "phone": "sim_phone_rosa2", "address": {
        "label": "SYNTHETIC", "lat": 34.200, "lon": -118.300}}}).json()
    assert inside["zone_status"] == "WARNING" and outside["zone_status"] == "OUTSIDE_KNOWN_ZONES"


# ------------------------------------------------------------ ingest rules
def test_ten_identical_ingests_send_one_checkin(svc):
    svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_WILDFIRE")
    payload = svc.alerts.feed.render_caloes()
    results = [ingest(svc, copy.deepcopy(payload)) for _ in range(10)]
    assert len(results[0]["new_alerts"]) == 2 and len(results[0]["checkins_sent"]) == 2
    assert all(r["new_alerts"] == [] and r["checkins_sent"] == [] for r in results[1:])
    assert svc.db.coll("checkins").count_documents({}) == 2
    assert svc.db.coll("zone_alerts").count_documents({}) == 2
    outbound = [m for m in svc.store.list_messages(MARIA) if m.direction == "outbound"]
    assert len(outbound) == 1 and outbound[0].body.startswith("DOORSTEP DEMO")


def test_payload_idempotency_key(svc):
    svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_WARNING")
    first = ingest(svc, key="poll-1")
    again = ingest(svc, key="poll-1")
    assert again["duplicate"] is True and again["ingest_id"] == first["ingest_id"]


def test_rebuild_gap_needs_two_misses_to_cancel(svc):
    issue(svc)
    svc.alerts.feed.trigger("EXPIRE", zone_id="zone_3_sector_a")  # David's ORDER record disappears
    first = ingest(svc)
    assert first["canceled_alerts"] == [] and len(first["pending_cancellation"]) == 1
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_002")) == "ORDER"
    second = ingest(svc)
    assert len(second["canceled_alerts"]) == 1
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_002")) == "OUTSIDE_KNOWN_ZONES"


def test_record_reappearing_resets_the_miss_counter(svc):
    issue(svc)
    svc.alerts.feed.trigger("EXPIRE", zone_id="zone_3_sector_a")
    assert len(ingest(svc)["pending_cancellation"]) == 1
    svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_ORDER")
    assert ingest(svc)["pending_cancellation"] == []
    svc.alerts.feed.trigger("EXPIRE", zone_id="zone_3_sector_a")
    assert ingest(svc)["canceled_alerts"] == []  # counter restarted


def test_explicit_normal_cancels_immediately(svc):
    issue(svc)
    svc.alerts.feed.trigger("CANCEL", zone_id="zone_3_sector_b")
    result = ingest(svc)
    assert len(result["canceled_alerts"]) == 1
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_001")) == "OUTSIDE_KNOWN_ZONES"


def test_failed_fetch_never_cancels(svc):
    issue(svc)
    for _ in range(3):
        r = ingest(svc, payload=None, fetch_ok=False)
        assert r["canceled_alerts"] == [] and r["fetch_ok"] is False
    assert len(svc.alerts.active_view()["alerts"]) == 2


def test_malformed_and_partial_payloads(svc):
    with pytest.raises(FeedInvalid):
        ingest(svc, payload={"features": "nope"})
    bad = {"type": "FeatureCollection", "features": [
        feature("z_unknown", "Evacuation Advisory", ZONE_3_SECTOR_A, gid="a"),
        feature("z_geom", "Evacuation Order", {"type": "Point", "coordinates": [-118.09, 34.1]}, gid="b"),
        {"type": "Feature", "geometry": ZONE_3_SECTOR_A, "properties": {"STATUS": "Evacuation Order", "GlobalID": "c"}}]}
    r = ingest(svc, payload=bad)
    assert sorted(x["reason"] for x in r["records_rejected"]) == [
        "INVALID_GEOMETRY", "MISSING_ZONE_ID", "UNKNOWN_STATUS:Evacuation Advisory"]
    assert r["new_alerts"] == [] and r["checkins_sent"] == []


def test_empty_feed_is_valid(svc):
    r = ingest(svc, payload={"type": "FeatureCollection", "features": []})
    assert r["new_alerts"] == [] and r["feed_freshness"] == "FRESH"
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_001")) == "OUTSIDE_KNOWN_ZONES"


# ------------------------------------------------------------ staleness
def test_frozen_feed_becomes_stale_and_triggers_nothing(svc):
    issue(svc, preset="ZONE_3_WARNING")
    svc.alerts.feed.trigger("FREEZE_FEED", freeze_age_minutes=30)
    svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_ORDER")  # a new zone appears while data is stale
    r = ingest(svc)
    assert r["feed_freshness"] == "STALE" and r["checkins_sent"] == [] and r["outreach_orgs"] == []
    for rid in ("resident_001", "resident_002"):
        assert svc.alerts.zone_status_label(svc.store.get_resident_profile(rid)) == "STALE"
    svc.alerts.feed.trigger("UNFREEZE_FEED")
    assert ingest(svc)["feed_freshness"] == "FRESH"


# ------------------------------------------------------------ live data
def test_real_world_feed_is_display_only(svc):
    live = {"type": "FeatureCollection", "features": [feature("real_zone", "Evacuation Order", ZONE_3_SECTOR_A,
                                                              event=None)]}
    r = ingest(svc, payload=live, source_id="CALOES_LIVE", source_type="REAL_WORLD")
    assert len(r["new_alerts"]) == 1 and r["checkins_sent"] == [] and r["affected_cases"] == []
    assert r["outreach_orgs"] == []
    alert = svc.alerts.active_view()["alerts"][0]
    assert alert["verification"] == "OFFICIAL_LIVE_DISPLAY_ONLY" and alert["can_trigger_checkins"] is False
    # David sits inside that polygon, but live data never changes a resident's zone.
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_002")) == "UNKNOWN"
    with pytest.raises(Conflict):
        svc.alerts.start_outreach("eastside_rides_demo", alert["alert_id"])


# ------------------------------------------------------------ awareness radius
def test_awareness_radius_never_triggers_the_evacuation_flow(svc):
    issue(svc)
    svc.registry.register_resident(profile(34.1150, -118.0800, rid="resident_near"))  # near the fire, no zone
    view = svc.alerts.active_view()
    assert view["awareness"][0]["residents_nearby_not_in_zone"] == 1
    assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_near")) == "OUTSIDE_KNOWN_ZONES"
    assert svc.store.find_case("case_resident_near") is None  # no check-in from a radius


# ------------------------------------------------------------ outreach orgs
def test_outreach_orgs_closest_matching_approved(svc):
    r = issue(svc)
    assert [o["org_id"] for o in r["outreach_orgs"]] == ["neighbor_sedans_demo", "eastside_rides_demo", "red_cross_demo"]


def test_flood_alert_contacts_flood_orgs(svc):
    svc.alerts.feed.trigger("ISSUE", zone_id="zone_3_sector_b", status="Evacuation Warning", event_type="Flood",
                            geometry={"type": "Polygon", "coordinates": [[[-118.100, 34.098], [-118.090, 34.098],
                                                                          [-118.090, 34.104], [-118.100, 34.104],
                                                                          [-118.100, 34.098]]]})
    ids = [o["org_id"] for o in ingest(svc)["outreach_orgs"]]
    assert "flood_only_demo" in ids and "eastside_rides_demo" not in ids and "unlisted_vans_demo" not in ids


def test_unknown_calamity_type_contacts_any_approved_transport_org(svc):
    payload = {"type": "FeatureCollection", "features": [feature("zone_3_sector_b", "Evacuation Warning",
               {"type": "Polygon", "coordinates": [[[-118.100, 34.098], [-118.090, 34.098], [-118.090, 34.104],
                                                    [-118.100, 34.104], [-118.100, 34.098]]]}, event=None)]}
    import time
    now = int(time.time() * 1000)
    payload["features"][0]["properties"].update({"EDIT_DATE": now, "STATEWIDE_LAST_UPDATED": now})
    ids = [o["org_id"] for o in ingest(svc, payload=payload)["outreach_orgs"]]
    assert "unlisted_vans_demo" not in ids and len(ids) == 3


# ------------------------------------------------------------ volunteer outreach
def outreach_alert(svc):
    return issue(svc)["new_alerts"][0]["alert_id"]


def test_volunteer_outreach_and_replies(client):
    svc = client.app.state.service
    alert_id = outreach_alert(svc)
    h = {"X-Org-Agent": "red_cross_demo"}
    r = client.post("/orgs/red_cross_demo/outreach", json={"alert_id": alert_id}, headers=h)
    assert r.status_code == 200 and [a["volunteer_id"] for a in r.json()["asked"]] == ["volunteer_maya", "volunteer_lee"]
    assert client.post("/orgs/red_cross_demo/outreach", json={"alert_id": alert_id}, headers=h).json()["duplicate"]
    sms = [m for m in svc.store.list_messages() if m.recipient == "sim_phone_lee"]
    assert sms and sms[0].body.startswith("DOORSTEP DEMO")
    # Lee answers YES by SMS; Maya never answers.
    yes = client.post("/sim/inbound", json={"sender": "sim_phone_lee", "text": "YES", "external_id": "lee-1"})
    assert yes.status_code == 200 and yes.json()["availability"] == "AVAILABLE"
    client.post("/sim/outreach/" + alert_id + "/deadline")
    vols = {v["volunteer_id"]: v["availability"]["state"] for v in client.get(
        "/orgs/red_cross_demo/volunteers", params={"alert_id": alert_id}, headers=h).json()["volunteers"]}
    assert vols == {"volunteer_maya": "NO_REPLY", "volunteer_lee": "AVAILABLE"}
    summary = client.get(f"/alerts/{alert_id}/outreach").json()["orgs"][0]
    assert (summary["asked"], summary["available"], summary["no_reply"]) == (2, 1, 1)


def test_volunteer_says_no(client):
    svc = client.app.state.service
    alert_id = outreach_alert(svc)
    client.post("/orgs/eastside_rides_demo/outreach", json={"alert_id": alert_id},
                headers={"X-Org-Agent": "eastside_rides_demo"})
    r = client.post("/sim/inbound", json={"sender": "sim_phone_sarah", "text": "no"})
    assert r.json()["availability"] == "UNAVAILABLE"


def test_new_alert_outreach_makes_old_answers_stale(svc):
    first = outreach_alert(svc)
    svc.alerts.start_outreach("eastside_rides_demo", first)
    svc.registry.record_availability("eastside_rides_demo", "volunteer_sarah", alert_id=first, available=True)
    # A new calamity alert: outreach asks again; Sarah's old YES no longer counts.
    svc.alerts.feed.trigger("ISSUE", zone_id="zone_9", status="Evacuation Warning", event_type="Wildfire",
                            geometry={"type": "Polygon", "coordinates": [[[-118.12, 34.08], [-118.11, 34.08],
                                                                          [-118.11, 34.09], [-118.12, 34.09],
                                                                          [-118.12, 34.08]]]})
    second = next(a["alert_id"] for a in ingest(svc)["new_alerts"] if a["zone_id"] == "zone_9")
    svc.alerts.start_outreach("eastside_rides_demo", second)
    view = svc.registry.org_volunteers("eastside_rides_demo", second)["volunteers"][0]["availability"]
    assert view["state"] == "ASKED"
    with pytest.raises(Conflict) as exc:
        svc.registry.record_availability("eastside_rides_demo", "volunteer_sarah", alert_id=first, available=True)
    assert exc.value.code == "STALE_AVAILABILITY"


def test_outreach_refused_for_unapproved_org_and_wrong_agent(client):
    svc = client.app.state.service
    alert_id = outreach_alert(svc)
    r = client.post("/orgs/unlisted_vans_demo/outreach", json={"alert_id": alert_id},
                    headers={"X-Org-Agent": "unlisted_vans_demo"})
    assert r.status_code == 409 and r.json()["error"] == "ORG_NOT_APPROVED"
    r = client.post("/orgs/eastside_rides_demo/outreach", json={"alert_id": alert_id},
                    headers={"X-Org-Agent": "red_cross_demo"})
    assert r.status_code == 403


def test_unknown_sms_sender_still_rejected(client):
    assert client.post("/sim/inbound", json={"sender": "sim_phone_stranger", "text": "YES"}).status_code == 403


# ------------------------------------------------------------ v1 flow still works on ingest-created cases
def test_case_from_ingest_flows_into_existing_matching(svc):
    from .conftest import MARIA_SENDER, t_offers

    issue(svc)
    svc.submit_resident_response(MARIA, "1 necesito ayuda", "es", sender=MARIA_SENDER, external_id="r1")
    svc.submit_resident_response(MARIA, "SI", "es", sender=MARIA_SENDER, external_id="r2")
    result = svc.evaluate_transport(MARIA, t_offers(), "req_001")
    assert result["eligible"][0]["provider_id"] == "transport_org_a"
    view = svc.get_case_status(MARIA)
    assert view["zone_status"] == "WARNING" and view["alert_id"] == "alert_001"

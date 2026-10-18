"""B2: registration (two databases), needs codes, org-scoped volunteer access."""

import pytest

from doorstep.models import ResidentProfile, validate_codes
from doorstep.services.legacy import to_legacy_resident

ORG = "eastside_rides_demo"


def org_headers(org_id):
    return {"X-Org-Agent": org_id}


def rosa(**overrides):
    body = {"name": "Rosa (synthetic)", "phone": "sim_phone_rosa", "language": "es",
            "address": {"label": "SYNTHETIC: 12 Example Way", "lat": 34.1052, "lon": -118.0951,
                        "geocode_confidence": "HIGH"},
            "emergency_contacts": [{"name": "Luis (synthetic)", "phone": "sim_phone_luis", "relationship": "son"}],
            "needs": [1, 6], "pet_count": 0, "wants_help_contact": True,
            "consents": {"CHECKIN": True, "TRANSPORT": True, "DESTINATION": True, "RECOVERY": False}}
    body.update(overrides)
    return body


def new_org(org_id="foothill_vans_demo", **overrides):
    body = {"org_id": org_id, "name": "Foothill Access Vans (fictional)",
            "location": {"label": "SYNTHETIC: Zone 2", "lat": 34.09, "lon": -118.11},
            "calamity_types": ["WILDFIRE"], "services": ["TRANSPORT"], "approved": True, "service_radius_km": 20,
            "volunteers": [{"volunteer_id": "volunteer_kim", "name": "Kim (synthetic)", "phone": "sim_phone_kim",
                            "address": {"label": "SYNTHETIC: Zone 2", "lat": 34.09, "lon": -118.11},
                            "vehicle_type": "WHEELCHAIR_VAN", "vehicle_seats": 2, "wheelchair_spaces": 1,
                            "pet_capacity": 1, "needs_they_can_cater": [1, 2, 4], "approved": True}]}
    body.update(overrides)
    return body


# ---------------------------------------------------------------- needs codes
def test_needs_codes_validated_and_normalized():
    assert validate_codes([4, 1, 1, 2]) == [1, 2, 4]
    with pytest.raises(ValueError):
        validate_codes([1, 99])


# ---------------------------------------------------------------- seed / DBs
def test_seed_matches_contract(svc):
    maria = svc.store.get_resident_profile("resident_001")
    assert maria.needs == [1, 2, 4, 6] and maria.pet_count == 1 and maria.language == "es"
    p = svc.store.partners
    assert {o.org_id for o in p.list_orgs()} == {"eastside_rides_demo", "neighbor_sedans_demo", "red_cross_demo",
                                                 "unlisted_vans_demo", "flood_only_demo", "civic_shelter_demo",
                                                 "recovery_housing_demo"}
    assert [r.region_id for r in p.list_regions()] == ["la_county:east_valley", "la_county:south_valley",
                                                       "la_county:westside", "sf:mission"]
    # Red Cross is present in four places, each with only its local people/sites.
    assert [r.region_id for r in p.regions_of_org("red_cross_demo")] == [
        "la_county:east_valley", "la_county:south_valley", "la_county:westside", "sf:mission"]
    region, entry, sarah = p.locate_volunteer("volunteer_sarah")
    assert region.region_id == "la_county:east_valley" and entry.org_id == "eastside_rides_demo"
    assert sarah.needs_they_can_cater == [1, 2, 4, 7]
    assert p.locate_volunteer("volunteer_sam")[0].region_id == "sf:mission"
    assert svc.db.partners["regions"].count_documents({}) == 4
    assert svc.db.users["residents"].count_documents({}) == 2


def test_legacy_view_keeps_v1_engine_semantics(svc):
    legacy = svc.store.get_resident("resident_001")
    n = legacy.needs
    assert n.wheelchair_accessible_vehicle and n.transfer_assistance and n.pet_count == 1
    assert n.destination_accessibility == ["step_free_entry"] and not n.portable_oxygen_equipment
    assert legacy.sector_id == "zone_3_sector_b" and legacy.contact_channel == "sim_phone_maria"
    # A resident registered via the API has no legacy sector: the v1 zone rule fails closed.
    p = ResidentProfile(**rosa(), resident_id="resident_x")
    assert to_legacy_resident(p).sector_id is None


# ---------------------------------------------------------------- residents
def test_register_resident(client):
    r = client.post("/residents", json={"resident": rosa()})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["schema_version"] == "2.0"
    assert body["resident_id"] not in ("resident_001", "resident_002")
    # No feed ingested yet: no data means UNKNOWN, never "outside"/safe (see test_alerts for after-ingest).
    assert body["zone_status"] == "UNKNOWN" and body["needs"] == [1, 6]
    stored = client.app.state.service.store.get_resident_profile(body["resident_id"])
    assert stored.emergency_contacts[0].contact_id == f"{body['resident_id']}_contact_1"


def test_resident_opting_out_is_never_contacted(client):
    r = client.post("/residents", json={"resident": rosa(wants_help_contact=False)})
    assert r.json()["consents"]["CHECKIN"] is False


def test_uncertain_geocode_gives_unknown_zone(client):
    r = client.post("/residents", json={"resident": rosa(address={"label": "SYNTHETIC: ?", "lat": 34.1, "lon": -118.1,
                                                                  "geocode_confidence": "LOW"})})
    assert r.json()["zone_status"] == "UNKNOWN"


def test_pets_imply_pet_need_code(client):
    r = client.post("/residents", json={"resident": rosa(needs=[1], pet_count=2)})
    assert r.json()["needs"] == [1, 4]


@pytest.mark.parametrize("bad", [{"needs": [1, 99]}, {"consents": {"CHECKIN": True, "MARKETING": True}},
                                 {"address": {"label": "x", "lat": 200, "lon": 0}}])
def test_invalid_resident_rejected(client, bad):
    assert client.post("/residents", json={"resident": rosa(**bad)}).status_code == 422


def test_duplicate_resident_id_conflicts(client):
    r = client.post("/residents", json={"resident": rosa(resident_id="resident_001")})
    assert r.status_code == 409 and r.json()["error"] == "ALREADY_REGISTERED"


# ------------------------------------------------------------ organizations + regions (v2.1)
EAST = "la_county:east_valley"


def canonical(org_id="foothill_vans_demo", **overrides):
    body = {"org_id": org_id, "name": "Foothill Access Vans (fictional)", "calamity_types": ["WILDFIRE"],
            "services": ["TRANSPORT"], "approved": True, "service_radius_km": 20}
    body.update(overrides)
    return body


def kim(**overrides):
    body = {"volunteer_id": "volunteer_kim", "name": "Kim (synthetic)", "phone": "sim_phone_kim",
            "location": {"type": "Point", "coordinates": [-118.100, 34.100]}, "vehicle_type": "WHEELCHAIR_VAN",
            "vehicle_seats": 2, "wheelchair_spaces": 1, "pet_capacity": 1, "needs_they_can_cater": [1, 2, 4],
            "approved": True}
    body.update(overrides)
    return body


def test_canonical_org_create_and_update_propagates_to_regions(client):
    r = client.post("/organizations", json={"organization": canonical()})
    assert r.status_code == 201 and r.json()["region_ids"] == []
    # Revoking Red Cross approval updates its copy in every region in the same request.
    upd = client.post("/organizations", json={"organization": canonical(
        "red_cross_demo", name="Red Cross (fictional demo chapter)", approved=False, service_radius_km=40,
        calamity_types=["WILDFIRE", "FLOOD", "EARTHQUAKE"], services=["TRANSPORT", "SHELTER"])})
    assert upd.status_code == 200 and len(upd.json()["region_ids"]) == 4
    p = client.app.state.service.store.partners
    assert all(not e.approved for r in p.regions_of_org("red_cross_demo") for e in r.orgs if e.org_id == "red_cross_demo")


def test_volunteer_registered_where_they_are(client):
    client.post("/organizations", json={"organization": canonical()})
    ok = client.post(f"/regions/{EAST}/orgs/foothill_vans_demo/volunteers", json={"volunteer": kim()})
    assert ok.status_code == 201 and ok.json()["region_id"] == EAST
    p = client.app.state.service.store.partners
    region, entry, v = p.locate_volunteer("volunteer_kim")
    assert entry.org_id == "foothill_vans_demo" and entry.approved and v.availability is None
    # Same id again (any region) -> conflict.
    again = client.post(f"/regions/{EAST}/orgs/foothill_vans_demo/volunteers", json={"volunteer": kim()})
    assert again.status_code == 409 and again.json()["error"] == "ALREADY_REGISTERED"


def test_wrong_region_names_the_right_one(client):
    client.post("/organizations", json={"organization": canonical()})
    r = client.post("/regions/la_county:westside/orgs/foothill_vans_demo/volunteers", json={"volunteer": kim()})
    assert r.status_code == 409 and r.json()["error"] == "WRONG_REGION"
    assert r.json()["reasons"] == [f"CORRECT_REGION:{EAST}"]
    nowhere = client.post(f"/regions/{EAST}/orgs/foothill_vans_demo/volunteers",
                          json={"volunteer": kim(volunteer_id="v_x", location={"type": "Point", "coordinates": [0, 0]})})
    assert nowhere.json()["reasons"] == ["NO_REGION"]


def test_volunteer_needs_existing_org_and_region(client):
    assert client.post(f"/regions/{EAST}/orgs/nope_org/volunteers", json={"volunteer": kim()}).status_code == 404
    client.post("/organizations", json={"organization": canonical()})
    assert client.post("/regions/nope/orgs/foothill_vans_demo/volunteers", json={"volunteer": kim()}).status_code == 404


def test_regions_cannot_overlap(client):
    body = {"region_id": "la_county:overlap", "label": "Overlap (synthetic)",
            "center": {"type": "Point", "coordinates": [-118.10, 34.10]},
            "area": {"type": "Polygon", "coordinates": [[[-118.11, 34.09], [-118.09, 34.09], [-118.09, 34.11],
                                                         [-118.11, 34.11], [-118.11, 34.09]]]}}
    r = client.post("/regions", json={"region": body})
    assert r.status_code == 409 and r.json()["error"] == "REGION_OVERLAP"
    touching = {**body, "region_id": "la_county:north", "area": {"type": "Polygon", "coordinates": [[
        [-118.13, 34.12], [-118.06, 34.12], [-118.06, 34.15], [-118.13, 34.15], [-118.13, 34.12]]]}}
    assert client.post("/regions", json={"region": touching}).status_code == 201  # sharing an edge is fine


def test_presence_and_shelter_sites(client):
    client.post("/organizations", json={"organization": canonical(services=["SHELTER"])})
    assert client.post(f"/regions/{EAST}/orgs/foothill_vans_demo").json()["added"] is True
    site = {"site_id": "fv_site", "name": "Foothill Hall (fictional)",
            "location": {"type": "Point", "coordinates": [-118.08, 34.10]}, "beds_available": 5, "features": [6]}
    assert client.post(f"/regions/{EAST}/orgs/foothill_vans_demo/shelter_sites", json={"site": site}).status_code == 201
    assert client.app.state.service.store.partners.locate_site("fv_site")[0].region_id == EAST


def test_public_org_list_is_sanitized(client):
    r = client.get("/organizations")
    assert r.status_code == 200 and "sim_phone_" not in r.text and "coordinates" not in r.text
    rc = next(o for o in r.json()["organizations"] if o["org_id"] == "red_cross_demo")
    assert rc["volunteer_count"] == 3 and "volunteers" not in rc and len(rc["region_ids"]) == 4


def test_agent_address_registry(client):
    assert client.put("/agents/volunteer_network", json={"agent_address": "agent1qnetwork"}).status_code == 200
    assert client.get("/agents").json()["agents"] == {"volunteer_network": "agent1qnetwork"}
    assert client.put("/agents/not_a_role", json={"agent_address": "x"}).status_code == 404
    client.post("/demo/alerts/trigger", json={"action": "ISSUE", "preset": "ZONE_3_WILDFIRE"})
    feed = client.get("/demo/feeds/caloes").json()
    r = client.post("/alerts/ingest", json={"source": {"source_id": "SYNTHETIC_CALOES",
                                                       "source_type": "OFFICIAL_SIMULATION"}, "payload": feed})
    assert r.json()["network_agent_address"] == "agent1qnetwork"


def test_resident_pickup_sms_only_counts_with_accepted_volunteer(svc):
    from doorstep.models import Evidence
    from .test_matching_v2 import accept, propose, ready
    ready(svc)
    svc.submit_resident_response("case_maria_001", "RECOGIDO", "es", sender="sim_phone_maria", external_id="early")
    assert any(e.event_type == "PICKUP_CONFIRMATION_IGNORED" for e in svc.events.for_case("case_maria_001"))
    aid = propose(svc)["match"]["assignment_id"]
    accept(svc, aid)
    svc.submit_resident_response("case_maria_001", "ya me recogieron", "es", sender="sim_phone_maria", external_id="ok")
    out = svc.confirm_pickup(aid, Evidence(type="VOLUNTEER_AND_RESIDENT_CONFIRMATION", volunteer_confirmed=True))
    assert out["resident_status"] == "PICKUP_CONFIRMED"


def test_registration_is_on_the_timeline(svc):
    svc.registry.register_resident(ResidentProfile(**rosa()))
    types = [e.event_type for e in svc.events.all()]
    assert "RESIDENT_REGISTERED" in types

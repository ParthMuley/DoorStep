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
    orgs = {o.org_id: o for o in svc.store.list_organizations()}
    assert set(orgs) == {"eastside_rides_demo", "neighbor_sedans_demo", "red_cross_demo", "unlisted_vans_demo",
                         "flood_only_demo", "civic_shelter_demo", "recovery_housing_demo"}
    assert orgs["unlisted_vans_demo"].approved is False
    assert orgs["flood_only_demo"].calamity_types == ["FLOOD"]
    assert [v.volunteer_id for v in orgs[ORG].volunteers] == ["volunteer_sarah"]
    assert orgs[ORG].volunteers[0].needs_they_can_cater == [1, 2, 4, 7]
    assert svc.db.orgs["organizations"].count_documents({}) == 7
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
    assert body["zone_status"] == "OUTSIDE_KNOWN_ZONES" and body["needs"] == [1, 6]
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


# ------------------------------------------------------------ organizations
def test_register_organization_resets_availability(client):
    body = new_org()
    body["volunteers"][0]["availability"] = {"alert_id": "alert_x", "state": "AVAILABLE"}
    body["volunteers"][0]["reserved_case_id"] = "case_x"
    r = client.post("/organizations", json={"organization": body})
    assert r.status_code == 201 and r.json()["volunteers"] == ["volunteer_kim"]
    kim = client.app.state.service.store.get_organization("foothill_vans_demo").volunteers[0]
    assert kim.availability is None and kim.reserved_case_id is None
    assert client.post("/organizations", json={"organization": new_org()}).status_code == 409


def test_duplicate_volunteer_ids_rejected(client):
    body = new_org()
    body["volunteers"].append(dict(body["volunteers"][0]))
    assert client.post("/organizations", json={"organization": body}).status_code == 422


def test_public_org_list_is_sanitized(client):
    r = client.get("/organizations")
    assert r.status_code == 200
    assert "sim_phone_" not in r.text  # no volunteer (or anyone's) phone numbers
    for org in r.json()["organizations"]:
        assert "volunteers" not in org and set(org["location"]) == {"label"}  # no volunteer records, no coordinates
    eastside = next(o for o in r.json()["organizations"] if o["org_id"] == ORG)
    assert eastside["volunteer_count"] == 1 and "volunteers" not in eastside


def test_add_volunteer_requires_matching_org_agent(client):
    vol = new_org()["volunteers"][0]
    path = f"/organizations/{ORG}/volunteers"
    assert client.post(path, json={"volunteer": vol}).status_code == 403
    assert client.post(path, json={"volunteer": vol}, headers=org_headers("red_cross_demo")).status_code == 403
    assert client.post(path, json={"volunteer": vol}, headers=org_headers(ORG)).status_code == 201
    assert client.post(path, json={"volunteer": vol}, headers=org_headers(ORG)).status_code == 409


# ---------------------------------------------------- org-scoped volunteers
def test_org_agent_sees_only_its_own_volunteers(client):
    r = client.get(f"/orgs/{ORG}/volunteers", headers=org_headers(ORG))
    assert r.status_code == 200
    vols = r.json()["volunteers"]
    assert [v["volunteer_id"] for v in vols] == ["volunteer_sarah"]
    assert vols[0]["phone"] == "sim_phone_sarah" and vols[0]["availability"]["state"] == "UNASKED"
    # Another org's agent cannot read Eastside's volunteers.
    assert client.get(f"/orgs/{ORG}/volunteers", headers=org_headers("red_cross_demo")).status_code == 403
    client.headers.pop("Authorization")
    assert client.get(f"/orgs/{ORG}/volunteers", headers=org_headers(ORG)).status_code == 401


def test_availability_recorded_per_alert(client):
    path = f"/orgs/{ORG}/volunteers/volunteer_sarah/availability"
    r = client.post(path, json={"alert_id": "alert_001", "available": True}, headers=org_headers(ORG))
    assert r.status_code == 200 and r.json()["availability"] == "AVAILABLE" and r.json()["duplicate"] is False
    again = client.post(path, json={"alert_id": "alert_001", "available": True}, headers=org_headers(ORG))
    assert again.json()["duplicate"] is True
    view = client.get(f"/orgs/{ORG}/volunteers", params={"alert_id": "alert_001"}, headers=org_headers(ORG)).json()
    assert view["volunteers"][0]["availability"]["state"] == "AVAILABLE"
    other = client.get(f"/orgs/{ORG}/volunteers", params={"alert_id": "alert_999"}, headers=org_headers(ORG)).json()
    assert other["volunteers"][0]["availability"]["state"] == "UNASKED"
    stale = client.post(path, json={"alert_id": "alert_000", "available": True}, headers=org_headers(ORG))
    assert stale.status_code == 409 and stale.json()["error"] == "STALE_AVAILABILITY"


def test_availability_rules(client):
    h = org_headers("unlisted_vans_demo")
    r = client.post("/orgs/unlisted_vans_demo/volunteers/volunteer_tom/availability",
                    json={"alert_id": "alert_001", "available": True}, headers=h)
    assert r.status_code == 409 and r.json()["error"] == "VOLUNTEER_NOT_APPROVED"
    r = client.post(f"/orgs/{ORG}/volunteers/volunteer_nobody/availability",
                    json={"alert_id": "alert_001", "available": True}, headers=org_headers(ORG))
    assert r.status_code == 404
    # An org agent cannot answer for another org's volunteer.
    r = client.post(f"/orgs/{ORG}/volunteers/volunteer_sarah/availability",
                    json={"alert_id": "alert_001", "available": True}, headers=org_headers("red_cross_demo"))
    assert r.status_code == 403


def test_registration_is_on_the_timeline(svc):
    svc.registry.register_resident(ResidentProfile(**rosa()))
    types = [e.event_type for e in svc.events.all()]
    assert "RESIDENT_REGISTERED" in types

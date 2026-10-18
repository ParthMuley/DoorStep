"""B8 / contract v2.2: ASI:One linking, self-registration, invites, approval, the
15-minute reply deadline and hosted route maps (plan rev 4 §0.5, rev 5 §00, rev 6 §000)."""

from datetime import datetime, timedelta, timezone

import pytest

from doorstep.services import deadlines

from .conftest import MARIA, MARIA_SENDER
from .test_matching_v2 import ingest, propose

DOORSTEP = {"X-Agent-Token": "change-me-doorstep-agent-token"}
ROUTE = {"X-Agent-Token": "change-me-route-agent-token"}
MARIA_ASI = "user1qmaria_demo_address"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MAP_ID = "a" * 32


def link(client, code, address, headers=DOORSTEP):
    return client.post("/link", headers=headers, json={"schema_version": "2.0", "code": code,
                                                       "asi_one_address": address})


@pytest.fixture
def clock(monkeypatch):
    state = {"t": datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(deadlines, "now", lambda: state["t"])

    def advance(minutes):
        state["t"] += timedelta(minutes=minutes)
    return advance


def warning_checkin(client):
    client.post("/demo/alerts/trigger", json={"schema_version": "2.0", "action": "ISSUE", "preset": "ZONE_3_WILDFIRE",
                                             "poll_now": True})


# ------------------------------------------------------------------ linking
def test_link_needs_the_doorstep_agent_token(client):
    assert link(client, "MARIA-4821", MARIA_ASI, headers={}).status_code == 401
    assert link(client, "MARIA-4821", MARIA_ASI, headers={"X-Agent-Token": "change-me-network-agent-token"}).status_code == 401


def test_link_code_works_once_and_returns_the_person(client):
    r = link(client, "maria-4821", MARIA_ASI)  # case-insensitive
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "RESIDENT" and body["resident_id"] == "resident_001" and body["case_id"] == MARIA
    again = link(client, "MARIA-4821", MARIA_ASI)
    assert again.status_code == 409 and again.json()["error"] == "CODE_SPENT"  # even from the same address
    assert link(client, "NOPE-0000", "user1qx").json()["error"] == "UNKNOWN_CODE"


def test_one_address_one_person(client):
    link(client, "MARIA-4821", MARIA_ASI)
    r = link(client, "SARAH-7310", MARIA_ASI)
    assert r.status_code == 409 and r.json()["error"] == "ADDRESS_ALREADY_LINKED"
    vol = link(client, "SARAH-7310", "user1qsarah")
    assert vol.json()["role"] == "VOLUNTEER" and vol.json()["org_id"] == "eastside_rides_demo"
    coord = link(client, "COORD-1150", "user1qcoord").json()
    assert coord["role"] == "COORDINATOR" and coord["coordinator_id"] == "coordinator_demo"


def test_unlink_then_relink_needs_a_new_code(client):
    link(client, "MARIA-4821", MARIA_ASI)
    assert client.post("/unlink", headers=DOORSTEP, json={"asi_one_address": MARIA_ASI}).status_code == 200
    assert link(client, "MARIA-4821", MARIA_ASI).json()["error"] == "CODE_SPENT"
    client.post("/demo/reset")  # reissues the public demo codes
    assert link(client, "MARIA-4821", MARIA_ASI).status_code == 200


# ------------------------------------------------------------ sender check
def reply(client, text, sender, headers=None, ext=None):
    return client.post(f"/cases/{MARIA}/responses", headers=headers or {},
                       json={"text": text, "sender": sender, "external_id": ext})


def test_linked_sender_accepted_only_through_the_doorstep_agent(client):
    warning_checkin(client)
    link(client, "MARIA-4821", MARIA_ASI)
    assert reply(client, "1", MARIA_ASI).status_code == 401  # linked address without the Doorstep token
    r = reply(client, "1 necesito ayuda", MARIA_ASI, DOORSTEP, "asi-1")
    assert r.status_code == 200, r.text
    assert r.json()["communication_status"] == "REPLIED"
    assert reply(client, "1", "user1qstranger", DOORSTEP).status_code == 403  # not linked to this case
    link(client, "SARAH-7310", "user1qsarah")
    assert reply(client, "1", "user1qsarah", DOORSTEP).status_code == 403  # linked, but to someone else


def test_sim_sender_still_works(client):
    warning_checkin(client)
    assert reply(client, "1 necesito ayuda", MARIA_SENDER, ext="sim-1").status_code == 200


def test_case_view_shows_contact_without_the_address(client):
    warning_checkin(client)
    before = client.get(f"/cases/{MARIA}").json()
    assert before["contact"] == {"channel": "SIM", "linked": False, "linked_at": None}
    assert before["reachability"] == "SIM_ONLY"
    link(client, "MARIA-4821", MARIA_ASI)
    after = client.get(f"/cases/{MARIA}").json()
    assert after["contact"]["channel"] == "ASI_ONE" and after["reachability"] == "LINKED_ASI_ONE"
    assert MARIA_ASI not in str(after)  # GET views never expose the address


# -------------------------------------------------------- self-registration
RESIDENT = {"name": "Rosa (synthetic)", "language": "es", "needs": [1, 4], "pet_count": 1,
            "address": {"label": "123 Real St, typed by user", "lat": 34.1012, "lon": -118.0964,
                        "geocode_confidence": "HIGH"},
            "consents": {"CHECKIN": True, "TRANSPORT": True, "DESTINATION": True}}


def register(client, role, address, profile, org_id=None, headers=DOORSTEP):
    return client.post("/register", headers=headers, json={"schema_version": "2.0", "role": role,
                                                           "asi_one_address": address, "profile": profile,
                                                           "org_id": org_id})


def test_register_resident_links_and_never_stores_the_typed_address(client):
    assert register(client, "RESIDENT", "user1qrosa", RESIDENT, headers={}).status_code == 401
    r = register(client, "RESIDENT", "user1qrosa", RESIDENT)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "RESIDENT" and body["case_id"] == f"case_{body['resident_id']}"
    assert register(client, "RESIDENT", "user1qrosa", RESIDENT).json()["error"] == "ADDRESS_ALREADY_LINKED"
    stored = client.app.state.service.store.get_resident_profile(body["resident_id"])
    assert stored.address.label == "SELF-REGISTERED (demo)"
    # The new resident gets a real check-in after an alert, and can answer from ASI:One.
    warning_checkin(client)
    case = client.get(f"/cases/{body['case_id']}").json()
    assert case["communication_status"] == "SENT" and case["reachability"] == "LINKED_ASI_ONE"
    ok = client.post(f"/cases/{body['case_id']}/responses", headers=DOORSTEP,
                     json={"text": "1", "sender": "user1qrosa", "external_id": "rosa-1"})
    assert ok.status_code == 200, ok.text


VOLUNTEER = {"name": "Alex (synthetic)", "location": {"type": "Point", "coordinates": [-118.098, 34.100]},
             "vehicle_type": "WHEELCHAIR_VAN", "vehicle_seats": 2, "wheelchair_spaces": 1, "pet_capacity": 1,
             "needs_they_can_cater": [1, 2, 4, 7], "approved": True}  # approved is ignored on self-registration


def test_self_registered_volunteer_starts_unapproved_until_the_org_approves(client):
    r = register(client, "VOLUNTEER", "user1qalex", VOLUNTEER, org_id="eastside_rides_demo")
    assert r.status_code == 201, r.text
    vid = r.json()["volunteer_id"]
    assert r.json()["approved"] is False and r.json()["region_id"] == "la_county:east_valley"
    pending = client.get("/volunteers/pending", params={"org_id": "eastside_rides_demo"}).json()["volunteers"]
    assert vid in [p["volunteer_id"] for p in pending]
    assert client.post(f"/orgs/red_cross_demo/volunteers/{vid}/approve").json()["error"] == "WRONG_ORG"
    ok = client.post(f"/orgs/eastside_rides_demo/volunteers/{vid}/approve", json={"approved": True})
    assert ok.status_code == 200 and ok.json()["approved"] is True
    far = {**VOLUNTEER, "location": {"type": "Point", "coordinates": [-100.0, 40.0]}}
    assert register(client, "VOLUNTEER", "user1qfar", far, org_id="eastside_rides_demo").json()["error"] == "NO_REGION"


def test_org_invite_code_links_an_imported_volunteer(client):
    r = client.post("/organizations/neighbor_sedans_demo/invites", json={"volunteer_id": "volunteer_joe"})
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert code.startswith("NEIGHBOR-")
    linked = link(client, code, "user1qjoe").json()
    assert linked["volunteer_id"] == "volunteer_joe" and linked["org_id"] == "neighbor_sedans_demo"
    wrong = client.post("/organizations/red_cross_demo/invites", json={"volunteer_id": "volunteer_joe"})
    assert wrong.json()["error"] == "WRONG_ORG"


# --------------------------------------------------------------- deadlines
def test_resident_silence_after_15_minutes_is_unresolved_never_safe(client, clock):
    warning_checkin(client)
    case = client.get(f"/cases/{MARIA}").json()
    assert case["communication_status"] == "SENT" and case["reply_by"] == "2026-10-18T12:15:00Z"
    clock(14)
    assert client.get(f"/cases/{MARIA}").json()["communication_status"] == "SENT"
    clock(2)
    case = client.get(f"/cases/{MARIA}").json()  # applied on read, no sweep needed
    assert case["communication_status"] == "NO_REPLY_AFTER_DEADLINE"
    assert case["unresolved"] is True and case["resident_status"] != "ARRIVAL_CONFIRMED"
    assert "NOT evidence of danger or of safety" in case["next_step"]
    queue = client.get("/dashboard/summary").json()["unresolved"]
    assert any(u["case_id"] == MARIA and u["reason"] == "NO_REPLY_AFTER_DEADLINE" for u in queue)
    # A late answer still counts.
    late = reply(client, "1 necesito ayuda", MARIA_SENDER, ext="late-1")
    assert late.json()["communication_status"] == "REPLIED"


def test_volunteer_silence_becomes_no_reply_and_late_yes_counts(svc, clock):
    svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_WILDFIRE")
    alert_id = next(a["alert_id"] for a in ingest(svc)["new_alerts"] if a["status"] == "WARNING")
    svc.alerts.start_outreach(alert_id)
    v = svc.store.partners.locate_volunteer("volunteer_sarah")[2]
    assert v.availability.state == "ASKED" and v.availability.reply_by == "2026-10-18T12:15:00Z"
    clock(16)
    out = svc.deadlines.sweep()
    assert {"org_id": "eastside_rides_demo", "volunteer_id": "volunteer_sarah"} in out["volunteers_no_reply"]
    assert out["notify"] and "not safety" in out["notify"][0]["text"]
    assert svc.store.partners.locate_volunteer("volunteer_sarah")[2].availability.state == "NO_REPLY"
    svc.submit_resident_response(MARIA, "1 necesito ayuda", None, sender=MARIA_SENDER, external_id="m1")
    svc.submit_resident_response(MARIA, "SI", None, sender=MARIA_SENDER, external_id="m2")
    rejected = {r["volunteer_id"]: r for r in propose(svc, create_proposal=False)["evaluation"]["volunteers"]["rejected"]}
    assert "NO_REPLY" in rejected["volunteer_sarah"]["reason_codes"]
    svc.registry.record_availability(alert_id, "volunteer_sarah", org_id="eastside_rides_demo", available=True)
    eligible = [e["volunteer_id"] for e in propose(svc, create_proposal=False, idempotency_key="k2")
                ["evaluation"]["volunteers"]["eligible"]]
    assert "volunteer_sarah" in eligible


def test_sweep_needs_an_agent_token(client):
    assert client.post("/deadlines/sweep", json={}).status_code == 401
    r = client.post("/deadlines/sweep", headers=DOORSTEP, json={})
    assert r.status_code == 200 and r.json()["deadline_minutes"] == 15


def test_availability_sender_must_be_the_linked_volunteer(client):
    client.post("/demo/alerts/trigger", json={"schema_version": "2.0", "action": "ISSUE",
                                             "preset": "ZONE_3_WILDFIRE", "poll_now": True})
    alert_id = next(a["alert_id"] for a in client.get("/alerts/active").json()["alerts"] if a["status"] == "WARNING")
    net = {"X-Agent-Token": "change-me-network-agent-token"}
    client.post(f"/alerts/{alert_id}/outreach", headers=net, json={"idempotency_key": "o1"})
    link(client, "SARAH-7310", "user1qsarah")
    body = {"org_id": "eastside_rides_demo", "available": True, "sender": "user1qsomeone"}
    url = f"/alerts/{alert_id}/volunteers/volunteer_sarah/availability"
    assert client.post(url, headers=net, json=body).status_code == 403
    assert client.post(url, headers=net, json={**body, "sender": "user1qsarah"}).status_code == 200


# -------------------------------------------------------------------- maps
def test_map_upload_needs_route_token_and_a_png(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://doorstep-demo.example")
    put = lambda body=PNG, h=ROUTE, mid=MAP_ID, ct="image/png": client.put(  # noqa: E731
        f"/maps/{mid}", content=body, headers={**h, "Content-Type": ct})
    assert put(h={}).status_code == 401
    assert put(ct="image/jpeg").status_code == 415
    assert put(body=b"not a png").status_code == 409
    assert put(mid="short").status_code == 409
    assert put(body=PNG + b"\x00" * (300 * 1024)).json()["error"] == "IMAGE_TOO_LARGE"
    ok = put()
    assert ok.status_code == 201 and ok.json()["url"] == f"https://doorstep-demo.example/maps/{MAP_ID}.png"
    public = client.get(f"/maps/{MAP_ID}.png", headers={"Authorization": ""})
    assert public.status_code == 200 and public.content == PNG
    assert public.headers["content-type"] == "image/png" and public.headers["x-robots-tag"] == "noindex"
    assert client.get(f"/maps/{'b' * 32}.png").status_code == 404


def test_map_expires(client, clock):
    client.put(f"/maps/{MAP_ID}", content=PNG, headers={**ROUTE, "Content-Type": "image/png"})
    clock(24 * 60 + 1)
    assert client.get(f"/maps/{MAP_ID}.png").status_code == 404


def test_map_gone_when_assignment_ends(svc):
    svc.db.coll("assignments").insert_one({"_id": "assign_x", "status": "ACCEPTED"})
    svc.maps.put(MAP_ID, PNG, assignment_id=None, base_url="http://t")
    svc.db.coll("maps").update_one({"_id": MAP_ID}, {"$set": {"assignment_id": "assign_x"}})
    assert svc.maps.get(MAP_ID) == PNG
    svc.db.coll("assignments").update_one({"_id": "assign_x"}, {"$set": {"status": "COMPLETED"}})
    with pytest.raises(Exception):
        svc.maps.get(MAP_ID)

"""Optional: run both scenarios against a REAL MongoDB server.

Skipped unless DOORSTEP_TEST_MONGODB_URI is set, e.g.
    scripts/start_mongo.sh && DOORSTEP_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 pytest tests/unit/test_real_mongo.py
Uses throwaway database names and drops them afterwards.
"""

import os
import uuid

import pytest

URI = os.environ.get("DOORSTEP_TEST_MONGODB_URI")
pytestmark = pytest.mark.skipif(not URI, reason="DOORSTEP_TEST_MONGODB_URI not set")


def quiet(*_a, **_k):
    pass


def test_scenarios_on_real_mongodb(monkeypatch):
    from fastapi.testclient import TestClient
    from pymongo import MongoClient

    from doorstep.api import app as app_module
    from doorstep.demo.scenarios import run_scenario_a, run_scenario_b
    from doorstep.services.db import Database

    suffix = uuid.uuid4().hex[:8]
    users, orgs = f"doorstep_users_test_{suffix}", f"doorstep_orgs_test_{suffix}"
    real = MongoClient(URI, serverSelectionTimeoutMS=5000)
    monkeypatch.setattr(app_module, "Database", lambda _path=None: Database(client=real, users_db=users, orgs_db=orgs))
    monkeypatch.delenv("DEMO_AUTH_TOKEN", raising=False)
    try:
        client = TestClient(app_module.create_app(seed=True),
                            headers={"Authorization": "Bearer change-me-local-demo-token"})
        assert run_scenario_a(client, log=quiet)["resident_status"] == "ARRIVAL_CONFIRMED"
        assert run_scenario_b(client, log=quiet)["unresolved"] is True
        # Contract v2.0 flow: alert -> outreach -> volunteer match/reservation -> accept -> pickup -> shelter.
        from doorstep.demo.scenarios import run_scenario_a_v2, run_scenario_b_v2, run_scenario_c_v2
        client.post("/demo/reset")
        assert run_scenario_a_v2(client, log=quiet)["resident_status"] == "ARRIVAL_CONFIRMED"
        assert run_scenario_b_v2(client, log=quiet)["unresolved"] is True
        client.post("/demo/reset")
        assert run_scenario_c_v2(client, log=quiet)["zone_status"] == "STALE"
    finally:
        real.drop_database(users)
        real.drop_database(orgs)


def test_alert_ingest_and_outreach_on_real_mongodb():
    from pymongo import MongoClient

    from doorstep.services.db import Database
    from doorstep.services.engine import DoorstepService

    suffix = uuid.uuid4().hex[:8]
    users, orgs = f"doorstep_users_test_{suffix}", f"doorstep_orgs_test_{suffix}"
    real = MongoClient(URI, serverSelectionTimeoutMS=5000)
    try:
        svc = DoorstepService(Database(client=real, users_db=users, orgs_db=orgs))
        svc.reset()
        svc.alerts.feed.trigger("ISSUE", preset="ZONE_3_WILDFIRE")
        payload = svc.alerts.feed.render_caloes()
        first = svc.alerts.ingest(source_id="SYNTHETIC_CALOES", source_type="OFFICIAL_SIMULATION", url="t",
                                  fetched_at=None, fetch_ok=True, http_status=200, error=None, payload=payload,
                                  idempotency_key="real-1")
        repeat = svc.alerts.ingest(source_id="SYNTHETIC_CALOES", source_type="OFFICIAL_SIMULATION", url="t",
                                   fetched_at=None, fetch_ok=True, http_status=200, error=None, payload=payload,
                                   idempotency_key="real-2")
        assert len(first["checkins_sent"]) == 2 and repeat["checkins_sent"] == []
        alert_id = first["new_alerts"][0]["alert_id"]
        assert not svc.store.partners.is_mock  # the real 2dsphere $geoIntersects path is exercised here
        out = svc.alerts.start_outreach(alert_id)
        asked = {a["volunteer_id"] for o in out["orgs"] for a in o["asked"]}
        assert "volunteer_sam" not in asked and {"volunteer_lee", "volunteer_maya"} <= asked
        svc.inbound_sms("sim_phone_lee", "YES", external_id="lee-real")
        p = svc.store.partners
        assert p.locate_volunteer("volunteer_lee")[2].availability.state == "AVAILABLE"
        assert p.locate_volunteer("volunteer_maya")[2].availability.state == "ASKED"
        assert p.region_for_point(34.1012, -118.0964).region_id == "la_county:east_valley"
        near = [r.region_id for r, _ in p.regions_near(__import__("shapely.geometry", fromlist=["Point"]).Point(-122.42, 37.76), 5)]
        assert near == ["sf:mission"]
        assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_002")) == "ORDER"
    finally:
        real.drop_database(users)
        real.drop_database(orgs)


def test_links_and_maps_on_real_mongodb(monkeypatch):
    """Contract v2.2 on a real server: atomic code spend, binary PNG round trip."""
    from fastapi.testclient import TestClient
    from pymongo import MongoClient

    from doorstep.api import app as app_module
    from doorstep.services.db import Database

    suffix = uuid.uuid4().hex[:8]
    users, orgs = f"doorstep_users_test_{suffix}", f"doorstep_orgs_test_{suffix}"
    real = MongoClient(URI, serverSelectionTimeoutMS=5000)
    monkeypatch.setattr(app_module, "Database", lambda _path=None: Database(client=real, users_db=users, orgs_db=orgs))
    try:
        client = TestClient(app_module.create_app(seed=True),
                            headers={"Authorization": "Bearer change-me-local-demo-token"})
        doorstep = {"X-Agent-Token": "change-me-doorstep-agent-token"}
        first = client.post("/link", headers=doorstep, json={"code": "MARIA-4821", "asi_one_address": "user1qm"})
        assert first.status_code == 200, first.text
        again = client.post("/link", headers=doorstep, json={"code": "MARIA-4821", "asi_one_address": "user1qz"})
        assert again.json()["error"] == "CODE_SPENT"
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
        put = client.put("/maps/" + "m" * 30, content=png,
                         headers={"X-Agent-Token": "change-me-route-agent-token", "Content-Type": "image/png"})
        assert put.status_code == 201, put.text
        assert client.get("/maps/" + "m" * 30 + ".png").content == png
    finally:
        real.drop_database(users)
        real.drop_database(orgs)

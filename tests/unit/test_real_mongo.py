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
        svc.alerts.start_outreach("red_cross_demo", alert_id)
        svc.inbound_sms("sim_phone_lee", "YES", external_id="lee-real")
        states = {v["volunteer_id"]: v["availability"]["state"]
                  for v in svc.registry.org_volunteers("red_cross_demo", alert_id)["volunteers"]}
        assert states == {"volunteer_maya": "ASKED", "volunteer_lee": "AVAILABLE"}
        assert svc.alerts.zone_status_label(svc.store.get_resident_profile("resident_002")) == "ORDER"
    finally:
        real.drop_database(users)
        real.drop_database(orgs)

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

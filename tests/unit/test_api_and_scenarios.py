"""HTTP contract (v1.0), auth, errors, determinism, and both end-to-end scenarios."""

from doorstep.demo.scenarios import run_scenario_a, run_scenario_b
from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService

from .conftest import maria_accepted


def quiet(*_a, **_k):
    pass


def test_health_and_reads_are_public(client):
    client.headers.pop("Authorization")
    assert client.get("/health").json() == {"schema_version": "1.0", "status": "ok", "simulation_mode": True}
    assert client.get("/cases").status_code == 200


def test_writes_require_bearer_token(client):
    client.headers.pop("Authorization")
    r = client.post("/demo/reset")
    assert r.status_code == 401 and r.json()["error"] == "UNAUTHORIZED"
    assert client.post("/demo/warnings", json={"zone_id": "zone_3"}).status_code == 401
    client.headers["Authorization"] = "Bearer wrong"
    assert client.post("/demo/reset").status_code == 401
    client.headers["Authorization"] = "change-me-local-demo-token"  # missing "Bearer"
    assert client.post("/demo/reset").status_code == 401


def test_correlation_id_header_is_echoed(client):
    r = client.post("/demo/warnings", json={"zone_id": "zone_3"}, headers={"X-Correlation-ID": "corr_7f3a"})
    assert r.status_code == 201
    assert r.json()["correlation_id"] == "corr_7f3a" and r.headers["X-Correlation-ID"] == "corr_7f3a"
    events = client.app.state.service.events.for_case("case_maria_001")
    assert all(e.correlation_id == "corr_7f3a" for e in events)


def test_error_shape(client):
    r = client.get("/cases/nope", headers={"X-Correlation-ID": "corr_x"})
    assert r.status_code == 404
    assert r.json() == {"schema_version": "1.0", "error": "NOT_FOUND", "detail": r.json()["detail"],
                        "correlation_id": "corr_x"}
    r = client.post("/cases/case_maria_001/escalations", json={"reason": "NOT_A_REASON"})
    assert r.status_code == 422 and r.json()["error"] == "VALIDATION_ERROR"


def test_unknown_fields_rejected_on_writes(client):
    r = client.post("/demo/warnings", json={"zone_id": "zone_3", "surprise": 1})
    assert r.status_code == 422


def test_scenario_a_maria(client):
    assert run_scenario_a(client, log=quiet)["resident_status"] == "ARRIVAL_CONFIRMED"


def test_scenario_b_david(client):
    final = run_scenario_b(client, log=quiet)
    assert final["unresolved"] and final["resident_status"] == "REQUIRES_COORDINATOR"


def test_both_scenarios_and_list_filters(client):
    run_scenario_a(client, log=quiet)
    run_scenario_b(client, log=quiet)
    unresolved = client.get("/cases", params={"unresolved": True}).json()["cases"]
    assert [c["case_id"] for c in unresolved] == ["case_david_002"]
    green = client.get("/cases", params={"zone_id": "zone_3", "resident_status": "ARRIVAL_CONFIRMED"}).json()
    assert [c["case_id"] for c in green["cases"]] == ["case_maria_001"]


def test_reset_is_deterministic():
    def snapshot():
        svc = DoorstepService(Database(":memory:"))
        svc.reset()
        aid = maria_accepted(svc)
        view = svc.get_case_status("case_maria_001")
        return aid, view["resident_status"], [(e["type"], e["event_id"]) for e in view["timeline"]]

    assert snapshot() == snapshot()


def test_reset_restores_seed_state(svc):
    maria_accepted(svc)
    svc.reset()
    assert svc.store.list_cases() == []


def test_persisted_state_survives_restart(tmp_path):
    path = str(tmp_path / "demo.db")
    svc = DoorstepService(Database(path))
    svc.reset()
    aid = maria_accepted(svc)
    svc.db.close()
    restarted = DoorstepService(Database(path))
    assert restarted.store.get_case("case_maria_001").resident_status == "PROVIDER_ACCEPTED"
    assert restarted.respond_assignment(aid, "transport_org_a", "ACCEPTED")["duplicate"] is True


def test_offers_in_developer_a_agent_format_are_accepted_but_not_trusted(client):
    """A's provider agents add fields like approved_by_partner/base_node. They are ignored:
    an unapproved provider claiming approval is still rejected via B's registry."""
    from doorstep.demo import seed

    offers = [{**o, "approved_by_partner": True, "base_node": "node_depot_east", "org_name": "x (fictional)",
               "accepts_requests": True, "valid_for_minutes": 30} for o in seed.transport_offers()]
    client.post("/demo/warnings", json={"zone_id": "zone_3"})
    client.post("/cases/case_maria_001/responses", json={"text": "1", "sender": seed.MARIA_SENDER})
    client.post("/cases/case_maria_001/responses", json={"text": "SI", "sender": seed.MARIA_SENDER})
    r = client.post("/cases/case_maria_001/transport/evaluate", json={"request_id": "r1", "candidate_offers": offers})
    assert r.status_code == 200, r.text
    rejected = {x["provider_id"]: x["reasons"] for x in r.json()["rejected"]}
    assert "PROVIDER_NOT_APPROVED" in rejected["transport_org_c"]

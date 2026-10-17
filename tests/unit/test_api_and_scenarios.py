"""API contract, auth, determinism, and both end-to-end scenarios (API only)."""

from doorstep.demo.scenarios import run_scenario_a, run_scenario_b
from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService

from .conftest import maria_accepted


def quiet(*_a, **_k):
    pass


def test_health_is_public(client):
    client.headers.pop("X-Demo-Token")
    assert client.get("/health").status_code == 200


def test_mutations_require_demo_token(client):
    client.headers.pop("X-Demo-Token")
    assert client.post("/demo/reset").status_code == 401
    assert client.post("/demo/warnings", json={"zone_id": "zone_3"}).status_code == 401
    assert client.get("/cases").status_code == 401
    client.headers["X-Demo-Token"] = "wrong"
    assert client.post("/demo/reset").status_code == 401


def test_scenario_a_maria(client):
    final = run_scenario_a(client, log=quiet)
    assert final["case"]["resident_status"] == "ARRIVAL_CONFIRMED"


def test_scenario_b_david(client):
    final = run_scenario_b(client, log=quiet)
    assert final["unresolved"] and final["case"]["resident_status"] == "REQUIRES_COORDINATOR"


def test_both_scenarios_together(client):
    run_scenario_a(client, log=quiet)
    run_scenario_b(client, log=quiet)
    unresolved = client.get("/cases", params={"unresolved": True}).json()["cases"]
    assert [c["case_id"] for c in unresolved] == ["case_david_002"]


def test_domain_errors_map_to_http(client):
    assert client.get("/cases/nope").status_code == 404
    r = client.post("/cases/case_maria_001/escalate", json={"reason": "NOT_A_REASON"})
    assert r.status_code == 422


def test_reset_is_deterministic():
    def snapshot():
        svc = DoorstepService(Database(":memory:"))
        svc.reset()
        ta, da = maria_accepted(svc)
        view = svc.get_case_status("case_maria_001")
        return (ta.assignment_id, da.assignment_id, view["case"]["resident_status"],
                [(e["event_type"], e["event_id"]) for e in view["timeline"]],
                [o["offer_id"] for o in view["offers"]])

    assert snapshot() == snapshot()


def test_reset_restores_seed_state(svc):
    maria_accepted(svc)
    svc.reset()
    assert svc.store.list_cases() == []
    assert svc.store.get_transport_provider("transport_org_a").available_trips == 1


def test_persisted_state_survives_restart(tmp_path):
    path = str(tmp_path / "demo.db")
    svc = DoorstepService(Database(path))
    svc.reset()
    ta, _ = maria_accepted(svc)
    svc.db.close()
    restarted = DoorstepService(Database(path))
    assert restarted.store.get_case("case_maria_001").resident_status == "PROVIDER_ACCEPTED"
    again = restarted.respond_assignment(ta.assignment_id, ta.provider_id, True)
    assert again["duplicate"] is True  # no duplicate action after restart

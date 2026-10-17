"""A's DoorstepBackend client against B's real API (in-process)."""

import pytest

from doorstep.demo.seed import destination_offers, transport_offers
from doorstep.workflows.backend_client import BackendError, transport_requirements
from tests.integration.backend_fixtures import DAVID, MARIA, confirm_needs, make_backend


async def test_case_exists_only_after_simulated_warning(monkeypatch):
    backend = make_backend(monkeypatch)
    assert (await backend.health())["simulation_mode"] is True
    with pytest.raises(BackendError) as err:
        await backend.get_case_status(MARIA, "corr_t1")
    assert err.value.status_code == 404
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_t1")
    case = await backend.get_case_status(MARIA, "corr_t1")
    assert case["case_id"] == MARIA
    assert case["needs_confirmed"] is False


async def test_evaluate_refused_until_needs_confirmed(monkeypatch):
    backend = make_backend(monkeypatch)
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_t2")
    with pytest.raises(BackendError) as err:
        await backend.evaluate_transport(MARIA, "req_x", transport_offers(), "corr_t2")
    assert err.value.status_code == 409
    assert err.value.code == "NEEDS_NOT_CONFIRMED"


async def test_maria_eligibility_and_proposal(monkeypatch):
    backend = make_backend(monkeypatch)
    await confirm_needs(backend)
    case = await backend.get_case_status(MARIA, "corr_t3")
    assert transport_requirements(case)["wheelchair_accessible_vehicle"] is True

    t = await backend.evaluate_transport(MARIA, "req_t", transport_offers(), "corr_t3")
    assert [e["offer_id"] for e in t["eligible"]][0] == "offer_t_001"
    rejected = {r["offer_id"]: r["reasons"] for r in t["rejected"]}
    assert "NOT_WHEELCHAIR_ACCESSIBLE" in rejected["offer_t_002"]
    d = await backend.evaluate_destination(MARIA, "req_d", destination_offers(), "corr_t3")
    assert d["eligible"][0]["offer_id"] == "offer_d_001"

    proposal = await backend.propose_assignment(MARIA, "offer_t_001", "offer_d_001", f"{MARIA}:transport:v1", "corr_t3")
    assert proposal["service_status"] == "AWAITING_PROVIDER"
    assert proposal["confirmed_pickup_at"] is None


async def test_david_unsafe_zone_is_refused(monkeypatch):
    backend = make_backend(monkeypatch)
    await confirm_needs(backend)
    t = await backend.evaluate_transport(DAVID, "req_t", transport_offers(), "corr_t4")
    assert t["eligible"] == []
    assert t["escalation_required"] is True
    with pytest.raises(BackendError) as err:
        await backend.propose_assignment(DAVID, "offer_t_001", "offer_d_001", f"{DAVID}:transport:v1", "corr_t4")
    assert err.value.status_code == 409

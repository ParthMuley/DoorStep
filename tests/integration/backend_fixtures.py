"""In-process Developer B backend for A's integration tests (real FastAPI app, real
matching rules, in-memory SQLite) reached through A's DoorstepBackend HTTP client."""

import httpx

from doorstep.api.app import create_app
from doorstep.workflows.backend_client import DoorstepBackend

MARIA = "case_maria_001"
DAVID = "case_david_002"


def make_backend(monkeypatch) -> DoorstepBackend:
    monkeypatch.setenv("SIMULATION_MODE", "true")
    monkeypatch.setenv("DEMO_AUTH_TOKEN", "change-me-local-demo-token")  # .env must not leak in
    app = create_app(":memory:", seed=True)
    return DoorstepBackend(base_url="http://backend.test", token="change-me-local-demo-token",
                           transport=httpx.ASGITransport(app=app))


async def confirm_needs(backend: DoorstepBackend) -> None:
    """Simulated official warning + both residents reply and confirm (B's message simulator path)."""
    await backend.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_setup")
    await backend.submit_resident_response(MARIA, "1 Necesito ayuda, uso silla de ruedas y tengo un perro",
                                           "sim_phone_maria", "corr_setup", language="es", external_id="m1")
    await backend.submit_resident_response(MARIA, "SI", "sim_phone_maria", "corr_setup", language="es",
                                           external_id="m2")
    await backend.submit_resident_response(DAVID, "1", "sim_phone_david", "corr_setup", language="en",
                                           external_id="d1")
    await backend.submit_resident_response(DAVID, "yes", "sim_phone_david", "corr_setup", language="en",
                                           external_id="d2")

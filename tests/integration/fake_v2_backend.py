"""B's REAL app for A's integration tests (contract v2.1, in-memory Mongo).

All stand-ins are gone: B now serves every route the agents use (alerts, outreach,
matching, assignments, escalation, recovery, closures, routes, dashboard).
Never used outside tests and `scripts/dev_backend_v2.py` (DEV ONLY).
"""

from typing import Any

import httpx

from doorstep.api.app import create_app
from doorstep.workflows.backend_v2 import DEFAULT_NETWORK_TOKEN, DoorstepBackendV2

TOKEN = "change-me-local-demo-token"


def build_v2_app(db_path: str | None = ":memory:"):
    """B's real app. Returns (app, state); `state` is kept for API compatibility."""
    return create_app(db_path, seed=True), {}


def make_v2_backend(monkeypatch) -> tuple[DoorstepBackendV2, dict]:
    """In-process client (no network token) for tests. Returns (client, state).
    Use `network_client(client)` for the Volunteer Network agent."""
    monkeypatch.setenv("SIMULATION_MODE", "true")
    monkeypatch.setenv("AUTO_ESCALATION_ACK", "false")  # our Escalation agent acknowledges
    monkeypatch.delenv("DEMO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("NETWORK_AGENT_TOKEN", raising=False)
    app, state = build_v2_app()
    client = DoorstepBackendV2(base_url="http://backend.test", token=TOKEN, transport=httpx.ASGITransport(app=app))
    return client, state


def network_client(client: DoorstepBackendV2) -> DoorstepBackendV2:
    """Same backend, holding the network agent token (only the Volunteer Network agent gets this)."""
    return DoorstepBackendV2(base_url=client.base_url, token=client.token, transport=client._transport,
                             agent_token=DEFAULT_NETWORK_TOKEN)

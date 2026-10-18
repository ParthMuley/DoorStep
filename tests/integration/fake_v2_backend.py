"""B's REAL app for A's integration tests (contract v2.2, in-memory Mongo). B ships /link,
/unlink, /register, invites, approval, deadlines and maps (B8), so A's agents run on B's
real routes. ONE stand-in remains: `POST /routes/candidates` (asked of B in plan rev 6
§000.11) for drive-time ranking; delete it when B ships it. Never used outside tests and
`scripts/dev_backend_v2.py`.
"""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request

from doorstep.api.app import create_app
from doorstep.api.security import require_agent
from doorstep.workflows.backend_v2 import DEFAULT_NETWORK_TOKEN, DoorstepBackendV2

TOKEN = "change-me-local-demo-token"


def build_candidates_standin() -> APIRouter:
    r = APIRouter()

    @r.post("/routes/candidates", dependencies=[Depends(require_agent("ROUTE"))])
    async def candidates(request: Request):
        """Stand-in: pickup + each candidate volunteer's start + avoid areas, from B's own
        route-service helpers. Route token only; coordinates never appear in GET views."""
        body = await request.json()
        svc = request.app.state.service
        case = svc.store.get_case(body["case_id"])
        profile = svc.store.get_resident_profile(case.resident_id)
        out = []
        for vid in body.get("volunteer_ids", [])[:5]:
            found = svc.store.partners.locate_volunteer(vid)
            if found:
                out.append({"volunteer_id": vid, "lat": found[2].location.lat, "lon": found[2].location.lon})
        avoid = [{"kind": "ORDER_ZONE", "id": i, "geometry": a.__geo_interface__} for i, a in svc.routes._order_areas()]
        avoid += [{"kind": "OFFICIAL_CLOSURE", "id": i, "geometry": a.__geo_interface__}
                  for i, a in svc.routes._official_areas()]
        return {"schema_version": "2.0", "case_id": case.case_id, "candidates": out, "avoid_areas": avoid,
                "pickup": {"role": "PICKUP", "lat": profile.address.lat, "lon": profile.address.lon}}

    return r


def build_v2_app(db_path: str | None = ":memory:"):
    """B's real app + the /routes/candidates stand-in. Returns (app, state)."""
    app = create_app(db_path, seed=True)
    for route in reversed(build_candidates_standin().routes):
        app.router.routes.insert(0, route)
    return app, {}


def make_v2_backend(monkeypatch) -> tuple[DoorstepBackendV2, dict]:
    """In-process client (no network token) for tests. Returns (client, state).
    Use `network_client(client)` for the Volunteer Network agent."""
    monkeypatch.setenv("SIMULATION_MODE", "true")
    monkeypatch.setenv("AUTO_ESCALATION_ACK", "false")  # our Escalation agent acknowledges
    monkeypatch.setenv("DEMO_AUTH_TOKEN", "change-me-local-demo-token")  # .env must not leak in
    monkeypatch.setenv("NETWORK_AGENT_TOKEN", DEFAULT_NETWORK_TOKEN)
    app, state = build_v2_app()
    client = DoorstepBackendV2(base_url="http://backend.test", token=TOKEN, transport=httpx.ASGITransport(app=app))
    return client, state


def network_client(client: DoorstepBackendV2) -> DoorstepBackendV2:
    """Same backend, holding the network agent token (only the Volunteer Network agent gets this)."""
    return DoorstepBackendV2(base_url=client.base_url, token=client.token, transport=client._transport,
                             agent_token=DEFAULT_NETWORK_TOKEN)

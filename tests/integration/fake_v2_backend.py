"""B's REAL app for A's integration tests (contract v2.1, in-memory Mongo), plus ONE
stand-in for a rev 4 route B hasn't built yet: `POST /link` (contract v2.2 ask, plan
§0.4-0.5). Delete it when B ships `/link`; tests must keep passing against B.
Never used outside tests and `scripts/dev_backend_v2.py` (DEV ONLY).
"""

from typing import Any

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from doorstep.api.app import create_app
from doorstep.workflows.backend_v2 import DEFAULT_NETWORK_TOKEN, DoorstepBackendV2, doorstep_agent_token

TOKEN = "change-me-local-demo-token"


# Seeded one-time demo codes (public, plan §0.5 item 2). `sender_for_backend` maps a linked
# resident to the contact B accepts today; B's v2.2 will accept the linked address itself.
LINK_CODES = {
    "MARIA-4821": {"role": "RESIDENT", "resident_id": "resident_001", "case_id": "case_maria_001",
                   "display_name": "Maria (synthetic)", "sender_for_backend": "sim_phone_maria"},
    "DAVID-5932": {"role": "RESIDENT", "resident_id": "resident_002", "case_id": "case_david_002",
                   "display_name": "David (synthetic)", "sender_for_backend": "sim_phone_david"},
    "SARAH-7310": {"role": "VOLUNTEER", "volunteer_id": "volunteer_sarah", "org_id": "eastside_rides_demo",
                   "display_name": "Sarah (synthetic)"},
    "LEE-6624": {"role": "VOLUNTEER", "volunteer_id": "volunteer_lee", "org_id": "red_cross_demo",
                 "display_name": "Lee (synthetic)"},
    "COORD-1150": {"role": "COORDINATOR", "coordinator_id": "coordinator_demo",
                   "display_name": "Coordinator (synthetic)"},
}


def build_link_standin(spent: dict[str, str]) -> APIRouter:
    r = APIRouter()

    @r.post("/link")
    async def link(request: Request, x_agent_token: str | None = Header(default=None)):
        if x_agent_token != doorstep_agent_token():  # only the Doorstep agent may link (plan §0.5 item 1)
            return JSONResponse(status_code=401, content={"error": "UNAUTHORIZED", "detail": "Doorstep agent token"})
        body = await request.json()
        code, address = str(body.get("code", "")).upper(), body.get("asi_one_address")
        if code not in LINK_CODES:
            return JSONResponse(status_code=409, content={"error": "UNKNOWN_CODE", "detail": "unknown link code"})
        if code in spent:  # works once, even from the same address
            return JSONResponse(status_code=409, content={"error": "CODE_SPENT", "detail": "code already used"})
        spent[code] = address
        return {"schema_version": "2.0", "asi_one_address": address, **LINK_CODES[code]}

    return r


def build_v2_app(db_path: str | None = ":memory:"):
    """B's real app + the `/link` stand-in in front. Returns (app, state)."""
    app = create_app(db_path, seed=True)
    state: dict[str, Any] = {"spent_codes": {}}
    for route in reversed(build_link_standin(state["spent_codes"]).routes):
        app.router.routes.insert(0, route)
    return app, state


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

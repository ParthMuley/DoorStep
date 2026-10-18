"""B's REAL app for A's integration tests (contract v2.1, in-memory Mongo), plus ONE
stand-ins for routes B hasn't built yet: `POST /link` (rev 4, contract v2.2 ask),
`POST /register` (rev 5; it calls B's real registration routes) and
`POST /organizations/{org}/invites` (one-time volunteer invite codes for an org's bulk
roster import, scripts/import_volunteers.py). Delete them when B ships them; tests must
keep passing against B.
Never used outside tests and `scripts/dev_backend_v2.py` (DEV ONLY).
"""

from typing import Any

import secrets

import httpx
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from doorstep.api.app import create_app
from doorstep.api.security import require_demo_token
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


def build_link_standin(spent: dict[str, str], invites: dict[str, dict[str, Any]] | None = None) -> APIRouter:
    r = APIRouter()
    state_counter: list[str] = []
    invites = {} if invites is None else invites

    @r.post("/organizations/{org_id}/invites", dependencies=[Depends(require_demo_token)])
    async def invite(org_id: str, request: Request):
        """One-time code an org hands to a volunteer it imported; `LINK <code>` in ASI:One
        links that person's account to the existing volunteer record (no self-registration)."""
        body = await request.json()
        if not body.get("volunteer_id"):
            return JSONResponse(status_code=422, content={"error": "VALIDATION", "detail": "volunteer_id required"})
        prefix = org_id.split("_")[0].upper()[:12] or "ORG"
        code = f"{prefix}-{secrets.randbelow(9000) + 1000}"
        while code in LINK_CODES or code in invites:
            code = f"{prefix}-{secrets.randbelow(9000) + 1000}"
        invites[code] = {"role": "VOLUNTEER", "volunteer_id": body["volunteer_id"], "org_id": org_id,
                         "display_name": body.get("display_name") or body["volunteer_id"]}
        return JSONResponse(status_code=201, content={"schema_version": "2.0", "code": code, **invites[code]})

    @r.post("/link")
    async def link(request: Request, x_agent_token: str | None = Header(default=None)):
        if x_agent_token != doorstep_agent_token():  # only the Doorstep agent may link (plan §0.5 item 1)
            return JSONResponse(status_code=401, content={"error": "UNAUTHORIZED", "detail": "Doorstep agent token"})
        body = await request.json()
        code, address = str(body.get("code", "")).upper(), body.get("asi_one_address")
        entry = LINK_CODES.get(code) or invites.get(code)
        if entry is None:
            return JSONResponse(status_code=409, content={"error": "UNKNOWN_CODE", "detail": "unknown link code"})
        if code in spent:  # works once, even from the same address
            return JSONResponse(status_code=409, content={"error": "CODE_SPENT", "detail": "code already used"})
        spent[code] = address
        return {"schema_version": "2.0", "asi_one_address": address, **entry}

    @r.post("/register")
    async def register(request: Request, x_agent_token: str | None = Header(default=None)):
        """Stand-in for plan rev 5: uses B's REAL registration routes, then links the address."""
        if x_agent_token != doorstep_agent_token():
            return JSONResponse(status_code=401, content={"error": "UNAUTHORIZED", "detail": "Doorstep agent token"})
        body = await request.json()
        auth = {"Authorization": request.headers.get("authorization", "")}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app), base_url="http://in") as c:
            if body["role"] == "RESIDENT":
                res = await c.post("/residents", headers=auth, json={"resident": body["profile"]})
                if res.status_code >= 400:
                    return JSONResponse(status_code=res.status_code, content=res.json())
                rid = res.json()["resident_id"]
                return {"schema_version": "2.0", "role": "RESIDENT", "resident_id": rid, "case_id": f"case_{rid}",
                        "display_name": body["profile"]["name"], "sender_for_backend": body["profile"]["phone"]}
            lon, lat = body["profile"]["location"]["coordinates"]
            near = (await c.get("/regions/near", params={"lat": lat, "lon": lon})).json().get("regions", [])
            region = next((g for g in near if g.get("distance_km", 1) == 0), None)
            if region is None:
                return JSONResponse(status_code=409, content={"error": "NO_REGION",
                                                              "detail": "no partner region covers this location"})
            vid = f"volunteer_self_{len(spent) + len(state_counter) + 1:03d}"
            state_counter.append(vid)
            res = await c.post(f"/regions/{region['region_id']}/orgs/{body['org_id']}/volunteers", headers=auth,
                               json={"volunteer": {"volunteer_id": vid, **body["profile"]}})
            if res.status_code >= 400:
                return JSONResponse(status_code=res.status_code, content=res.json())
            return {"schema_version": "2.0", "role": "VOLUNTEER", "volunteer_id": vid, "org_id": body["org_id"],
                    "display_name": body["profile"]["name"], "approved": False}

    return r


def build_v2_app(db_path: str | None = ":memory:"):
    """B's real app + the `/link` stand-in in front. Returns (app, state)."""
    app = create_app(db_path, seed=True)
    state: dict[str, Any] = {"spent_codes": {}, "invites": {}}
    for route in reversed(build_link_standin(state["spent_codes"], state["invites"]).routes):
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

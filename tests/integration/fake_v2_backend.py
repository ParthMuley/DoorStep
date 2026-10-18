"""B's REAL app for A's integration tests, plus contract-shaped stand-ins ONLY for the
routes B hasn't built yet (contract v2.1 §5.9 closures; later §5.10 routes and §5.11
dashboard). Everything else (alerts, outreach, availability, matching, assignments,
escalation, recovery, cases) is B's real code.

Delete each stand-in when B's real route lands; tests must keep passing against B.
Never used outside tests and `scripts/dev_backend_v2.py` (DEV ONLY).
"""

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from doorstep.api.app import create_app
from doorstep.api.security import expected_token
from doorstep.workflows.backend_v2 import DEFAULT_NETWORK_TOKEN, DoorstepBackendV2

TOKEN = "change-me-local-demo-token"
V2 = "2.0"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(status: int, code: str, detail: str, reasons: list[str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"schema_version": V2, "error": code, "detail": detail,
                                                     "reasons": reasons or [], "correlation_id": None})


def build_standin_router(state: dict[str, Any]) -> APIRouter:
    r = APIRouter()

    def authed(authorization: str | None) -> bool:
        return authorization == f"Bearer {expected_token()}"  # same rule as B's real routes

    # ------------------------------------------------- road closures (contract §5.9)
    gazetteer = {"ridge ave": "seg_ridge_ave", "canyon rd": "seg_canyon_rd"}  # unmapped names never route

    @r.get("/demo/feeds/closures")
    def official_feed():
        return {"schema_version": V2, "closures": state["official_feed"]}

    @r.get("/demo/feeds/news")
    def news_feed():
        return {"schema_version": V2, "items": state["news_feed"]}

    @r.post("/demo/closures/trigger")
    async def closures_trigger(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        n = len(state["official_feed"]) + len(state["news_feed"]) + 1
        if body["action"] == "PUBLISH_OFFICIAL":
            state["official_feed"].append({"closure_id": f"off_{n:03d}", "issuing_authority":
                                           "SIMULATED_LA_COUNTY_PUBLIC_WORKS", "road_name": body["road_name"],
                                           "status": "CLOSED", "published_at": _now(), "expires_at": None})
        elif body["action"] == "PUBLISH_NEWS":
            state["news_feed"].append({"item_id": f"news_{n:03d}", "source_name": "Fictional Valley Gazette (DEMO)",
                                       "url": None, "published_at": _now(), "headline": body.get("headline", ""),
                                       "body": body.get("body", "")})
        return {"schema_version": V2, "action": body["action"]}

    @r.post("/closures/ingest")
    async def closures_ingest(request: Request, authorization: str | None = Header(default=None)):
        if not authed(authorization):
            return _err(401, "UNAUTHORIZED", "token")
        body = await request.json()
        source_type = body["source"]["source_type"]
        accepted, rejected = [], []
        for item in body["items"]:
            key = (body["source"]["source_id"], item["source_item_id"])
            if key in state["closure_keys"]:
                continue
            state["closure_keys"].add(key)
            cand = item.get("candidate") or {}
            road = cand.get("road_name", "")
            if not road:
                rejected.append({"source_item_id": item["source_item_id"], "reason": "NO_CANDIDATE"})
                continue
            # Deterministic state rules (B's job; the agent never sets state).
            st = ("OFFICIAL_CONFIRMED" if source_type == "OFFICIAL_SIMULATION" and cand.get("claimed_status") == "CLOSED"
                  else "UNVERIFIED_REPORT")
            segment = gazetteer.get(road.lower())
            same = [c for c in state["closures"] if c["segment_id"] and c["segment_id"] == segment]
            if any(c["claimed_status"] != cand.get("claimed_status") for c in same):
                st = "CONFLICTING"
                for c in same:
                    if c["state"] != "OFFICIAL_CONFIRMED":
                        c["state"] = "CONFLICTING"
            state["closure_seq"] += 1
            rec = {"closure_id": f"closure_{state['closure_seq']:03d}", "road_name": road, "segment_id": segment,
                   "state": st, "claimed_status": cand.get("claimed_status"),
                   "used_for_routing": st == "OFFICIAL_CONFIRMED" and segment is not None,
                   "sources": [{"source_type": source_type, "url": body["source"].get("url"),
                                "published_at": item.get("published_at"), "headline": item.get("headline"),
                                "extraction_method": item.get("extraction_method")}], "expires_at": None}
            state["closures"].append(rec)
            accepted.append({k: rec[k] for k in ("closure_id", "road_name", "state", "segment_id", "claimed_status",
                                                 "used_for_routing")} | {"source_type": source_type})
        return {"schema_version": V2, "accepted": accepted, "rejected": rejected,
                "new_official_closures": [a for a in accepted if a["state"] == "OFFICIAL_CONFIRMED"],
                "notify_coordinator": bool(accepted)}

    @r.get("/closures")
    def closures():
        return {"schema_version": V2, "closures": state["closures"],
                "note": "No report does not mean a road is open."}

    return r


def build_v2_app(db_path: str | None = ":memory:"):
    """B's real app + stand-ins for B's missing routes, inserted in front."""
    app = create_app(db_path, seed=True)
    state: dict[str, Any] = {
        "closures": [], "closure_keys": set(), "closure_seq": 0,
        "official_feed": [{"closure_id": "off_001", "issuing_authority": "SIMULATED_LA_COUNTY_PUBLIC_WORKS",
                           "road_name": "Ridge Ave", "status": "CLOSED", "published_at": "2026-10-17T20:05:00Z",
                           "expires_at": None}],
        "news_feed": [{"item_id": "news_001", "source_name": "Fictional Valley Gazette (DEMO)", "url": None,
                       "published_at": "2026-10-17T20:07:00Z",
                       "headline": "Residents report Canyon Rd blocked by debris (DEMO)",
                       "body": "Neighbors say a fallen tree stops traffic near Zone 3. (DEMO)"},
                      {"item_id": "news_002", "source_name": "Fictional Valley Gazette (DEMO)", "url": None,
                       "published_at": "2026-10-17T20:09:00Z", "headline": "Library bake sale raises funds (DEMO)",
                       "body": "Volunteers sold 300 cookies. (DEMO)"}]}
    for route in reversed(build_standin_router(state).routes):
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

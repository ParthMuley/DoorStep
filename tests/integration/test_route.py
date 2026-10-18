"""Route agent + HERE client. HERE is always mocked (no paid calls in tests)."""

import asyncio
from urllib.parse import parse_qs, urlparse

import flexpolyline
import httpx
import pytest
from shapely.geometry import LineString, shape
from uagents import Context

from doorstep.agents.route import RouteAgent
from doorstep.integrations.fetch_messages import RouteRequest, RouteResponse, utc_now
from doorstep.integrations.here_client import HereRouter, RouteRefused, avoid_param, enlarge_only
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend, network_client

ORDER_ZONE = {"type": "Polygon", "coordinates": [[[-118.1, 34.104], [-118.09, 34.104], [-118.09, 34.11],
                                                  [-118.1, 34.11], [-118.1, 34.104]]]}
SARAH, PICKUP, SHELTER = (34.0950, -118.1100), (34.1012, -118.0964), (34.0890, -118.0700)
# (lat, lng) legs. Good: passes the Canyon Rd report (caution), stays south of the order zone,
# detours south around Ridge Ave. Bad: cuts through the order zone.
GOOD = [[SARAH, (34.0910, -118.1035), PICKUP], [PICKUP, (34.0880, -118.0900), SHELTER]]
BAD = [[SARAH, (34.1070, -118.0950), PICKUP], [PICKUP, (34.0880, -118.0900), SHELTER]]


def here_response(legs, notices=None):
    return {"routes": [{"sections": [
        {"polyline": flexpolyline.encode(leg), "summary": {"length": 3000 + i * 1000, "duration": 420 + i * 300},
         "actions": [{"instruction": f"Leg {i + 1}: head toward stop {i + 1} (DEMO)."}],
         "notices": notices or []} for i, leg in enumerate(legs)]}]}


class FakeHere:
    """httpx MockTransport standing in for router.hereapi.com; records every call."""

    def __init__(self, body):
        self.body, self.calls = body, []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(parse_qs(urlparse(str(request.url)).query))
        return httpx.Response(200, json=self.body)


def test_enlarge_only_covers_and_respects_limits():
    zone = shape(ORDER_ZONE)
    out = enlarge_only(zone, max_vertices=8)
    assert out.covers(zone) and len(out.exterior.coords) - 1 <= 8
    param = avoid_param([{"kind": "ORDER_ZONE", "id": "a", "geometry": ORDER_ZONE}])
    first = param.split("polygon:")[1].split(";")[0].split(",")
    assert 34 < float(first[0]) < 35 and -119 < float(first[1]) < -118  # latitude first
    with pytest.raises(RouteRefused) as err:  # refuse instead of truncating
        avoid_param([{"kind": "ORDER_ZONE", "id": str(i), "geometry": ORDER_ZONE} for i in range(21)])
    assert err.value.reason == "TOO_MANY_AVOID_AREAS"


async def test_here_request_and_violation_detection():
    here = FakeHere(here_response(GOOD, notices=[{"code": "violatedBlockedRoad", "severity": "critical"}]))
    router = HereRouter(api_key="test-key", transport=here.transport)
    stops = [{"lat": la, "lon": lo} for la, lo in (SARAH, PICKUP, SHELTER)]
    route = await router.route(stops, [{"kind": "ORDER_ZONE", "id": "a", "geometry": ORDER_ZONE}])
    q = here.calls[0]
    assert q["via"] == ["34.101200,-118.096400"] and q["avoid[areas]"][0].startswith("polygon:")
    assert "polyline" in q["return"][0]
    assert route.violated and route.leg_durations_s == [420, 720] and route.coordinates[0] == (-118.11, 34.095)
    with pytest.raises(RouteRefused):
        await HereRouter(api_key="", transport=here.transport).route(stops, [])


async def accepted_assignment(backend) -> str:
    net = network_client(backend)
    await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE")
    res = await backend.ingest_alerts({"source_id": "SYNTHETIC_CALOES", "source_type": "OFFICIAL_SIMULATION",
                                       "url": "x", "fetched_at": utc_now()}, True, 200, None,
                                      await backend._request("GET", "/demo/feeds/caloes", "corr"), "k1", "corr")
    alert_id = res["outreach_orgs"][0]["alert_id"]
    await net.start_outreach(alert_id, f"{alert_id}:outreach", "corr")
    await net.record_availability(alert_id, "volunteer_sarah", "eastside_rides_demo", True, utc_now(), "a1", "corr")
    for i, t in enumerate(["1 Necesito ayuda, uso silla de ruedas y tengo un perro", "SI"]):
        await backend.submit_resident_response("case_maria_001", t, "sim_phone_maria", "corr", language="es",
                                               external_id=f"m{i}")
    match = (await backend.propose_match("case_maria_001", True, "case_maria_001:match:v1", "corr"))["match"]
    await net.accept_v2(match["assignment_id"], match["org_id"], "ACCEPTED", "acc", "corr",
                        volunteer_id=match["volunteer_id"])
    # Road reports, as the News agent would post them (B classifies).
    await backend.ingest_closures({"source_id": "SYNTHETIC_OFFICIAL_CLOSURES", "source_type": "OFFICIAL_SIMULATION",
                                   "url": "x", "fetched_at": utc_now()},
                                  [{"source_item_id": "off_001", "candidate": {"road_name": "Ridge Ave",
                                                                               "claimed_status": "CLOSED"}}], "c1", "corr")
    await backend.ingest_closures({"source_id": "SYNTHETIC_NEWS", "source_type": "NEWS", "url": "x",
                                   "fetched_at": utc_now()},
                                  [{"source_item_id": "news_001", "candidate": {"road_name": "Canyon Rd",
                                                                                "claimed_status": "CLOSED"}}], "c2", "corr")
    return match["assignment_id"]


async def plan_twice(monkeypatch, here_body, cap: str = "50"):
    monkeypatch.setenv("HERE_MAX_CALLS_PER_DAY", cap)
    backend, _ = make_v2_backend(monkeypatch)
    here = FakeHere(here_body)
    agent = make_agent("route")
    route = RouteAgent(lambda: backend, HereRouter(api_key="test-key", transport=here.transport))
    agent.include(route.protocol())
    driver = make_agent("doorstep_driver")
    out, done = {}, asyncio.Event()

    @driver.on_event("startup")
    async def go(ctx: Context):
        try:
            aid = await accepted_assignment(backend)
            req = RouteRequest(correlation_id="corr_route", created_at=utc_now(), case_id="case_maria_001",
                               assignment_id=aid, idempotency_key=f"{aid}:route:v1")
            for key in ("first", "again"):
                out[key], _ = await ctx.send_and_receive(agent.address, req, response_type=RouteResponse, timeout=15)
        finally:
            done.set()

    await run_until([driver, agent], done, timeout=45)
    return out, here


def test_fixture_geometry_is_what_we_think():
    good = LineString([(lo, la) for leg in GOOD for la, lo in leg])
    bad = LineString([(lo, la) for leg in BAD for la, lo in leg])
    assert not good.intersects(shape(ORDER_ZONE)) and bad.intersects(shape(ORDER_ZONE))


async def test_illustrative_route_avoids_blocks_and_flags_unverified_caution(monkeypatch):
    out, here = await plan_twice(monkeypatch, here_response(GOOD))
    r = out["first"]
    assert r.status == "ILLUSTRATIVE_ONLY" and r.label.startswith("ILLUSTRATIVE ROUTE ONLY")
    assert r.eta_pickup_minutes == 7  # first leg only: the volunteer's ETA to the resident
    kinds = {a["kind"] for a in r.avoided}
    assert kinds == {"ORDER_ZONE", "OFFICIAL_CLOSURE"}  # only order zones + official closures block
    assert r.cautions_on_path  # Canyon Rd (unverified) is a caution, not a block
    assert out["again"].route_preview_id == r.route_preview_id and len(here.calls) == 1  # cached: one paid call
    sent = here.calls[0]["avoid[areas]"][0]
    assert sent.count("polygon:") == 2


async def test_route_through_order_zone_is_refused_by_post_check(monkeypatch):
    out, _ = await plan_twice(monkeypatch, here_response(BAD))
    assert out["first"].status == "REFUSED"
    assert any(x.startswith("CROSSES:") for x in out["first"].reasons) and not out["first"].directions


async def test_no_route_found(monkeypatch):
    out, _ = await plan_twice(monkeypatch, {"routes": []})
    assert out["first"].status == "NO_ROUTE_CONFIRMED" and "NO_ROUTE_FOUND" in out["first"].reasons


async def test_daily_cap_blocks_paid_calls(monkeypatch):
    # One Bureau per test: a cancelled Bureau's shutdown cancels every task on the loop.
    out, here = await plan_twice(monkeypatch, here_response(GOOD), cap="0")
    assert out["first"].status == "NO_ROUTE_CONFIRMED" and here.calls == []  # cap reached: no HERE call
    assert "HERE_DAILY_CAP_REACHED" in out["first"].reasons

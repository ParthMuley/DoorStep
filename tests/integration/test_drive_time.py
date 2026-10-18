"""Drive-time ranking: Matching agent -> B preview -> Route agent (HERE mocked) -> B ranks the
eligible volunteers by road minutes (contract v2.2 §5.6). Eligibility never changes."""

import asyncio
from urllib.parse import parse_qs, urlparse

import flexpolyline
import httpx
from uagents import Context

from doorstep.agents.matching import build_matching_protocol
from doorstep.agents.route import RouteAgent
from doorstep.integrations.fetch_messages import MatchRequest, MatchResult, utc_now
from doorstep.integrations.here_client import HereRouter
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend, network_client

MINUTES = {"34.095000,-118.110000": 15, "34.070000,-118.140000": 4}  # Sarah's start is slow by road, Lee's fast


class TimedHere:
    def __init__(self):
        self.calls: list[str] = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        q = parse_qs(urlparse(str(request.url)).query)
        origin, dest = q["origin"][0], q["destination"][0]
        self.calls.append(origin)
        (la1, lo1), (la2, lo2) = (map(float, p.split(",")) for p in (origin, dest))
        minutes = MINUTES.get(origin, 30)
        return httpx.Response(200, json={"routes": [{"sections": [{
            "polyline": flexpolyline.encode([(la1, lo1), (34.085, -118.12), (la2, lo2)]),
            "summary": {"length": 5000, "duration": minutes * 60}, "actions": [], "notices": []}]}]})


async def ready_for_match(backend) -> None:
    net = network_client(backend)
    poll = (await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE", poll_now=True))["poll_result"]
    warning = next(a["alert_id"] for a in poll["new_alerts"] if a["status"] == "WARNING")
    await net.start_outreach(warning, f"{warning}:outreach", "corr")
    for vid, org in (("volunteer_sarah", "eastside_rides_demo"), ("volunteer_lee", "red_cross_demo")):
        await net.record_availability(warning, vid, org, True, utc_now(), f"{warning}:{vid}", "corr")
    for i, text in enumerate(["1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.", "SI"]):
        await backend.submit_resident_response("case_maria_001", text, "sim_phone_maria", "corr", language="es",
                                               external_id=f"sim_maria_{i}")


async def run_match(monkeypatch, ranking: str) -> tuple[MatchResult, TimedHere]:
    monkeypatch.setenv("DRIVE_TIME_RANKING", ranking)
    backend, _ = make_v2_backend(monkeypatch)
    here = TimedHere()
    matching, route, driver = make_agent("matching"), make_agent("route"), make_agent("driver")
    route.include(RouteAgent(lambda: backend, HereRouter(api_key="test-key", transport=here.transport)).protocol())
    matching.include(build_matching_protocol(lambda: backend, route_address=lambda: route.address))
    out, done = {}, asyncio.Event()

    @driver.on_event("startup")
    async def go(ctx: Context):
        try:
            await ready_for_match(backend)
            out["r"], _ = await ctx.send_and_receive(matching.address, MatchRequest(
                correlation_id="corr_drive", created_at=utc_now(), case_id="case_maria_001", create_proposal=True,
                idempotency_key="case_maria_001:match:v1"), response_type=MatchResult, timeout=40)
        finally:
            done.set()

    await run_until([driver, matching, route], done, timeout=60)
    return out["r"], here


async def test_road_time_reorders_eligible_volunteers(monkeypatch):
    r, here = await run_match(monkeypatch, "true")
    eligible = r.result["evaluation"]["volunteers"]["eligible"]
    assert r.ok and r.result["ranking"] == "DRIVE_TIME"
    assert [e["volunteer_id"] for e in eligible][:2] == ["volunteer_lee", "volunteer_sarah"]  # 4 min beats 15 min
    assert r.result["match"]["volunteer_id"] == "volunteer_lee"
    assert r.result["match"]["eta_estimate"]["minutes"] == 4  # ETA from the road time, not straight line
    assert sorted(here.calls) == sorted(MINUTES)  # one HERE call per candidate, start -> pickup


async def test_off_switch_keeps_distance_ranking(monkeypatch):
    r, here = await run_match(monkeypatch, "false")
    assert r.result.get("ranking", "DISTANCE") == "DISTANCE" and here.calls == []
    assert r.result["match"]["volunteer_id"] == "volunteer_sarah"  # closest in a straight line

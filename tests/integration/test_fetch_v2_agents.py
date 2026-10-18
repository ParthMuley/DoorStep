"""V2 agents over uAgents messaging (in-process Bureau, offline), against B's real app
plus the contract-shaped stand-ins in fake_v2_backend.py (team plan rev 3)."""

import asyncio
from typing import Any, Awaitable, Callable

from uagents import Agent, Context

from doorstep.agents.calamity_checker import CalamityChecker
from doorstep.agents.escalation import build_escalation_protocol
from doorstep.agents.matching import build_matching_protocol
from doorstep.agents.post_calamity import build_post_calamity_protocol
from doorstep.agents.volunteer_network import build_network_protocol
from doorstep.integrations.fetch_messages import (
    AcceptRequest,
    AcceptResponse,
    AlertNotification,
    ArrivalReport,
    EscalationAck,
    EscalationRequest,
    MatchRequest,
    MatchResult,
    OutreachRequest,
    OutreachResult,
    PickupReport,
    PollNow,
    RecoveryRequest,
    RecoveryResponse,
    ReportRequest,
    ReportUnavailable,
    utc_now,
)
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend

MARIA, DAVID = "case_maria_001", "case_david_002"


def m(**fields) -> dict[str, Any]:
    return {"correlation_id": "corr_v2_test", "created_at": utc_now(), **fields}


def network_agent(backend) -> Agent:
    agent = make_agent("volunteer_network")
    agent.include(build_network_protocol(lambda: backend))
    return agent


async def drive(agents: list[Agent], script: Callable[[Context, dict], Awaitable[None]]) -> dict:
    """Run `script` from a driver agent (playing the Doorstep agent) inside one Bureau.
    Backend calls must happen inside the script: the Bureau's shutdown cancels later awaits."""
    driver = make_agent("doorstep_driver")
    out: dict[str, Any] = {"driver": driver}
    done = asyncio.Event()

    @driver.on_event("startup")
    async def go(ctx: Context):
        try:
            await script(ctx, out)
        finally:
            done.set()

    await run_until([driver, *agents], done, timeout=45)
    return out


async def ask(ctx: Context, address: str, message, response_type):
    reply, status = await ctx.send_and_receive(address, message, response_type=response_type, timeout=15)
    assert reply is not None, f"no reply: {status}"
    return reply


async def ingest(backend) -> str:
    await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE")
    feed = await backend._request("GET", "/demo/feeds/caloes", "corr")
    res = await backend.ingest_alerts({"source_id": "SYNTHETIC_CALOES", "source_type": "OFFICIAL_SIMULATION",
                                       "url": "x", "fetched_at": utc_now()}, True, 200, None, feed, "k1", "corr")
    return res["outreach_orgs"][0]["alert_id"]


async def test_network_outreach_nearest_orgs_first(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    network = network_agent(backend)

    async def script(ctx, out):
        alert_id = await ingest(backend)
        out["result"] = await ask(ctx, network.address, OutreachRequest(
            **m(alert_id=alert_id, calamity_type="WILDFIRE", idempotency_key=f"{alert_id}:outreach")), OutreachResult)
        out["status"] = await backend.alert_outreach(alert_id, "corr")

    out = await drive([network], script)
    orgs = {o["org_id"]: o for o in out["result"].orgs}
    assert [o["org_id"] for o in out["result"].orgs] == ["neighbor_sedans_demo", "eastside_rides_demo",
                                                         "red_cross_demo"]  # nearest region first
    assert orgs["eastside_rides_demo"]["available"] == ["volunteer_sarah"]
    assert orgs["eastside_rides_demo"]["region_id"] == "la_county:zone_2"
    assert "volunteer_maya" in orgs["red_cross_demo"]["awaiting_reply"]  # NO_REPLY never = available
    assert {o["org_id"]: o["available"] for o in out["status"]["orgs"]}["red_cross_demo"] == 1


async def test_calamity_checker_ingests_and_notifies_once(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE")

    async def fetch(url):
        return True, 200, await backend._request("GET", "/demo/feeds/caloes", "corr"), None

    checker_agent, driver = make_agent("calamity"), make_agent("doorstep_driver")
    checker_agent.include(CalamityChecker(lambda: backend, fetch, coordinator_address=lambda: driver.address)
                          .protocol(3600))
    notifications: list[AlertNotification] = []
    done = asyncio.Event()

    @driver.on_message(AlertNotification)
    async def on_alert(ctx: Context, sender: str, msg: AlertNotification):
        notifications.append(msg)

    @driver.on_event("startup")
    async def go(ctx: Context):
        for _ in range(3):  # three identical polls -> one notification
            await ctx.send(checker_agent.address, PollNow(**m()))
            await asyncio.sleep(0.7)
        done.set()

    await run_until([driver, checker_agent], done)
    assert len(notifications) == 1
    note = notifications[0]
    assert {a["status"] for a in note.new_alerts} == {"WARNING", "ORDER"}
    assert {c["case_id"] for c in note.affected_cases} == {MARIA, DAVID}
    assert note.outreach_orgs[0]["org_id"] == "neighbor_sedans_demo"  # closest region first
    assert "agent_address" not in note.outreach_orgs[0]  # rev 3: no per-org agents


async def test_calamity_checker_reports_failed_fetch_and_backs_off(monkeypatch):
    backend, state = make_v2_backend(monkeypatch)

    async def broken(url):
        return False, None, None, "ConnectError"

    checker = CalamityChecker(lambda: backend, broken, coordinator_address=lambda: "unused")
    agent = make_agent("calamity")
    done, results = asyncio.Event(), []

    @agent.on_event("startup")
    async def go(ctx: Context):
        results.append(await checker.poll_once(ctx))
        results.append(await checker.poll_once(ctx))
        done.set()

    await run_until([agent], done)
    assert results[0]["feed_freshness"] == "UNKNOWN"  # B was told the fetch failed
    assert state["ingests"] == 2
    assert checker.failures == 2 and checker.skip_ticks == 1


async def test_maria_match_accept_pickup_arrival_via_network(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    network, matching = network_agent(backend), make_agent("matching")
    matching.include(build_matching_protocol(lambda: backend))

    async def script(ctx, out):
        alert_id = await ingest(backend)
        await ask(ctx, network.address, OutreachRequest(
            **m(alert_id=alert_id, calamity_type="WILDFIRE", idempotency_key=f"{alert_id}:outreach")), OutreachResult)
        res = await ask(ctx, matching.address, MatchRequest(**m(case_id=MARIA, create_proposal=True,
                                                                 idempotency_key=f"{MARIA}:match:v1")), MatchResult)
        out["match"] = res
        match = res.result["match"]
        aid = match["assignment_id"]
        out["vol"] = await ask(ctx, network.address, AcceptRequest(**m(
            case_id=MARIA, assignment_id=aid, org_id=match["org_id"], role="VOLUNTEER",
            volunteer_id=match["volunteer_id"], shared_with_volunteer=match["shared_with_volunteer"],
            idempotency_key=f"{aid}:accept:{match['volunteer_id']}")), AcceptResponse)
        out["shelter"] = await ask(ctx, network.address, AcceptRequest(**m(
            case_id=MARIA, assignment_id=aid, org_id=match["shelter_org_id"], role="SHELTER",
            site_id=match["site_id"], idempotency_key=f"{aid}:accept:{match['site_id']}")), AcceptResponse)
        out["pickup"] = await ask(ctx, network.address, ReportRequest(
            **m(kind="PICKUP", case_id=MARIA, assignment_id=aid)), {PickupReport, ReportUnavailable})
        out["arrival"] = await ask(ctx, network.address, ReportRequest(
            **m(kind="ARRIVAL", case_id=MARIA, assignment_id=aid)), {ArrivalReport, ReportUnavailable})
        out["unknown"] = await ask(ctx, network.address, ReportRequest(
            **m(kind="PICKUP", case_id=MARIA, assignment_id="assign_999")), {PickupReport, ReportUnavailable})
        ev = {"type": "VOLUNTEER_AND_RESIDENT_CONFIRMATION", "volunteer_confirmed": True, "resident_confirmed": True,
              "source": "SIMULATED", "report_id": out["pickup"].report_id}
        out["picked"] = await backend.pickup_v2(aid, ev, "p1", "corr")
        out["arrived"] = await backend.arrival_v2(aid, {
            "type": "SHELTER_CHECKIN", "shelter_org_id": "civic_shelter_demo", "site_id": "dest_center_a",
            "shelter_confirmed": True, "source": "SIMULATED", "report_id": out["arrival"].report_id}, "a1", "corr")

    out = await drive([network, matching], script)
    match = out["match"].result["match"]
    assert out["match"].ok and match["volunteer_id"] == "volunteer_sarah"
    rejected = out["match"].result["evaluation"]["volunteers"]["rejected"]
    assert any(r["volunteer_id"] == "volunteer_joe" and "NO_WHEELCHAIR_SPACE" in r["reason_codes"] for r in rejected)
    assert out["vol"].decision == "ACCEPTED" and out["vol"].backend["resident_status"] == "PROVIDER_ACCEPTED"
    assert "pickup_details" not in out["vol"].backend  # pickup point never travels back to Doorstep
    assert out["shelter"].decision == "ACCEPTED"
    assert isinstance(out["pickup"], PickupReport) and out["pickup"].volunteer_id == "volunteer_sarah"
    assert isinstance(out["arrival"], ArrivalReport) and out["arrival"].site_id == "dest_center_a"
    assert isinstance(out["unknown"], ReportUnavailable)
    assert out["picked"]["resident_status"] == "PICKUP_CONFIRMED"
    assert out["arrived"]["resident_status"] == "ARRIVAL_CONFIRMED" and out["arrived"]["map"]["color"] == "green"


async def test_volunteer_decline_names_next_alternate_and_is_idempotent(monkeypatch):
    monkeypatch.setenv("DECLINE_VOLUNTEERS", "volunteer_sarah")
    backend, _ = make_v2_backend(monkeypatch)
    network = network_agent(backend)

    async def script(ctx, out):
        alert_id = await ingest(backend)
        await ask(ctx, network.address, OutreachRequest(
            **m(alert_id=alert_id, calamity_type="WILDFIRE", idempotency_key=f"{alert_id}:outreach")), OutreachResult)
        proposal = await backend.propose_match(MARIA, True, f"{MARIA}:match:v1", "corr")
        aid = proposal["match"]["assignment_id"]
        req = AcceptRequest(**m(case_id=MARIA, assignment_id=aid, org_id="eastside_rides_demo", role="VOLUNTEER",
                                volunteer_id="volunteer_sarah", idempotency_key=f"{aid}:accept:volunteer_sarah"))
        out["first"] = await ask(ctx, network.address, req, AcceptResponse)
        out["again"] = await ask(ctx, network.address, req, AcceptResponse)
        out["next"] = await backend.propose_match(MARIA, True, f"{MARIA}:match:v2", "corr",
                                                  select_volunteer_id="volunteer_lee")

    out = await drive([network], script)
    assert out["first"].decision == "DECLINED"
    assert out["first"].backend["next_alternate"] == {"org_id": "red_cross_demo", "volunteer_id": "volunteer_lee"}
    assert out["again"].created_at == out["first"].created_at  # duplicate request -> same stored answer
    assert out["next"]["match"]["volunteer_id"] == "volunteer_lee"


async def test_wrong_org_for_volunteer_is_refused(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    network = network_agent(backend)

    async def script(ctx, out):
        alert_id = await ingest(backend)
        await ask(ctx, network.address, OutreachRequest(
            **m(alert_id=alert_id, calamity_type="WILDFIRE", idempotency_key=f"{alert_id}:outreach")), OutreachResult)
        aid = (await backend.propose_match(MARIA, True, f"{MARIA}:match:v1", "corr"))["match"]["assignment_id"]
        out["wrong"] = await ask(ctx, network.address, AcceptRequest(**m(
            case_id=MARIA, assignment_id=aid, org_id="red_cross_demo", role="VOLUNTEER",
            volunteer_id="volunteer_sarah", idempotency_key=f"{aid}:accept:wrong")), AcceptResponse)

    out = await drive([network], script)
    assert out["wrong"].decision == "ERROR" and out["wrong"].error["status"] == 403


async def test_david_escalation_is_receipt_only(monkeypatch):
    escalation, matching = make_agent("escalation"), make_agent("matching")
    backend, _ = make_v2_backend(monkeypatch)
    escalation.include(build_escalation_protocol(lambda: backend))
    matching.include(build_matching_protocol(lambda: backend))

    async def script(ctx, out):
        out["match"] = await ask(ctx, matching.address, MatchRequest(
            **m(case_id=DAVID, create_proposal=True, idempotency_key=f"{DAVID}:match:v1")), MatchResult)
        esc = await backend.escalate(DAVID, "ACTIVE_EVACUATION_ORDER_ZONE", f"{DAVID}:escalation:v1", "corr")
        out["ack"] = await ask(ctx, escalation.address, EscalationRequest(**m(
            escalation_id=esc["escalation_id"], case_id=DAVID,
            case_summary_for_recipient=esc["case_summary_for_recipient"],
            idempotency_key=f"{esc['escalation_id']}:request")), EscalationAck)

    out = await drive([escalation, matching], script)
    assert out["match"].result["match"] is None and out["match"].result["no_match_reason"] == "ORDER_ZONE"
    assert out["ack"].status == "ACKNOWLEDGED_REQUEST_ONLY"
    assert out["ack"].assistance_confirmed is False


async def test_post_calamity_referrals_answered_via_network(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    network, post = network_agent(backend), make_agent("post_calamity")
    post.include(build_post_calamity_protocol(lambda: backend, network_address=lambda: network.address))

    async def script(ctx, out):
        out["ok"] = await ask(ctx, post.address, RecoveryRequest(**m(
            case_id=MARIA, help_types=["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE", "SUPPLIES"],
            share_recovery_needs=True, granted_by="RESIDENT", idempotency_key=f"{MARIA}:recovery:v1")),
            RecoveryResponse)
        out["no_consent"] = await ask(ctx, post.address, RecoveryRequest(**m(
            case_id=MARIA, help_types=["TEMPORARY_HOUSING"], share_recovery_needs=False, granted_by="RESIDENT",
            idempotency_key=f"{MARIA}:recovery:v2")), RecoveryResponse)

    out = await drive([post, network], script)
    ok = out["ok"]
    assert {(r["help_type"], r["org_id"], r["status"]) for r in ok.referrals} == {
        ("TEMPORARY_HOUSING", "recovery_housing_demo", "ACCEPTED"), ("INSURANCE_GUIDANCE", "red_cross_demo", "ACCEPTED")}
    assert ok.unmatched_help_types == ["SUPPLIES"] and ok.housing_secured is False
    assert all("shared_payload" not in r for r in ok.referrals)
    assert out["no_consent"].ok is False and out["no_consent"].error["code"] == "CONSENT_MISSING"

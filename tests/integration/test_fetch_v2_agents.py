"""V2 agents over uAgents messaging (in-process Bureau, offline), against B's real app
plus the contract-shaped stand-ins in fake_v2_backend.py."""

import asyncio
from typing import Any, Awaitable, Callable

from uagents import Agent, Context

from doorstep.agents.calamity_checker import CalamityChecker
from doorstep.agents.escalation import build_escalation_protocol
from doorstep.agents.matching import build_matching_protocol
from doorstep.agents.organization import build_org_protocol
from doorstep.agents.post_calamity import build_post_calamity_protocol
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
ORGS = ["eastside_rides_demo", "red_cross_demo", "civic_shelter_demo", "recovery_housing_demo"]


def org_agents() -> dict[str, Agent]:
    return {org: make_agent(f"org_{org}") for org in ORGS}


def wire_orgs(agents: dict[str, Agent], backend) -> None:
    for org, agent in agents.items():
        agent.include(build_org_protocol(org, lambda: backend))


def m(**fields) -> dict[str, Any]:
    return {"correlation_id": "corr_v2_test", "created_at": utc_now(), **fields}


async def drive(agents: list[Agent], script: Callable[[Context, dict], Awaitable[None]]) -> dict:
    """Run `script` from a driver agent (playing the Doorstep agent) inside one Bureau."""
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


async def test_org_outreach_reads_and_writes_real_volunteer_records(monkeypatch):
    orgs = org_agents()
    backend, _ = make_v2_backend(monkeypatch, {o: a.address for o, a in orgs.items()})
    wire_orgs(orgs, backend)

    async def script(ctx, out):
        for org in ("eastside_rides_demo", "red_cross_demo"):
            out[org] = await ask(ctx, orgs[org].address, OutreachRequest(
                **m(alert_id="alert_001", calamity_type="WILDFIRE", idempotency_key=f"alert_001:outreach:{org}")),
                OutreachResult)
        # The answer really landed in B's org DB (B's real endpoint), scoped to that org.
        out["vols"] = (await backend.org_volunteers("eastside_rides_demo", "corr", alert_id="alert_001"))["volunteers"]

    out = await drive(list(orgs.values()), script)
    east, rc = out["eastside_rides_demo"], out["red_cross_demo"]
    assert east.asked == ["volunteer_sarah"] and east.available == ["volunteer_sarah"]
    assert set(rc.available) == {"volunteer_lee"} and "volunteer_maya" in rc.awaiting_reply  # NO_REPLY never = available
    assert out["vols"][0]["availability"]["state"] == "AVAILABLE"


async def test_calamity_checker_ingests_and_notifies_once(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE")

    async def fetch(url):
        return True, 200, await backend._request("GET", "/demo/feeds/caloes", "corr"), None

    checker_agent = make_agent("calamity")
    notifications: list[AlertNotification] = []
    driver_box: dict = {}

    # Protocols must be included before the Bureau starts, so build the checker up front.
    checker = CalamityChecker(lambda: backend, fetch, coordinator_address=lambda: driver_box["addr"])
    checker_agent.include(checker.protocol(3600))
    driver = make_agent("doorstep_driver")
    driver_box["addr"] = driver.address
    done = asyncio.Event()

    @driver.on_message(AlertNotification)
    async def on_alert(ctx: Context, sender: str, msg: AlertNotification):
        notifications.append(msg)

    @driver.on_event("startup")
    async def go(ctx: Context):
        for _ in range(3):
            await ctx.send(checker_agent.address, PollNow(**m()))
            await asyncio.sleep(0.7)
        done.set()

    await run_until([driver, checker_agent], done)
    assert len(notifications) == 1
    note = notifications[0]
    assert {a["status"] for a in note.new_alerts} == {"WARNING", "ORDER"}
    assert {c["case_id"] for c in note.affected_cases} == {MARIA, DAVID}
    assert [o["org_id"] for o in note.outreach_orgs][0] == "neighbor_sedans_demo"  # closest first


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


async def ingest_and_outreach(backend, orgs_to_ask=("eastside_rides_demo", "red_cross_demo")):
    await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE")
    feed = await backend._request("GET", "/demo/feeds/caloes", "corr")
    res = await backend.ingest_alerts({"source_id": "SYNTHETIC_CALOES", "source_type": "OFFICIAL_SIMULATION",
                                       "url": "x", "fetched_at": utc_now()}, True, 200, None, feed, "k1", "corr")
    alert_id = res["outreach_orgs"][0]["alert_id"]
    for org in orgs_to_ask:
        await backend.start_outreach(org, alert_id, f"{alert_id}:outreach:{org}", "corr")
    await backend.record_availability("eastside_rides_demo", "volunteer_sarah", alert_id, True, utc_now(), "a1", "corr")
    await backend.record_availability("red_cross_demo", "volunteer_lee", alert_id, True, utc_now(), "a2", "corr")
    return alert_id


async def test_maria_match_accept_pickup_arrival_over_agents(monkeypatch):
    orgs = org_agents()
    matching = make_agent("matching")
    backend, _ = make_v2_backend(monkeypatch, {o: a.address for o, a in orgs.items()})
    wire_orgs(orgs, backend)
    matching.include(build_matching_protocol(lambda: backend))
    await ingest_and_outreach(backend)

    async def script(ctx, out):
        res = await ask(ctx, matching.address, MatchRequest(**m(case_id=MARIA, create_proposal=True,
                                                                 idempotency_key=f"{MARIA}:match:v1")), MatchResult)
        out["match"] = res
        match = res.result["match"]
        aid = match["assignment_id"]
        out["vol"] = await ask(ctx, match["org_agent_address"], AcceptRequest(**m(
            case_id=MARIA, assignment_id=aid, org_id=match["org_id"], role="VOLUNTEER",
            volunteer_id=match["volunteer_id"], shared_with_volunteer=match["shared_with_volunteer"],
            idempotency_key=f"{aid}:accept:{match['volunteer_id']}")), AcceptResponse)
        out["shelter"] = await ask(ctx, match["shelter_agent_address"], AcceptRequest(**m(
            case_id=MARIA, assignment_id=aid, org_id=match["shelter_org_id"], role="SHELTER",
            site_id=match["site_id"], idempotency_key=f"{aid}:accept:{match['site_id']}")), AcceptResponse)
        out["pickup"] = await ask(ctx, match["org_agent_address"], ReportRequest(
            **m(kind="PICKUP", case_id=MARIA, assignment_id=aid)), {PickupReport, ReportUnavailable})
        out["wrong"] = await ask(ctx, match["shelter_agent_address"], ReportRequest(
            **m(kind="PICKUP", case_id=MARIA, assignment_id=aid)), {PickupReport, ReportUnavailable})
        out["arrival"] = await ask(ctx, match["shelter_agent_address"], ReportRequest(
            **m(kind="ARRIVAL", case_id=MARIA, assignment_id=aid)), {ArrivalReport, ReportUnavailable})
        out["aid"] = aid

    out = await drive([matching, *orgs.values()], script)
    match = out["match"].result["match"]
    assert out["match"].ok and match["volunteer_id"] == "volunteer_sarah"
    rejected = out["match"].result["evaluation"]["volunteers"]["rejected"]
    assert any(r["volunteer_id"] == "volunteer_joe" and "NO_WHEELCHAIR_SPACE" in r["reason_codes"] for r in rejected)
    assert out["vol"].decision == "ACCEPTED" and out["vol"].backend["resident_status"] == "PROVIDER_ACCEPTED"
    assert "pickup_details" not in out["vol"].backend  # pickup point never travels back to Doorstep
    assert out["shelter"].decision == "ACCEPTED"
    assert isinstance(out["pickup"], PickupReport) and out["pickup"].volunteer_id == "volunteer_sarah"
    assert isinstance(out["wrong"], ReportUnavailable)
    assert isinstance(out["arrival"], ArrivalReport) and out["arrival"].site_id == "dest_center_a"
    # Doorstep forwards the reports to B; acceptance != pickup != arrival.
    ev = {"type": "VOLUNTEER_AND_RESIDENT_CONFIRMATION", "volunteer_confirmed": True, "resident_confirmed": True,
          "source": "SIMULATED", "report_id": out["pickup"].report_id}
    assert (await backend.pickup_v2(out["aid"], ev, "p1", "corr"))["resident_status"] == "PICKUP_CONFIRMED"
    arr = await backend.arrival_v2(out["aid"], {"type": "SHELTER_CHECKIN", "shelter_org_id": "civic_shelter_demo",
                                                "site_id": "dest_center_a", "shelter_confirmed": True,
                                                "source": "SIMULATED", "report_id": out["arrival"].report_id},
                                   "a1", "corr")
    assert arr["resident_status"] == "ARRIVAL_CONFIRMED" and arr["map"]["color"] == "green"


async def test_volunteer_decline_names_next_alternate_and_is_idempotent(monkeypatch):
    monkeypatch.setenv("DECLINE_VOLUNTEERS", "volunteer_sarah")
    orgs = org_agents()
    backend, _ = make_v2_backend(monkeypatch, {o: a.address for o, a in orgs.items()})
    wire_orgs(orgs, backend)
    await ingest_and_outreach(backend)
    proposal = await backend.propose_match(MARIA, True, f"{MARIA}:match:v1", "corr")
    aid = proposal["match"]["assignment_id"]

    async def script(ctx, out):
        req = AcceptRequest(**m(case_id=MARIA, assignment_id=aid, org_id="eastside_rides_demo", role="VOLUNTEER",
                                volunteer_id="volunteer_sarah", idempotency_key=f"{aid}:accept:volunteer_sarah"))
        out["first"] = await ask(ctx, orgs["eastside_rides_demo"].address, req, AcceptResponse)
        out["again"] = await ask(ctx, orgs["eastside_rides_demo"].address, req, AcceptResponse)

    out = await drive(list(orgs.values()), script)
    assert out["first"].decision == "DECLINED"
    assert out["first"].backend["next_alternate"] == {"org_id": "red_cross_demo", "volunteer_id": "volunteer_lee"}
    assert out["again"].created_at == out["first"].created_at  # duplicate request -> same stored answer
    nxt = await backend.propose_match(MARIA, True, f"{MARIA}:match:v2", "corr", select_volunteer_id="volunteer_lee")
    assert nxt["match"]["volunteer_id"] == "volunteer_lee"


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


async def test_post_calamity_referrals_to_recovery_org_agents(monkeypatch):
    orgs = org_agents()
    post = make_agent("post_calamity")
    backend, _ = make_v2_backend(monkeypatch, {o: a.address for o, a in orgs.items()})
    wire_orgs(orgs, backend)
    post.include(build_post_calamity_protocol(lambda: backend))

    async def script(ctx, out):
        out["ok"] = await ask(ctx, post.address, RecoveryRequest(**m(
            case_id=MARIA, help_types=["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE", "SUPPLIES"],
            share_recovery_needs=True, granted_by="RESIDENT", idempotency_key=f"{MARIA}:recovery:v1")),
            RecoveryResponse)
        out["no_consent"] = await ask(ctx, post.address, RecoveryRequest(**m(
            case_id=MARIA, help_types=["TEMPORARY_HOUSING"], share_recovery_needs=False, granted_by="RESIDENT",
            idempotency_key=f"{MARIA}:recovery:v2")), RecoveryResponse)

    out = await drive([post, *orgs.values()], script)
    ok = out["ok"]
    assert {(r["help_type"], r["org_id"], r["status"]) for r in ok.referrals} == {
        ("TEMPORARY_HOUSING", "recovery_housing_demo", "ACCEPTED"), ("INSURANCE_GUIDANCE", "red_cross_demo", "ACCEPTED")}
    assert ok.unmatched_help_types == ["SUPPLIES"] and ok.housing_secured is False
    assert all("shared_payload" not in r for r in ok.referrals)
    assert out["no_consent"].ok is False and out["no_consent"].error["code"] == "CONSENT_MISSING"

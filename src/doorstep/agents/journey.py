"""Doorstep V2 journey: the steps the Doorstep agent runs between ASI:One, the other
agents (over Fetch.ai) and Developer B's backend. Every step returns cards whose status
words come from B or from the other agents' replies; nothing here decides eligibility,
zones, consent or safety.

Flow: start check -> (Calamity agent) AlertNotification -> push Alert card + outreach
via the Volunteer Network agent (orgs nearest the zone) -> push Outreach card -> resident reply (simulated) -> Matching agent ->
Match card -> approve -> Volunteer Network forwards volunteer + shelter acceptance -> Help on the way ->
pickup report -> arrival report (green) -> recovery consent -> Post-Calamity agent.
David: no match (order zone) -> escalate -> Escalation agent (receipt only).

State is in memory for now (one coordinator process); the thin LangGraph step adds
durable per-case state later.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from uagents import Context

from doorstep.integrations.asi_cards import (
    Card,
    case_card,
    escalation_card,
    help_on_the_way_card,
    info_card,
    match_card,
    recovery_consent_card,
    text_message,
)
from doorstep.integrations.fetch_messages import (
    AcceptRequest,
    AcceptResponse,
    AlertNotification,
    ClosureNotification,
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
    RouteRequest,
    RouteResponse,
    utc_now,
)
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

AGENT_TIMEOUT_SECONDS = 25
NAMES = {"case_maria_001": "Maria (synthetic)", "case_david_002": "David (synthetic)"}
SIM_REPLIES = {  # simulated resident SMS (B's simulator); labeled SIMULATED in replies
    "case_maria_001": ("sim_phone_maria", "es", ["1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.", "SI"]),
    "case_david_002": ("sim_phone_david", "en", ["1 I need help, I use a wheelchair.", "YES"]),
}
DEFAULT_HELP_TYPES = ["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"]
Reply = str | Card | list[str | Card]


@dataclass
class CaseJourney:
    proposal: dict[str, Any] | None = None
    attempt: int = 1
    accepted: dict[str, Any] | None = None
    shelter_accepted: bool = False
    steps: dict[str, str | None] = field(default_factory=lambda: {
        "REQUESTED": None, "PROVIDER_ACCEPTED": None, "PICKUP_CONFIRMED": None, "ARRIVAL_CONFIRMED": None})
    map: dict[str, str] = field(default_factory=lambda: {"color": "red", "label": "Assistance needed"})
    next_step: str | None = None


class Journey:
    def __init__(self, get_backend: Callable[[], DoorstepBackendV2], address_for: Callable[[str], str]):
        self.get_backend, self.address_for = get_backend, address_for
        self.subscribers: set[str] = set()
        self.last_alert: AlertNotification | None = None
        self.outreach: OutreachResult | None = None
        self.cases: dict[str, CaseJourney] = {}

    def case(self, case_id: str) -> CaseJourney:
        return self.cases.setdefault(case_id, CaseJourney())

    async def ask(self, ctx: Context, address: str, message, response_type):
        reply, status = await ctx.send_and_receive(address, message, response_type=response_type,
                                                   timeout=AGENT_TIMEOUT_SECONDS)
        if reply is None:
            ctx.logger.warning(f"[{message.correlation_id}] no reply from {address[:16]}...: {status.detail}")
        return reply

    @staticmethod
    def refused(err: Exception) -> str:
        if isinstance(err, BackendError):
            return f"The case service refused this step ({err.code}: {err.detail}). Nothing was changed."
        return "The case service is unreachable, so I can't show verified status. Nothing was changed."

    # ------------------------------------------------------------ alert flow
    async def start_check(self, ctx: Context, sender: str, corr: str) -> Reply:
        self.subscribers.add(sender)
        try:
            await self.get_backend().trigger_alert("ISSUE", corr, preset="ZONE_3_WILDFIRE")
        except (BackendError, OSError) as err:
            return self.refused(err)
        await ctx.send(self.address_for("CALAMITY"), PollNow(correlation_id=corr, created_at=utc_now()))
        await ctx.send(self.address_for("NEWS"), PollNow(correlation_id=corr, created_at=utc_now()))
        return ("Simulated official wildfire alert issued for Zone 3 (demo control). The Calamity Checker and "
                "News agents are polling their feeds now; alert, volunteer-outreach and road-condition cards "
                "will appear here automatically.")

    async def on_alert(self, ctx: Context, msg: AlertNotification) -> None:
        """Push the alert to everyone watching, then ask the Volunteer Network agent to reach
        the volunteers of the organizations nearest the zone (B picks them by location)."""
        self.last_alert = msg
        await self.push(ctx, self.alert_card(msg))
        if not msg.outreach_orgs:
            return
        alert_id = msg.outreach_orgs[0]["alert_id"]
        calamity = next((a["calamity_type"] for a in msg.new_alerts if a["alert_id"] == alert_id), "UNKNOWN")
        result = await self.ask(ctx, self.address_for("NETWORK"), OutreachRequest(
            correlation_id=msg.correlation_id, created_at=utc_now(), alert_id=alert_id, calamity_type=calamity,
            idempotency_key=f"{alert_id}:outreach"), OutreachResult)
        self.outreach = result
        await self.push(ctx, self.outreach_card(result))

    # -------------------------------------------------------- road closures
    async def on_closures(self, ctx: Context, msg: ClosureNotification) -> None:
        try:
            records = (await self.get_backend().closures(msg.correlation_id)).get("closures", [])
        except (BackendError, OSError):
            records = msg.new_records
        await self.push(ctx, self.road_card(records))

    async def road_conditions(self, corr: str) -> Reply:
        try:
            records = (await self.get_backend().closures(corr)).get("closures", [])
        except (BackendError, OSError) as err:
            return self.refused(err)
        return self.road_card(records)

    @staticmethod
    def road_card(records: list[dict[str, Any]]) -> Card:
        groups = [("OFFICIAL_CONFIRMED", "Official (blocks illustrative routes)"),
                  ("UNVERIFIED_REPORT", "Unverified report (caution only)"),
                  ("CONFLICTING", "Conflicting reports (caution)"), ("EXPIRED", "Expired")]
        rows = []
        for state, label in groups:
            for c in (r for r in records if r.get("state") == state):
                src = (c.get("sources") or [{}])[0]
                where = c.get("segment_id") or "not on the demo road map (never used for routing)"
                rows.append((f"{c['road_name']} · {label}",
                             f"claims {c.get('claimed_status')} · {src.get('source_type')} · "
                             f"{src.get('published_at') or 'time unknown'} · {where}"))
        if not rows:
            rows.append(("Reports", "none received yet"))
        rows.append(("Note", "No report does not mean a road is open. Never a safety assessment."))
        return info_card("Road conditions", rows, "Road conditions from the News agent (simulated feeds):",
                         "News agent · SYNTHETIC official closures + SYNTHETIC news")

    async def push(self, ctx: Context, card: Card | str) -> None:
        for user in list(self.subscribers):
            await ctx.send(user, card.to_message() if isinstance(card, Card) else text_message(card))

    @staticmethod
    def alert_card(msg: AlertNotification) -> Card:
        rows = [(f"{a['zone_id']}", f"{a['status']} · {a['calamity_type']}") for a in msg.new_alerts]
        rows += [(f"Resident {c['case_id']}", f"in {c['zone_status']} zone") for c in msg.affected_cases]
        rows += [("Feed", f"{msg.feed_freshness} (ingest {msg.ingest_id})"),
                 ("Next", "Check-ins sent to residents in the zones (simulated SMS); asking nearby organizations' "
                          "volunteers if they're available.")]
        return info_card("Alert detected", rows, "Calamity Checker detected a simulated official alert:",
                         "Calamity Checker agent · SYNTHETIC_CALOES")

    @staticmethod
    def outreach_card(result: OutreachResult | None) -> Card:
        if result is None:
            rows = [("Volunteer Network", "no answer yet; no volunteer is treated as available")]
        else:
            rows = [(f"{o['org_id']} · {', '.join(o.get('region_ids') or []) or '-'} ({o.get('distance_km')} km)",
                     f"asked {len(o.get('asked', []))} · available {len(o.get('available', []))} · "
                     f"waiting {len(o.get('awaiting_reply', []))} · unavailable {len(o.get('unavailable', []))}")
                    if "error" not in o else ("Outreach", f"failed: {o['error'].get('code')}")
                    for o in result.orgs]
        return info_card("Volunteer outreach", rows,
                         "Volunteer Network asked the volunteers of the organizations nearest the zone:",
                         "Volunteer Network agent · simulated volunteer replies")

    # -------------------------------------------------------- resident reply
    async def simulate_reply(self, case_id: str, corr: str) -> Reply:
        sender, language, texts = SIM_REPLIES[case_id]
        backend, last = self.get_backend(), {}
        try:
            for i, text in enumerate(texts):
                last = await backend.submit_resident_response(case_id, text, sender, corr, language=language,
                                                              external_id=f"sim_{case_id}_{i}")
        except (BackendError, OSError) as err:
            return self.refused(err)
        j = self.case(case_id)
        j.steps["REQUESTED"] = utc_now() if last.get("needs_confirmed") else None
        return (f"Simulated SMS from {NAMES[case_id]}: \"{texts[0]}\" then \"{texts[-1]}\". "
                f"Needs confirmed: {last.get('needs_confirmed')}. Resident status: {last.get('resident_status')}.")

    # -------------------------------------------------------------- matching
    async def find_match(self, ctx: Context, case_id: str, corr: str, select: str | None = None) -> Reply:
        j = self.case(case_id)
        result = await self.ask(ctx, self.address_for("MATCHING"), MatchRequest(
            correlation_id=corr, created_at=utc_now(), case_id=case_id, create_proposal=True,
            select_volunteer_id=select, idempotency_key=f"{case_id}:match:v{j.attempt}"), MatchResult)
        if result is None:
            return "The Matching agent did not answer. Nothing was proposed; ask again in a moment."
        if not result.ok:
            return f"Matching refused: {result.error.get('code')} ({result.error.get('detail')}). Nothing was proposed."
        r = result.result
        vols, shelters = r["evaluation"]["volunteers"], r["evaluation"]["shelters"]
        chosen = [{"label": f"{e['volunteer_id']} · {e.get('vehicle_type', '')} · {e['org_id']} · {e.get('distance_km')} km",
                   "reasons": e["reason_codes"]} for e in vols["eligible"]]
        rejected = [{"label": f"{x['volunteer_id']} · {x['org_id']}", "reasons": x["reason_codes"]}
                    for x in vols["rejected"]]
        top_shelter = shelters["eligible"][0] if shelters["eligible"] else None
        shelter = {"label": f"{top_shelter['site_id']} · {top_shelter['org_id']}",
                   "reasons": top_shelter["reason_codes"]} if top_shelter else None
        match = r.get("match")
        j.proposal = match
        if r.get("escalation_required"):
            j.map, j.next_step = {"color": "black", "label": "Coordinator attention"}, "Escalate (simulated)."
        return match_card(case_id=case_id, display_name=NAMES.get(case_id, case_id), chosen=chosen,
                          rejected=rejected, shelter=shelter, assignment_id=match and match["assignment_id"],
                          escalation_required=bool(r.get("escalation_required")),
                          no_match_reason=r.get("no_match_reason"))

    # ------------------------------------------------------------ acceptance
    async def approve(self, ctx: Context, case_id: str, corr: str) -> Reply:
        j = self.case(case_id)
        p = j.proposal
        if not p:
            return f"There is no proposed arrangement for {NAMES.get(case_id, case_id)} yet. Ask me to find a match first."
        aid = p["assignment_id"]
        vol_req = AcceptRequest(correlation_id=corr, created_at=utc_now(), case_id=case_id, assignment_id=aid,
                                org_id=p["org_id"], role="VOLUNTEER", volunteer_id=p["volunteer_id"],
                                shared_with_volunteer=p.get("shared_with_volunteer", {}),
                                idempotency_key=f"{aid}:accept:{p['volunteer_id']}")
        shelter_req = AcceptRequest(correlation_id=corr, created_at=utc_now(), case_id=case_id, assignment_id=aid,
                                    org_id=p["shelter_org_id"], role="SHELTER", site_id=p["site_id"],
                                    idempotency_key=f"{aid}:accept:{p['site_id']}")
        # Sequential on purpose: uagents send_and_receive matches replies by (sender, destination,
        # session), so two concurrent requests to the same agent from one handler collide.
        network = self.address_for("NETWORK")
        vol = await self.ask(ctx, network, vol_req, AcceptResponse)
        shelter = await self.ask(ctx, network, shelter_req, AcceptResponse)
        if vol is None or vol.decision == "ERROR":
            return ("The volunteer did not confirm (via the Volunteer Network). Help is NOT on the way yet; "
                    "I will not resend "
                    "blindly. Ask for status in a moment.")
        if vol.decision == "DECLINED":
            nxt = vol.backend.get("next_alternate")
            j.proposal, j.attempt = None, j.attempt + 1
            if not nxt:
                j.map = {"color": "black", "label": "Coordinator attention"}
                return f"{p['volunteer_id']} declined (simulated). No other eligible volunteer; the case needs the coordinator."
            card = await self.find_match(ctx, case_id, corr, select=nxt["volunteer_id"])
            if isinstance(card, Card):
                card.narration = f"{p['volunteer_id']} declined (simulated), no pressure. Next eligible volunteer: " + card.narration
            return card
        j.accepted = {"assignment_id": aid, "org_id": p["org_id"], "volunteer_id": p["volunteer_id"]}
        j.shelter_accepted = bool(shelter and shelter.decision == "ACCEPTED")
        j.steps["PROVIDER_ACCEPTED"] = utc_now()
        j.map = {"color": "yellow", "label": "Volunteer accepted (not yet picked up)"}
        j.next_step = "Awaiting pickup confirmation." if j.shelter_accepted else "Shelter has not confirmed a bed yet."
        route = await self.ask(ctx, self.address_for("ROUTE"), RouteRequest(
            correlation_id=corr, created_at=utc_now(), case_id=case_id, assignment_id=aid,
            idempotency_key=f"{aid}:route:v1"), RouteResponse)
        eta = vol.backend.get("eta") or {}
        eta_minutes = route.eta_pickup_minutes if route and route.status == "ILLUSTRATIVE_ONLY" else eta.get("minutes")
        help_card = help_on_the_way_card(
            case_id=case_id, display_name=NAMES.get(case_id, case_id),
            volunteer_label=f"{p['volunteer_id']} ({p.get('vehicle_type', '')}, {p['org_id']})",
            eta_minutes=eta_minutes, eta_label=eta.get("label") or "Illustrative estimate, not a guarantee",
            route_status=route.status if route else "no route yet")
        return [help_card, self.route_card(case_id, p["volunteer_id"], route)]

    @staticmethod
    def route_card(case_id: str, volunteer_id: str, r: RouteResponse | None) -> Card:
        """Volunteer's route (shown to the coordinator until rev 4 role linking)."""
        title = f"Route for {volunteer_id} · {NAMES.get(case_id, case_id)}"
        if r is None:
            return info_card(title, [("Status", "NO_ROUTE_CONFIRMED (the Route agent did not answer)")],
                             "No route yet:", "Route agent")
        if r.status != "ILLUSTRATIVE_ONLY":
            rows = [("Status", f"{r.status} - no route shown"), ("Why", ", ".join(r.reasons) or "-"),
                    ("Next", "Coordinator decides; never treat this as a safe route.")]
            return info_card(title, rows, "Route refused (volunteer is not given a route):", "Route agent · HERE")
        rows = [("Status", r.status), ("Distance", f"{(r.distance_m or 0) / 1000:.1f} km"),
                ("ETA to pickup", f"about {r.eta_pickup_minutes} min (estimate, not a guarantee)"),
                ("Total time", f"about {round((r.duration_s or 0) / 60)} min")]
        rows += [("Avoided", f"{a['kind']} {a['id']}") for a in r.avoided] or [("Avoided", "no active blocks")]
        rows += [("Caution", f"{c}: unverified report on the path") for c in r.cautions_on_path]
        rows += [(f"Step {i}", d) for i, d in enumerate(r.directions, 1)]
        rows.append(("Note", r.label))
        return info_card(title, rows, "Illustrative route sent to the volunteer (simulated):", "Route agent · HERE")

    # -------------------------------------------------------- pickup/arrival
    async def confirm_pickup(self, ctx: Context, case_id: str, corr: str) -> Reply:
        j = self.case(case_id)
        if not j.accepted:
            return "Pickup can't be confirmed: no volunteer has accepted this case. Nothing was changed."
        a = j.accepted
        report = await self.ask(ctx, self.address_for("NETWORK"), ReportRequest(
            correlation_id=corr, created_at=utc_now(), kind="PICKUP", case_id=case_id,
            assignment_id=a["assignment_id"]), {PickupReport, ReportUnavailable})
        if not isinstance(report, PickupReport):
            return "No pickup report came back from the Volunteer Network. Pickup is NOT confirmed."
        evidence = {"type": "VOLUNTEER_AND_RESIDENT_CONFIRMATION", "volunteer_confirmed": True,
                    "resident_confirmed": True, "caregiver_confirmed": False, "code_verified": report.code_verified,
                    "source": "SIMULATED", "report_id": report.report_id,
                    "confirmations": [{"party": "volunteer", "party_id": report.volunteer_id}]}
        try:
            res = await self.get_backend().pickup_v2(a["assignment_id"], evidence, f"{a['assignment_id']}:pickup", corr)
        except (BackendError, OSError) as err:
            return self.refused(err)
        j.steps["PICKUP_CONFIRMED"] = res.get("confirmed_pickup_at")
        j.map, j.next_step = await self.case_map(case_id, corr, res), "Awaiting arrival check-in at the shelter."
        return self.journey_card(case_id, res.get("resident_status"),
                                 note="Pickup confirmed by the volunteer's report + simulated resident confirmation.")

    async def confirm_arrival(self, ctx: Context, case_id: str, corr: str) -> Reply:
        j = self.case(case_id)
        if not j.accepted or not j.steps["PICKUP_CONFIRMED"]:
            return "Arrival can't be confirmed before a confirmed pickup. Nothing was changed."
        a = j.accepted
        report = await self.ask(ctx, self.address_for("NETWORK"), ReportRequest(
            correlation_id=corr, created_at=utc_now(), kind="ARRIVAL", case_id=case_id,
            assignment_id=a["assignment_id"]), {ArrivalReport, ReportUnavailable})
        if not isinstance(report, ArrivalReport):
            return "The shelter did not report a check-in. Arrival is NOT confirmed."
        evidence = {"type": "SHELTER_CHECKIN", "shelter_org_id": report.shelter_org_id, "site_id": report.site_id,
                    "shelter_confirmed": True, "source": "SIMULATED", "report_id": report.report_id}
        try:
            res = await self.get_backend().arrival_v2(a["assignment_id"], evidence, f"{a['assignment_id']}:arrival",
                                                      corr)
        except (BackendError, OSError) as err:
            return self.refused(err)
        j.steps["ARRIVAL_CONFIRMED"] = res.get("confirmed_arrival_at")
        j.map, j.next_step = await self.case_map(case_id, corr, res), "Ask whether the resident wants further help."
        return [self.journey_card(case_id, res.get("resident_status"), note="Arrival confirmed by shelter check-in."),
                recovery_consent_card(case_id=case_id, display_name=NAMES.get(case_id, case_id),
                                      help_types=DEFAULT_HELP_TYPES)]

    async def case_map(self, case_id: str, corr: str, step_response: dict[str, Any]) -> dict[str, str]:
        """Status color/label always from B: the step response if it has one, else the case record."""
        if step_response.get("map"):
            return step_response["map"]
        try:
            return (await self.get_backend().get_case_status(case_id, corr)).get("map") or self.case(case_id).map
        except (BackendError, OSError):
            return self.case(case_id).map

    def journey_card(self, case_id: str, resident_status: str | None, note: str) -> Card:
        j = self.case(case_id)
        card = case_card(case_id=case_id, display_name=NAMES.get(case_id, case_id), map_color=j.map.get("color"),
                         map_label=j.map.get("label") or resident_status, zone_status=None,
                         steps=[(k, v is not None, v) for k, v in j.steps.items()], next_step=j.next_step,
                         communication_status=None)
        card.narration = f"{note} Resident status: {resident_status}. " + card.narration
        return card

    # -------------------------------------------------------------- recovery
    async def recovery(self, ctx: Context, case_id: str, consent: bool, corr: str) -> Reply:
        if not consent:
            return f"Understood: nothing is shared with recovery organizations for {NAMES.get(case_id, case_id)}."
        res = await self.ask(ctx, self.address_for("POSTCALAMITY"), RecoveryRequest(
            correlation_id=corr, created_at=utc_now(), case_id=case_id, help_types=DEFAULT_HELP_TYPES,
            share_recovery_needs=True, granted_by="RESIDENT", idempotency_key=f"{case_id}:recovery:v1"),
            RecoveryResponse)
        if res is None:
            return "The Post-Calamity agent did not answer. No referral is confirmed."
        if not res.ok:
            return f"Recovery referral refused: {res.error.get('code')}. Nothing was shared."
        rows = [(r["help_type"].replace("_", " ").title(), f"{r['org_id']}: {r['status']}") for r in res.referrals]
        rows += [(h.replace("_", " ").title(), "no matching organization") for h in res.unmatched_help_types]
        rows.append(("Housing secured", "yes" if res.housing_secured else "no (a referral is a request, not housing)"))
        return info_card(f"Further help · {NAMES.get(case_id, case_id)}", rows,
                         "Post-Calamity agent sent consent-scoped referrals:", "Post-Calamity agent")

    # ------------------------------------------------------------ escalation
    async def escalate(self, ctx: Context, case_id: str, corr: str) -> Reply:
        try:
            esc = await self.get_backend().escalate(case_id, "ACTIVE_EVACUATION_ORDER_ZONE",
                                                    f"{case_id}:escalation:v1", corr)
        except (BackendError, OSError) as err:
            return self.refused(err)
        ack = await self.ask(ctx, self.address_for("ESCALATION"), EscalationRequest(
            correlation_id=corr, created_at=utc_now(), escalation_id=esc["escalation_id"], case_id=case_id,
            case_summary_for_recipient=esc.get("case_summary_for_recipient", {}),
            idempotency_key=f"{esc['escalation_id']}:request"), EscalationAck)
        j = self.case(case_id)
        j.map = {"color": "black", "label": "Coordinator attention"}
        return escalation_card(case_id=case_id, display_name=NAMES.get(case_id, case_id), reason=esc["reason"],
                               status=ack.status if ack else "NO_ACKNOWLEDGMENT",
                               next_step=esc.get("next_step"))


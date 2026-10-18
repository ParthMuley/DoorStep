"""Doorstep V2 journey: the steps the Doorstep agent runs between ASI:One, the other
agents (over Fetch.ai) and Developer B's backend. Every step returns cards whose status
words come from B or from the other agents' replies; nothing here decides eligibility,
zones, consent or safety.

Flow: start check -> (Calamity agent) AlertNotification -> push Alert card + outreach
via the Volunteer Network agent (orgs nearest the zone) -> push Outreach card -> resident reply (simulated) -> Matching agent ->
Match card -> approve -> Volunteer Network forwards volunteer + shelter acceptance -> Help on the way ->
pickup report -> arrival report (green) -> recovery consent -> Post-Calamity agent.
David: no match (order zone) -> escalate -> Escalation agent (receipt only).

Rev 4: residents and volunteers who linked their ASI:One account get their own cards
(check-in, needs confirmation, availability, assignment + route, pickup) and answer by
clicking; anyone not linked falls back to the labeled simulator/personas.

State is in memory for now (one coordinator process); the thin LangGraph step adds
durable per-case state later.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from uagents import Context

from doorstep.integrations.asi_cards import (
    Card,
    assignment_card,
    availability_card,
    case_card,
    checkin_card,
    escalation_card,
    help_on_the_way_card,
    info_card,
    match_card,
    needs_confirm_card,
    recovery_consent_card,
    text_message,
    trip_card,
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
    VolunteerAnswer,
    VolunteerAnswerAck,
    utc_now,
)
from doorstep.agents.links import Link, LinkRegistry
from doorstep.integrations.outbox import Outbox
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

AGENT_TIMEOUT_SECONDS = 25
NAMES = {"case_maria_001": "Maria (synthetic)", "case_david_002": "David (synthetic)"}
SIM_REPLIES = {  # simulated resident SMS (B's simulator); labeled SIMULATED in replies
    "case_maria_001": ("sim_phone_maria", "es", ["1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.", "SI"]),
    "case_david_002": ("sim_phone_david", "en", ["1 I need help, I use a wheelchair.", "YES"]),
}
DEFAULT_HELP_TYPES = ["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"]
CHECKIN_TEXT = {"need_help": "1", "have_plan": "2", "already_left": "3", "call_me": "4"}
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
    route: Any = None  # the RouteResponse sent to the volunteer
    help: dict[str, Any] = field(default_factory=dict)  # volunteer label + ETA + shelter for the trip card


class Journey:
    def __init__(self, get_backend: Callable[[], DoorstepBackendV2], address_for: Callable[[str], str]):
        self.get_backend, self.address_for = get_backend, address_for
        self.subscribers: set[str] = set()
        self.last_alert: AlertNotification | None = None
        self.outreach: OutreachResult | None = None
        self.cases: dict[str, CaseJourney] = {}
        self.people = LinkRegistry()  # rev 4: linked ASI:One accounts
        self.outbox = Outbox()  # one ASI:One message per burst per person
        self.pickup_confirms: dict[str, set[str]] = {}
        self.current_alert: dict[str, str] = {}

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
        for c in msg.affected_cases:  # rev 4: linked residents get their own check-in card
            resident = self.people.resident_for_case(c["case_id"])
            if resident:
                if not resident.language:  # linked by code: the case (created by this alert) has the profile language
                    try:
                        view = await self.get_backend().get_case_status(c["case_id"], msg.correlation_id)
                        resident.language = (view.get("case") or view).get("preferred_language")
                    except (BackendError, OSError):
                        pass
                await self.send_to(ctx, resident.address, checkin_card(
                    case_id=c["case_id"], display_name=resident.display_name, zone_status=c.get("zone_status"),
                    language=resident.language))
        if not msg.outreach_orgs:
            return
        alert_id = msg.outreach_orgs[0]["alert_id"]
        calamity = next((a["calamity_type"] for a in msg.new_alerts if a["alert_id"] == alert_id), "UNKNOWN")
        self.current_alert = {"alert_id": alert_id, "calamity": calamity}
        live = [l.volunteer_id for l in self.people.by_role("VOLUNTEER") if l.volunteer_id]
        result = await self.ask(ctx, self.address_for("NETWORK"), OutreachRequest(
            correlation_id=msg.correlation_id, created_at=utc_now(), alert_id=alert_id, calamity_type=calamity,
            idempotency_key=f"{alert_id}:outreach", live_volunteers=live), OutreachResult)
        self.outreach = result
        await self.push(ctx, self.outreach_card(result))
        for org in (result.orgs if result else []):  # rev 4: linked volunteers answer themselves
            for vid in org.get("awaiting_reply", []):
                volunteer = self.people.volunteer(vid)
                if volunteer:
                    await self.send_to(ctx, volunteer.address, availability_card(
                        alert_id=alert_id, volunteer_id=vid, org_id=org["org_id"], calamity=calamity))

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
        """Operations updates for coordinators (and unlinked demo users)."""
        for user in list(self.subscribers):
            await self.send_to(ctx, user, card)

    async def send_to(self, ctx: Context, address: str, *parts: Card | str) -> None:
        await self.outbox.add(ctx, address, *parts)

    # ---------------------------------------------- rev 4: people's own answers
    async def resident_checkin(self, ctx: Context, link: Link, answer: str, corr: str) -> Reply:
        if answer not in CHECKIN_TEXT:
            return "Please choose one of the check-in options. Nothing was changed."
        try:
            res = await self.get_backend().resident_reply(link.case_id, CHECKIN_TEXT[answer], link.backend_sender,
                                                          corr, external_id=f"{link.case_id}:checkin:{answer}")
        except (BackendError, OSError) as err:
            return self.refused(err)
        await self.push(ctx, f"{link.display_name} answered the check-in in their own chat: "
                             f"{res.get('intent')} (resident status {res.get('resident_status')}).")
        reply: list[str | Card] = [f"Thank you. Recorded: {res.get('intent')}. This is a simulation; "
                                   "in a real emergency call 911."]
        if res.get("confirmation_question") and not res.get("needs_confirmed"):
            reply.append(needs_confirm_card(case_id=link.case_id, question=res["confirmation_question"]))
        return reply

    async def resident_confirm_needs(self, ctx: Context, link: Link, yes: bool, corr: str) -> Reply:
        try:
            res = await self.get_backend().resident_reply(link.case_id, "YES" if yes else "NO", link.backend_sender,
                                                          corr, external_id=f"{link.case_id}:confirm:{yes}")
        except (BackendError, OSError) as err:
            return self.refused(err)
        if res.get("needs_confirmed"):
            self.case(link.case_id).steps["REQUESTED"] = utc_now()
        await self.push(ctx, f"{link.display_name} {'confirmed' if yes else 'did not confirm'} their needs in "
                             f"their own chat (needs confirmed: {res.get('needs_confirmed')}).")
        return (f"Thank you. Needs confirmed: {res.get('needs_confirmed')}. A coordinator is looking for a "
                "volunteer; nothing is arranged until a volunteer accepts." if yes else
                "Understood. A coordinator will follow up with you. Nothing was arranged.")

    async def volunteer_availability(self, ctx: Context, link: Link, sel: dict[str, Any], corr: str) -> Reply:
        if sel.get("volunteer_id", link.volunteer_id) != link.volunteer_id:
            return "That request was for another volunteer. Nothing was changed."
        alert_id = sel.get("alert_id") or self.current_alert.get("alert_id")
        if not alert_id:
            return "There is no active simulated alert to answer. Nothing was changed."
        ack = await self.ask(ctx, self.address_for("NETWORK"), VolunteerAnswer(
            correlation_id=corr, created_at=utc_now(), alert_id=alert_id, volunteer_id=link.volunteer_id,
            org_id=sel.get("org_id") or link.org_id, available=bool(sel.get("available")),
            idempotency_key=f"{alert_id}:avail:{link.volunteer_id}", sender=link.address), VolunteerAnswerAck)
        if ack is None or ack.error:
            return f"Your answer could not be recorded ({(ack.error or {}).get('code') if ack else 'no reply'})."
        await self.push(ctx, f"{link.display_name} answered in their own chat: {ack.availability}.")
        return f"Thanks, recorded as {ack.availability}. Being available is not an assignment."

    async def volunteer_decides(self, ctx: Context, link: Link, case_id: str, accept: bool, corr: str) -> Reply:
        p = self.case(case_id).proposal
        if not p or p["volunteer_id"] != link.volunteer_id:
            return "This assignment is no longer waiting for you. Nothing was changed."
        outcome = await self._decide(ctx, case_id, corr, p, "ACCEPTED" if accept else "DECLINED")
        if not outcome["accepted"]:
            for part in outcome["coordinator"]:
                await self.push(ctx, part)
            return "Thanks for letting us know; declining is always okay. The coordinator will ask someone else."
        resident = self.people.resident_for_case(case_id)
        for part in outcome["coordinator"]:
            await self.push(ctx, part)
        if resident:
            await self.send_to(ctx, resident.address, self.trip_card(case_id, resident, "Help is on the way (simulated)."))
        return self.trip_card(case_id, link, "You accepted. Your illustrative route is on the card")


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
        chosen = [{"label": f"{e['volunteer_id']} · {e.get('vehicle_type', '')} · {e['org_id']} · {e.get('distance_km')} km"
                            + (f" · {e['drive_minutes']:g} min by road" if e.get("drive_minutes") is not None else ""),
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
        volunteer = self.people.volunteer(p["volunteer_id"])
        if volunteer:  # rev 4: the volunteer decides in their own ASI:One chat
            eta = (p.get("eta_estimate") or {}).get("minutes")
            await self.send_to(ctx, volunteer.address, assignment_card(
                case_id=case_id, assignment_id=p["assignment_id"], volunteer_id=p["volunteer_id"],
                shared=p.get("shared_with_volunteer", {}), shelter=f"{p.get('site_id')} ({p.get('shelter_org_id')})",
                eta_minutes=eta))
            return (f"Asked {p['volunteer_id']} in their own ASI:One chat. Nothing is confirmed until they accept; "
                    "you'll get an update here.")
        outcome = await self._decide(ctx, case_id, corr, p, None)
        if not outcome["accepted"]:
            return outcome["coordinator"][0] if len(outcome["coordinator"]) == 1 else outcome["coordinator"]
        resident = self.people.resident_for_case(case_id)
        if resident:  # a linked resident hears it in their own chat even when the volunteer is simulated
            await self.send_to(ctx, resident.address, self.trip_card(case_id, resident, "Help is on the way (simulated)."))
        return [outcome["help"], outcome["route"]]

    async def _decide(self, ctx: Context, case_id: str, corr: str, p: dict[str, Any],
                      decision: str | None) -> dict[str, Any]:
        """Forward the volunteer's decision (their click, or the simulated persona when
        `decision` is None) and the shelter's, then plan the route. Returns the cards per
        audience: coordinator updates, the resident's help card, the volunteer's route."""
        j = self.case(case_id)
        aid = p["assignment_id"]
        vol_req = AcceptRequest(correlation_id=corr, created_at=utc_now(), case_id=case_id, assignment_id=aid,
                                org_id=p["org_id"], role="VOLUNTEER", volunteer_id=p["volunteer_id"],
                                shared_with_volunteer=p.get("shared_with_volunteer", {}),
                                idempotency_key=f"{aid}:accept:{p['volunteer_id']}", decision=decision)
        shelter_req = AcceptRequest(correlation_id=corr, created_at=utc_now(), case_id=case_id, assignment_id=aid,
                                    org_id=p["shelter_org_id"], role="SHELTER", site_id=p["site_id"],
                                    idempotency_key=f"{aid}:accept:{p['site_id']}")
        # Sequential on purpose: uagents send_and_receive matches replies by (sender, destination,
        # session), so two concurrent requests to the same agent from one handler collide.
        network = self.address_for("NETWORK")
        vol = await self.ask(ctx, network, vol_req, AcceptResponse)
        shelter = await self.ask(ctx, network, shelter_req, AcceptResponse)
        how = "in their own chat" if decision else "(simulated)"
        if vol is None or vol.decision == "ERROR":
            return {"accepted": False, "coordinator": [
                "The volunteer's answer could not be recorded (via the Volunteer Network). Help is NOT on the way "
                "yet; I will not resend blindly. Ask for status in a moment."]}
        if vol.decision == "DECLINED":
            nxt = vol.backend.get("next_alternate")
            j.proposal, j.attempt = None, j.attempt + 1
            if not nxt:
                j.map = {"color": "black", "label": "Coordinator attention"}
                return {"accepted": False, "coordinator": [
                    f"{p['volunteer_id']} declined {how}. No other eligible volunteer; the case needs the coordinator."]}
            card = await self.find_match(ctx, case_id, corr, select=nxt["volunteer_id"])
            if isinstance(card, Card):
                card.narration = f"{p['volunteer_id']} declined {how}, no pressure. Next eligible volunteer: " + card.narration
            return {"accepted": False, "coordinator": [card]}
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
        j.route = route
        j.help = {"volunteer": f"{p['volunteer_id']} ({p.get('vehicle_type', '')}, {p['org_id']})",
                  "eta": eta_minutes, "shelter": f"{p.get('site_id')} ({p.get('shelter_org_id')})"}
        help_card = help_on_the_way_card(
            case_id=case_id, display_name=NAMES.get(case_id, case_id),
            volunteer_label=f"{p['volunteer_id']} ({p.get('vehicle_type', '')}, {p['org_id']})",
            eta_minutes=eta_minutes, eta_label=eta.get("label") or "Illustrative estimate, not a guarantee",
            route_status=route.status if route else "no route yet")
        return {"accepted": True, "help": help_card, "route": self.route_card(case_id, p["volunteer_id"], route),
                "coordinator": [help_card, self.route_card(case_id, p["volunteer_id"], route)]}

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
    async def confirm_pickup(self, ctx: Context, case_id: str, corr: str, by: Link | None = None) -> Reply:
        """Pickup needs the volunteer AND the resident. A linked person confirms only in their
        own chat; an unlinked one is simulated (labeled) when the coordinator asks."""
        j = self.case(case_id)
        if not j.accepted:
            return "Pickup can't be confirmed: no volunteer has accepted this case. Nothing was changed."
        a = j.accepted
        if j.steps["PICKUP_CONFIRMED"]:
            return self.journey_card(case_id, "PICKUP_CONFIRMED", note="Pickup was already confirmed.")
        got = self.pickup_confirms.setdefault(case_id, set())
        volunteer = self.people.volunteer(a["volunteer_id"])
        resident = self.people.resident_for_case(case_id)
        if by is not None and by.role == "VOLUNTEER":
            if by.volunteer_id != a["volunteer_id"]:
                return "You are not the volunteer on this assignment. Nothing was changed."
            got.add("volunteer")
        elif by is not None and by.role == "RESIDENT":
            got.add("resident")
        report_id = f"pickup_{a['assignment_id']}"
        if "volunteer" not in got and volunteer is None and (by is None or by.role == "COORDINATOR"):
            report = await self.ask(ctx, self.address_for("NETWORK"), ReportRequest(
                correlation_id=corr, created_at=utc_now(), kind="PICKUP", case_id=case_id,
                assignment_id=a["assignment_id"]), {PickupReport, ReportUnavailable})
            if isinstance(report, PickupReport):
                got.add("volunteer_simulated")
                report_id = report.report_id
        if "resident" not in got and resident is None and (by is None or by.role == "COORDINATOR"):
            got.add("resident_simulated")
        waiting = [who for who, keys in (("the volunteer", {"volunteer", "volunteer_simulated"}),
                                         ("the resident", {"resident", "resident_simulated"})) if not got & keys]
        if waiting:
            await self.push(ctx, f"Pickup for {NAMES.get(case_id, case_id)}: waiting for {' and '.join(waiting)} "
                                 "to confirm in their own chat. Pickup is NOT confirmed yet.")
            if by is not None and by.role != "COORDINATOR":  # both people see the same snapshot
                other = resident if by.role == "VOLUNTEER" else volunteer
                if other is not None:
                    await self.send_to(ctx, other.address, self.trip_card(case_id, other, "The other person confirmed pickup."))
                return self.trip_card(case_id, by, f"Recorded. Waiting for {' and '.join(waiting)} to confirm too; "
                                                   "pickup is not confirmed until both do.")
            return (f"Recorded. Waiting for {' and '.join(waiting)} to confirm too; pickup is not confirmed until "
                    "both do.")
        live = {"volunteer", "resident"} <= got
        confirmations = [{"party": "volunteer", "party_id": a["volunteer_id"]}]
        if "resident" in got and resident is not None:
            confirmations.append({"party": "resident", "party_id": resident.person_id})
        evidence = {"type": "VOLUNTEER_AND_RESIDENT_CONFIRMATION", "volunteer_confirmed": True,
                    "resident_confirmed": True, "caregiver_confirmed": False, "code_verified": False,
                    "source": "ASI_ONE" if live else "SIMULATED", "report_id": report_id,
                    "confirmations": confirmations}
        try:
            res = await self.get_backend().pickup_v2(a["assignment_id"], evidence, f"{a['assignment_id']}:pickup", corr)
        except (BackendError, OSError) as err:
            return self.refused(err)
        j.steps["PICKUP_CONFIRMED"] = res.get("confirmed_pickup_at")
        j.map, j.next_step = await self.case_map(case_id, corr, res), "Awaiting arrival check-in at the shelter."
        how = ("Pickup confirmed by both the volunteer and the resident in their own chats." if live else
               "Pickup confirmed (" + ", ".join(sorted(x.replace("_", " ") for x in got)) + ").")
        card = self.journey_card(case_id, res.get("resident_status"), note=how)
        for person in (volunteer, resident):
            if person is not None and person is not by:
                await self.send_to(ctx, person.address, self.trip_card(case_id, person, how))
        if by is not None and by.role != "COORDINATOR":  # the person who confirmed last gets their own card
            await self.push(ctx, card)
            return self.trip_card(case_id, by, how)
        return card

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
        card = self.journey_card(case_id, res.get("resident_status"), note="Arrival confirmed by shelter check-in.")
        consent = recovery_consent_card(case_id=case_id, display_name=NAMES.get(case_id, case_id),
                                        help_types=DEFAULT_HELP_TYPES)
        resident = self.people.resident_for_case(case_id)
        volunteer = self.people.volunteer(a["volunteer_id"])
        note = "Arrival confirmed by shelter check-in."
        if volunteer:
            await self.send_to(ctx, volunteer.address, self.trip_card(case_id, volunteer, note))
        if resident:  # consent is the resident's to give, in their own chat
            await self.send_to(ctx, resident.address, self.trip_card(case_id, resident, note), consent)
            return [card, f"Asked {resident.display_name} in their own chat whether they want further help."]
        return [card, consent]

    def trip_card(self, case_id: str, person: Link, intro: str) -> Card:
        """The person's whole trip as one snapshot card: progress, who/route, the next step and
        the one button that applies now (ASI:One shows only the last card of a turn)."""
        j, mine = self.case(case_id), person.role == "VOLUNTEER"
        accepted, picked, arrived = (bool(j.steps[k]) for k in ("PROVIDER_ACCEPTED", "PICKUP_CONFIRMED", "ARRIVAL_CONFIRMED"))
        i_confirmed = ("volunteer" if mine else "resident") in self.pickup_confirms.get(case_id, set())
        shelter = j.help.get("shelter") or "the agreed shelter"
        progress = [("Volunteer accepted", accepted), ("Picked up", picked), ("Arrived at shelter", arrived)]
        rows: list[tuple[str, Any]] = []
        directions: list[str] = []
        if mine:
            r = j.route
            if r is not None and r.status == "ILLUSTRATIVE_ONLY":
                rows += [("Route", f"{(r.distance_m or 0) / 1000:.1f} km, about {round((r.duration_s or 0) / 60)} min "
                                   f"({r.status}, not for live evacuation)"),
                         ("Avoids", ", ".join(f"{a['kind']} {a['id']}" for a in r.avoided) or "no active blocks")]
                rows += [("Caution", f"{c}: unverified report on the path") for c in r.cautions_on_path]
                directions = list(r.directions)
            elif r is not None:
                rows.append(("Route", f"{r.status}: no route shown; ask the coordinator"))
            rows += [("Resident", NAMES.get(case_id, case_id)), ("Shelter", shelter)]
        else:
            eta = j.help.get("eta")
            rows += [("Volunteer", j.help.get("volunteer", "-")),
                     ("Estimated arrival", f"about {eta} min (estimate, not a guarantee)" if eta is not None
                      else "no estimate"), ("Shelter", shelter)]
        pickup = ("Confirm pickup", {"action": "confirm_pickup", "case_id": case_id})
        if arrived:
            nxt, cta = ("Your assignment is complete. Thank you for helping (simulated)." if mine else
                        "You've arrived. You can ask for further help."), None
        elif picked:
            nxt, cta = (f"Drive to {shelter}; the shelter confirms the arrival." if mine else
                        f"You're on the way to {shelter}."), None
        elif accepted and i_confirmed:
            nxt, cta = "Waiting for the other person to confirm pickup too.", None
        elif accepted:
            nxt, cta = ("Confirm only once the resident is in your vehicle." if mine else
                        "Confirm only once you are in the volunteer's vehicle."), pickup
        else:
            nxt, cta = "A coordinator is arranging help; nothing is confirmed yet.", None
        # Pickup point: volunteer only. B expires the map when the assignment ends, so drop it on arrival.
        image = getattr(j.route, "map_url", None) if mine and not arrived else None
        if image and not image.startswith("https://"):
            rows.append(("Map", "rendered; shown once the backend has a public https address"))
        return trip_card(case_id=case_id, name=NAMES.get(case_id, case_id), progress=progress, rows=rows,
                         next_step=nxt, cta=cta, intro=intro, steps=directions, image_url=image)

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
        card = info_card(f"Further help · {NAMES.get(case_id, case_id)}", rows,
                         "Post-Calamity agent sent consent-scoped referrals:", "Post-Calamity agent")
        if self.people.resident_for_case(case_id):  # the resident gave consent; coordinators are told
            await self.push(ctx, card)
        return card

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


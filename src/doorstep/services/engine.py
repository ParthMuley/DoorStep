"""DoorstepService: authoritative implementation of docs/interface-contract.md v1.0
(Developer B side). The FastAPI app is a thin layer over this class.

Every state change is written together with the timeline event that explains
it (serialized by ``db.tx()``). MongoDB has no multi-collection rollback here, so
each operation checks all of its guards *before* its first write.
Methods return contract-shaped dicts (the API adds ``schema_version``).
"""

from __future__ import annotations

from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from doorstep.demo import seed
from doorstep.demo.synthetic_zone_graph import ZoneGraph, build_demo_graph
from doorstep.integrations.message_simulator import MessageSimulator
from doorstep.models import (
    AlertEvent,
    Assignment,
    Case,
    CommunicationStatus as C,
    ConsentGrant,
    DestinationOfferIn,
    Escalation,
    EscalationReason,
    EscalationStatus,
    Evidence,
    Needs,
    Offer,
    ProviderResponse,
    RecoveryReferral,
    ReferralStatus,
    Resident,
    ResidentStatus as R,
    ResponseIntent,
    ServiceRequest,
    ServiceStatus as S,
    ServiceType,
    TransportOfferIn,
    VerificationEvent,
    ZoneRule,
    map_color,
    utc_now_iso,
)

from . import consent as consent_rules
from . import intake, matching, templates, verification
from .db import Database
from .errors import (
    Conflict,
    ConsentRequired,
    InvalidTransition,
    NotFound,
    SafetyRejection,
    Unauthenticated,
    Unauthorized,
    safety_code,
)
from .event_log import EventLog
from .registry import RegistryService
from .alerts import AlertService
from .matching_v2 import MatchService
from .recovery_v2 import RecoveryService
from .closures import ClosureService
from .routes import RouteService
from .dashboard import DashboardService
from . import deadlines
from .deadlines import DeadlineService
from .links import LinkService
from .maps import MapService
from .safety_rules import ROUTE_DISCLAIMER, assignment_safety_violations, zone_rule
from .store import Store
from .transitions import (
    RESIDENT_TRANSITIONS,
    TERMINAL_ASSIGNMENT_STATES,
    check_communication_transition,
    check_resident_transition,
)

TRANSPORT = ServiceType.ACCESSIBLE_TRANSPORT.value
DESTINATION = ServiceType.ACCESSIBLE_DESTINATION.value
RECOVERY_PROVIDER_ID = "recovery_org_demo"
ESCALATION_RECIPIENT = "SIMULATED_AUTHORIZED_RESPONSE_SERVICE"
OFFICIAL_SOURCE = "SIMULATED_OFFICIAL"
PREAPPROVED = "SIMULATED_PREAPPROVED"
CANDIDATE_FIELDS = ("wheelchair_accessible_vehicle", "transfer_assistance", "portable_oxygen_equipment",
                    "pet_count", "service_animal")


class DoorstepService:
    def __init__(self, db: Database, graph: Optional[ZoneGraph] = None):
        self.db = db
        self.store = Store(db)
        self.events = EventLog(db)
        self.sim = MessageSimulator(db, self.store)
        self.registry = RegistryService(db, self.store, self.events)
        self.graph = graph or build_demo_graph()
        self.alerts = AlertService(self)
        self.matching = MatchService(self)
        self.recovery = RecoveryService(self)
        self.closures = ClosureService(self)
        self.routes = RouteService(self)
        self.dashboard = DashboardService(self)
        self.links = LinkService(self)
        self.deadlines = DeadlineService(self)
        self.maps = MapService(self)
        self.registry.zone_lookup = self.alerts.zone_status_label

    # ================================================================ demo
    def reset(self, dataset: Optional[str] = None) -> dict[str, Any]:
        """Wipe and reseed deterministic synthetic data. ``dataset``: "core" (tests) or "full" (live demo);
        default DEMO_DATASET, else core (decision B-45)."""
        ds = seed.dataset_name(dataset)
        self.db.wipe()
        self.graph = build_demo_graph()
        orgs, regions, residents = seed.organizations(ds), seed.regions(ds), seed.residents(ds)
        with self.db.tx():
            for o in orgs:
                self.store.partners.save_org(o)
            for r in regions:
                self.store.partners.save_region(r)
            for r in residents:
                self.store.save_resident_profile(r, legacy_sector=seed.LEGACY_SECTORS.get(r.resident_id))
            for p in seed.provider_registry():
                self.store.save_registration(p)
            self.db.set_setting("escalation_ack", "true")
            self.db.set_setting("demo_dataset", ds)
            self.closures.seed_feeds()
            self.links.seed_codes(ds)
            self.events.append("DEMO_RESET", case_id=None, data={"simulated": True, "dataset": ds})
        return {"status": "reset", "dataset": ds, "residents": len(residents), "organizations": len(orgs),
                "regions": len(regions), "volunteers": sum(len(o.volunteers) for r in regions for o in r.orgs),
                "link_codes": len(seed.link_codes(ds)), "simulated": True}

    def set_escalation_ack(self, acknowledge: bool) -> dict[str, Any]:
        self.db.set_setting("escalation_ack", "true" if acknowledge else "false")
        return {"escalation_ack": acknowledge}

    # ============================================================= helpers
    def _corr(self, case: Case, correlation_id: Optional[str]) -> str:
        return correlation_id or case.correlation_id

    def _location(self, case: Case) -> str:
        return case.sector_id or case.zone_id

    def _zone_rule(self, case: Case) -> str:
        return zone_rule(self.graph, self._location(case)).value

    def _set_resident_status(self, case: Case, target: str, *, assignment: Optional[Assignment] = None,
                             actor: str = "system", reason: str = "", correlation_id: str = "") -> None:
        current = case.resident_status
        if current == target:
            return
        check_resident_transition(current, target, assignment)
        case.resident_status = target
        self.events.append(
            "RESIDENT_STATUS_CHANGED", case_id=case.case_id, correlation_id=correlation_id or case.correlation_id,
            actor=actor, dimension="resident", from_status=current, to_status=target,
            data={"reason": reason, "assignment_id": assignment.assignment_id if assignment else None},
        )

    def _can_move(self, case: Case, target: str) -> bool:
        return case.resident_status == target or target in RESIDENT_TRANSITIONS.get(case.resident_status, set())

    def _set_comm_status(self, case: Case, target: str, *, reason: str = "", correlation_id: str = "") -> None:
        current = case.communication_status
        if current == target:
            return
        check_communication_transition(current, target)
        case.communication_status = target
        if target == C.SENT:
            case.reply_by = deadlines.reply_by()  # plan rev 4 §0.5.3
        self.events.append(
            "COMMUNICATION_STATUS_CHANGED", case_id=case.case_id,
            correlation_id=correlation_id or case.correlation_id, dimension="communication",
            from_status=current, to_status=target, data={"reason": reason},
        )

    def _save_case(self, case: Case) -> None:
        case.updated_at = utc_now_iso()
        self.store.save_case(case)

    def _message_resident(self, case: Case, template_id: str, correlation_id: str = "", **kwargs: str):
        resident = self.store.get_resident(case.resident_id)
        lang = case.needs.preferred_language
        body = templates.render(template_id, lang, **kwargs)
        msg = self.sim.send(case_id=case.case_id, recipient=resident.contact_channel, body=body,
                            language=lang, template_id=template_id,
                            correlation_id=correlation_id or case.correlation_id)
        self.events.append("CHECKIN_SENT" if template_id == "checkin" else "MESSAGE_SENT",
                           case_id=case.case_id, correlation_id=msg.correlation_id,
                           data={"message_id": msg.message_id, "template_id": template_id, "simulated": True})
        return msg

    def _destination_label(self, destination: Assignment) -> str:
        if destination.site_id:
            found = self.store.partners.locate_site(destination.site_id)
            if found:
                return found[2].name
        return self._provider_name(destination.provider_id)

    def _provider_name(self, provider_id: str) -> str:
        reg = self.store.get_registration(provider_id)
        if reg:
            return reg.display_name
        org = self.store.partners.find_org(provider_id)
        return org.name if org else provider_id

    def _party_for_role(self, resident: Resident, granted_by: str) -> str:
        """Map RESIDENT/CAREGIVER (or a direct id) to the party id."""
        role = granted_by.upper()
        if role == "RESIDENT" or granted_by == resident.resident_id:
            return resident.resident_id
        if resident.caregiver and (role == "CAREGIVER" or granted_by == resident.caregiver.caregiver_id):
            return resident.caregiver.caregiver_id
        raise Unauthorized("Only the resident or their authorized caregiver can act here")

    # ================================================= start_demo_warning
    def start_demo_warning(self, zone_id: str, scenario_id: Optional[str] = None,
                           alert_source: str = OFFICIAL_SOURCE,
                           correlation_id: Optional[str] = None) -> dict[str, Any]:
        """Simulated OFFICIAL warning (demo-authorized callers only). Any other
        alert_source is recorded as a report requiring verification."""
        if zone_id not in self.graph.zones:
            raise NotFound(f"Unknown synthetic zone {zone_id!r}")
        corr = correlation_id or ""
        if alert_source != OFFICIAL_SOURCE:
            with self.db.tx():
                alert = AlertEvent(alert_id=self.db.next_id("report"), zone_id=zone_id, official_verified=False,
                                   scenario_id=scenario_id, created_at=utc_now_iso(),
                                   message="Report requires verification (DEMO). Not an official warning.")
                self.store.save_alert(alert)
                self.events.append("REPORT_RECORDED_REQUIRES_VERIFICATION", case_id=None, correlation_id=corr,
                                   data={"alert_id": alert.alert_id, "zone_id": zone_id, "alert_source": alert_source})
            return {"alert_id": alert.alert_id, "zone_id": zone_id, "verified": False, "simulated": True,
                    "case_ids": [], "checkins": [], "correlation_id": corr, "created_at": alert.created_at}

        covered = self.graph.zones_covered_by(zone_id)
        case_ids: list[str] = []
        with self.db.tx():
            alert = AlertEvent(alert_id=self.db.next_id("alert"), zone_id=zone_id, official_verified=True,
                               scenario_id=scenario_id, created_at=utc_now_iso(),
                               message=f"SIMULATED official warning for {zone_id} (DEMO)")
            self.store.save_alert(alert)
            self.events.append("SIMULATED_OFFICIAL_WARNING", case_id=None, correlation_id=corr, actor="demo_control",
                               data={"alert_id": alert.alert_id, "zone_id": zone_id, "covered_zones": covered,
                                     "scenario_id": scenario_id})
            for resident in self.store.list_residents():
                if resident.zone_id not in covered and resident.sector_id not in covered:
                    continue
                case_id = seed.CASE_IDS.get(resident.resident_id, f"case_{resident.resident_id}")
                case_ids.append(case_id)
                if self.store.find_case(case_id):
                    continue  # idempotent: one case per resident
                case = Case(
                    case_id=case_id, resident_id=resident.resident_id, zone_id=resident.zone_id,
                    sector_id=resident.sector_id, scenario_id=scenario_id, needs=resident.needs,
                    consent=resident.consent, alert_id=alert.alert_id,
                    correlation_id=corr or f"corr_{case_id}", created_at=utc_now_iso(),
                )
                self.events.append("CASE_CREATED", case_id=case_id, correlation_id=case.correlation_id,
                                   data={"alert_id": alert.alert_id, "zone_id": resident.zone_id})
                self.events.append("ALERT_VERIFIED", case_id=case_id, correlation_id=case.correlation_id,
                                   data={"alert_id": alert.alert_id, "evidence": OFFICIAL_SOURCE})
                if not resident.consent.contact_for_checkins:
                    case.next_step = "No check-in consent on file; coordinator decides next step."
                else:
                    self._message_resident(case, "checkin")
                    self._set_comm_status(case, C.SENT, reason="simulated check-in sent")
                    case.next_step = "Awaiting resident reply. Silence is not evidence of danger or safety."
                self._save_case(case)
        checkins = []
        for cid in case_ids:
            c = self.store.get_case(cid)
            checkins.append({"case_id": cid, "channel": "SIMULATED_SMS", "language": c.needs.preferred_language,
                             "communication_status": c.communication_status})
        return {"alert_id": alert.alert_id, "zone_id": zone_id, "verified": True, "simulated": True,
                "case_ids": case_ids, "checkins": checkins, "correlation_id": corr, "created_at": alert.created_at}

    # ============================================ submit_resident_response
    def submit_resident_response(self, case_id: str, text: str, language: Optional[str] = None, *,
                                 sender: str, external_id: Optional[str] = None,
                                 correlation_id: Optional[str] = None, via_doorstep_agent: bool = False) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        sender = self._linked_sender(case, resident, sender, via_doorstep_agent)
        allowed = {resident.contact_channel}
        if resident.caregiver:
            allowed.add(resident.caregiver.contact_channel)
        if sender not in allowed:
            # Unknown sender must not change the case. Logged without case_id or text.
            self.events.append("UNKNOWN_SENDER_REJECTED", case_id=None,
                               data={"target_case_id": case_id, "sender_known": False})
            raise Unauthorized("Sender is not an authorized contact for this case", reasons=["UNKNOWN_SENDER"])
        corr = self._corr(case, correlation_id)
        lang = language or case.needs.preferred_language

        if external_id:
            dup = self.store.message_by_external_id(external_id)
            if dup:
                self.events.append("MESSAGE_DUPLICATE_IGNORED", case_id=case_id, correlation_id=corr,
                                   data={"external_id": external_id})
                return {**self._response_view(case, corr), "response_id": dup.message_id,
                        "original_text": dup.body, "intent": None, "candidate_needs": {},
                        "confirmation_question": None, "duplicate": True}

        parsed = intake.extract(text, lang)
        question: Optional[str] = None
        with self.db.tx():
            msg = self.sim.record_inbound(case_id=case_id, sender=sender, body=text, language=lang,
                                          external_id=external_id or f"auto:{self.db.next_id('inbound')}",
                                          correlation_id=corr)
            self.events.append("RESIDENT_REPLIED", case_id=case_id, correlation_id=corr,
                               data={"response_id": msg.message_id, "intent": parsed.intent,
                                     "parse_method": parsed.method})
            self._set_comm_status(case, C.REPLIED, reason="resident replied", correlation_id=corr)
            actor = "caregiver" if sender != resident.contact_channel else "resident"
            intent = parsed.intent

            if intent == ResponseIntent.PICKUP_CONFIRMED:
                self._record_resident_pickup(case, resident, sender, corr)
            elif intent in (ResponseIntent.CONFIRM_YES, ResponseIntent.CONFIRM_NO) \
                    and case.pending_candidate_needs is None and case.resident_status == R.ARRIVAL_CONFIRMED:
                # Reply to the arrival message's "share your needs for further help?" question.
                party = resident.resident_id if actor == "resident" else (
                    resident.caregiver.caregiver_id if resident.caregiver else resident.resident_id)
                self.recovery.sms_reply_after_arrival(case, resident, party, intent == ResponseIntent.CONFIRM_YES, corr)
            elif intent == ResponseIntent.CONFIRM_YES:
                if case.pending_candidate_needs is not None:
                    self._confirm(case, case.pending_candidate_needs, actor, corr)
                else:
                    self.events.append("CONFIRMATION_IGNORED_NOTHING_PENDING", case_id=case_id, correlation_id=corr)
            elif intent == ResponseIntent.CONFIRM_NO:
                self._reject_candidates(case, actor, corr)
            else:
                case.response_intent = intent
                if intent == ResponseIntent.NEED_HELP:
                    if case.resident_status in (R.UNKNOWN, R.REQUIRES_COORDINATOR):
                        self._set_resident_status(case, R.NEEDS_ASSISTANCE, actor=actor,
                                                  reason="resident requested assistance", correlation_id=corr)
                    if not case.needs_confirmed:
                        merged = self._merge_needs(case.needs, parsed.candidate_needs)
                        case.pending_candidate_needs = merged
                        self.events.append("NEEDS_CANDIDATES_EXTRACTED", case_id=case_id, correlation_id=corr,
                                           data={"fields": sorted(parsed.candidate_needs)})
                        summary = templates.summarize_needs(merged.model_dump(), lang)
                        question = self._message_resident(case, "confirm_needs", corr, summary=summary).body
                        case.next_step = "Awaiting resident confirmation of needs (SI/YES or NO)."
                elif intent == ResponseIntent.CALL_ME:
                    if self._can_move(case, R.REQUIRES_COORDINATOR):
                        self._set_resident_status(case, R.REQUIRES_COORDINATOR, actor=actor,
                                                  reason="resident asked for a call", correlation_id=corr)
                    case.next_step = "Coordinator to call resident (simulated)."
                elif intent in (ResponseIntent.HAS_PLAN, ResponseIntent.ALREADY_LEFT):
                    what = "having a plan" if intent == ResponseIntent.HAS_PLAN else "already leaving"
                    case.next_step = f"Resident self-reported {what} (not verified). No assistance requested."
                else:
                    case.next_step = "Coordinator to review an unparsed free-text reply."
            self._save_case(case)

        candidates = {k: parsed.candidate_needs.get(k) for k in CANDIDATE_FIELDS} if parsed.candidate_needs else {}
        return {**self._response_view(case, corr), "response_id": msg.message_id, "original_text": text,
                "intent": parsed.intent.value, "candidate_needs": candidates,
                "confirmation_question": question, "duplicate": False}

    def _record_resident_pickup(self, case: Case, resident: Resident, sender: str, corr: str) -> None:
        """Resident side of pickup (A's review item 5). Only counts while a volunteer is ACCEPTED."""
        a = self.store.accepted_assignment(case.case_id, TRANSPORT)
        if a is None or a.status != S.ACCEPTED or a.confirmed_pickup_at:
            self.events.append("PICKUP_CONFIRMATION_IGNORED", case_id=case.case_id, correlation_id=corr,
                               data={"reason": "NO_ACCEPTED_TRANSPORT_AWAITING_PICKUP"})
            return
        party = resident.resident_id if sender == resident.contact_channel else (
            resident.caregiver.caregiver_id if resident.caregiver else sender)
        a.resident_pickup_confirmed_at = utc_now_iso()
        a.resident_pickup_confirmed_by = party
        self.store.save_assignment(a)
        self.events.append("RESIDENT_PICKUP_CONFIRMED", case_id=case.case_id, correlation_id=corr,
                           data={"assignment_id": a.assignment_id, "party": party})
        case.next_step = "Resident confirmed pickup; awaiting the volunteer's pickup report."

    def _response_view(self, case: Case, corr: str) -> dict[str, Any]:
        view = {"case_id": case.case_id, "needs_confirmed": case.needs_confirmed,
                "communication_status": case.communication_status, "resident_status": case.resident_status,
                "next_step": case.next_step, "correlation_id": corr}
        if case.needs_confirmed:
            view["needs"] = case.needs.model_dump()
        return view

    @staticmethod
    def _merge_needs(base: Needs, candidates: dict) -> Needs:
        data = base.model_dump()
        for key, value in candidates.items():
            if key == "pet_count":
                data[key] = max(int(data.get(key, 0)), int(value))
            elif isinstance(value, bool):
                data[key] = data.get(key, False) or value
            else:
                data[key] = value
        return Needs(**data)

    def _confirm(self, case: Case, needs: Needs, actor: str, corr: str) -> None:
        case.needs = needs
        case.needs_confirmed = True
        case.pending_candidate_needs = None
        self.events.append("NEEDS_CONFIRMED", case_id=case.case_id, correlation_id=corr, actor=actor)
        self._message_resident(case, "needs_confirmed", corr)
        case.next_step = "Collect provider offers and evaluate them."

    def _reject_candidates(self, case: Case, actor: str, corr: str) -> None:
        case.pending_candidate_needs = None
        case.needs_confirmed = False
        self.events.append("NEEDS_REJECTED_BY_RESIDENT", case_id=case.case_id, correlation_id=corr, actor=actor)
        if self._can_move(case, R.REQUIRES_COORDINATOR):
            self._set_resident_status(case, R.REQUIRES_COORDINATOR, actor=actor,
                                      reason="resident did not confirm extracted needs", correlation_id=corr)
        self._message_resident(case, "coordinator_followup", corr)
        case.next_step = "Coordinator to clarify needs with resident (simulated call)."

    # ======================================== find_transport / destination
    def evaluate_transport(self, case_id: str, candidate_offers: list[TransportOfferIn],
                           request_id: Optional[str] = None, correlation_id: Optional[str] = None) -> dict[str, Any]:
        return self._evaluate(case_id, TRANSPORT, candidate_offers, request_id, correlation_id)

    def evaluate_destination(self, case_id: str, candidate_offers: list[DestinationOfferIn],
                             request_id: Optional[str] = None,
                             correlation_id: Optional[str] = None) -> dict[str, Any]:
        return self._evaluate(case_id, DESTINATION, candidate_offers, request_id, correlation_id)

    def _requirements(self, case: Case, service_type: str):
        if service_type == TRANSPORT:
            return consent_rules.transport_requirements(case)
        return consent_rules.destination_requirements(case)

    def _evaluate(self, case_id: str, service_type: str, raw_offers: list, request_id: Optional[str],
                  correlation_id: Optional[str]) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        corr = self._corr(case, correlation_id)
        if not case.needs_confirmed:
            raise Conflict("Resident needs must be confirmed before evaluating offers", code="NEEDS_NOT_CONFIRMED")
        if case.resident_status == R.UNKNOWN:
            raise Conflict("Resident has not requested assistance", code="NO_ASSISTANCE_REQUESTED")
        reqs = self._requirements(case, service_type)  # raises CONSENT_MISSING
        rule = self._zone_rule(case)
        with self.db.tx():
            request_id = request_id or self.db.next_id("req")
            key = f"{case_id}:{service_type}:{request_id}"
            request = self.store.request_by_key(key)
            if request is None:
                field = "transport_requirements" if service_type == TRANSPORT else "destination_requirements"
                request = ServiceRequest(request_id=request_id, case_id=case_id, service_type=service_type,
                                         zone_id=case.zone_id, status=S.DRAFT, idempotency_key=key, **{field: reqs})
                self.events.append("SERVICE_REQUEST_CREATED", case_id=case_id, correlation_id=corr,
                                   data={"request_id": request_id, "service_type": service_type})
            registry = self.store.registry()
            if service_type == TRANSPORT:
                offers = matching.evaluate_transport_offers(case_id, request_id, reqs, case.zone_id, case.sector_id,
                                                            raw_offers, registry, self.graph)
            else:
                offers = matching.evaluate_destination_offers(case_id, request_id, reqs, case.zone_id,
                                                              case.sector_id, raw_offers, registry, self.graph)
            for o in offers:
                self.store.save_offer(o)
            eligible = [o for o in offers if o.eligible]

            history = self.store.assignments_for_case(case_id, service_type)
            if not any(a.status in (S.AWAITING_PROVIDER, S.ACCEPTED, S.COMPLETED) for a in history):
                declined = {a.provider_id for a in history if a.status in TERMINAL_ASSIGNMENT_STATES}
                request.status = S.PROPOSED if [o for o in eligible if o.provider_id not in declined] else S.UNRESOLVED
            self.store.save_request(request)
            self.events.append("OFFERS_EVALUATED", case_id=case_id, correlation_id=corr,
                               data={"request_id": request_id, "service_type": service_type,
                                     "eligible": [o.offer_id for o in eligible],
                                     "rejected": {o.offer_id: o.reasons for o in offers if not o.eligible}})

            escalation_required = rule != ZoneRule.OUTSIDE_ACTIVE_ORDER or (
                service_type == TRANSPORT and request.status == S.UNRESOLVED)
            if service_type == TRANSPORT and request.status == S.UNRESOLVED:
                if self._can_move(case, R.REQUIRES_COORDINATOR):
                    self._set_resident_status(
                        case, R.REQUIRES_COORDINATOR, correlation_id=corr,
                        reason="active-order zone" if rule != ZoneRule.OUTSIDE_ACTIVE_ORDER else "no eligible provider")
                case.next_step = (
                    "Inside a simulated active evacuation-order zone: ordinary volunteer dispatch is blocked. "
                    "Escalate to the simulated authorized response service."
                    if rule != ZoneRule.OUTSIDE_ACTIVE_ORDER
                    else "No eligible provider. Escalate per partner policy; case stays unresolved.")
            elif request.status == S.UNRESOLVED:
                case.next_step = "No eligible accessible destination. Coordinator follow-up required."
            elif request.status == S.PROPOSED:
                case.next_step = f"Propose the top-ranked eligible {service_type.replace('_', ' ')} offer."
            self._save_case(case)

        return {"case_id": case_id, "request_id": request_id, "zone_rule": rule,
                "eligible": [{"offer_id": o.offer_id, "provider_id": o.provider_id, "rank": o.rank,
                              "match_reasons": o.match_reasons} for o in eligible],
                "rejected": [{"offer_id": o.offer_id, "provider_id": o.provider_id, "reasons": o.reasons}
                             for o in offers if not o.eligible],
                "escalation_required": escalation_required, "correlation_id": corr}

    # ================================================== propose_assignment
    def propose_assignment(self, case_id: str, *, transport_offer_id: Optional[str] = None,
                           destination_offer_id: Optional[str] = None, authorization: str = PREAPPROVED,
                           idempotency_key: Optional[str] = None,
                           correlation_id: Optional[str] = None) -> tuple[dict[str, Any], bool]:
        """Returns (assignment view, created). Repeating an idempotency key returns the original."""
        case = self.store.get_case(case_id)
        corr = self._corr(case, correlation_id)
        if not transport_offer_id and not destination_offer_id:
            raise Conflict("Provide transport_offer_id and/or destination_offer_id", code="OFFER_NOT_ELIGIBLE")
        key = idempotency_key or f"{case_id}:{transport_offer_id or '-'}:{destination_offer_id or '-'}"
        existing = self.store.assignment_by_key(key)
        if existing:
            return self._assignment_view(existing, corr), False
        if authorization != PREAPPROVED:
            raise SafetyRejection("Only SIMULATED_PREAPPROVED arrangements can be proposed automatically",
                                  code="NOT_AUTHORIZED", reasons=["NOT_PREAPPROVED"])

        checked: list[tuple[Offer, str]] = []
        for offer_id, st in ((transport_offer_id, TRANSPORT), (destination_offer_id, DESTINATION)):
            if not offer_id:
                continue
            offer = self.store.get_offer(case_id, offer_id)
            if offer.service_type != st:
                raise Conflict(f"Offer {offer_id} is not a {st} offer", code="OFFER_NOT_ELIGIBLE")
            reasons = self._recheck(case, offer)
            if reasons:
                self.events.append("ASSIGNMENT_REJECTED_BY_SAFETY", case_id=case_id, correlation_id=corr,
                                   data={"offer_id": offer_id, "provider_id": offer.provider_id, "reasons": reasons})
                raise SafetyRejection("Offer fails deterministic eligibility/safety checks",
                                      reasons=reasons, code=safety_code(reasons))
            if self.store.accepted_assignment(case_id, st):
                raise Conflict(f"Case already has an accepted {st} assignment", code="ALREADY_ACCEPTED")
            if any(a.provider_id == offer.provider_id and a.status in (S.DECLINED, S.CANCELED)
                   for a in self.store.assignments_for_case(case_id, st)):
                raise Conflict("Provider already declined or canceled for this case; choose another offer",
                               code="PROVIDER_ALREADY_RESPONDED")
            checked.append((offer, st))

        with self.db.tx():
            rows: list[Assignment] = []
            primary_id = self.db.next_id("assign")
            for i, (offer, st) in enumerate(checked):
                reg = self.store.get_registration(offer.provider_id)
                rule = zone_rule(self.graph, self._location(case) if st == TRANSPORT else (reg.base_zone if reg else None))
                approved = bool(reg and reg.approved)
                a = Assignment(
                    assignment_id=primary_id if i == 0 else f"{primary_id}_dest", case_id=case_id,
                    request_id=offer.request_id, offer_id=offer.offer_id, provider_id=offer.provider_id,
                    service_type=st, provider_approved=approved, service_area_allowed=True, zone_rule=rule,
                    authorization=PREAPPROVED if approved and rule == ZoneRule.OUTSIDE_ACTIVE_ORDER
                    else "REQUIRES_AUTHORIZED_RESPONSE",
                    status=S.AWAITING_PROVIDER, idempotency_key=key if i == 0 else f"{key}:destination",
                    correlation_id=corr, created_at=utc_now_iso())
                violations = assignment_safety_violations(a)
                if violations:  # belt and braces; evaluation should already have caught this
                    raise SafetyRejection("Assignment blocked by safety gate", reasons=violations,
                                          code=safety_code(violations))
                rows.append(a)
            if len(rows) == 2:
                rows[0].linked_assignment_id = rows[1].assignment_id
                rows[1].linked_assignment_id = rows[0].assignment_id
            for a in rows:
                self.store.save_assignment(a)
                request = self.store.find_request(case_id, a.service_type, a.request_id)
                request.status = S.AWAITING_PROVIDER
                self.store.save_request(request)
                self.events.append("ASSIGNMENT_PROPOSED", case_id=case_id, correlation_id=corr,
                                   data={"assignment_id": a.assignment_id, "provider_id": a.provider_id,
                                         "service_type": a.service_type})
            names = " and ".join(self._provider_name(a.provider_id) for a in rows)
            case.next_step = f"Awaiting acceptance from {names}. Nothing is confirmed yet."
            self._save_case(case)
        return self._assignment_view(rows[0], corr), True

    def _recheck(self, case: Case, offer: Offer) -> list[str]:
        """Re-evaluate the stored raw offer NOW (expiry, approval, zone, consent)."""
        reqs = self._requirements(case, offer.service_type)
        reg = self.store.get_registration(offer.provider_id)
        if offer.service_type == TRANSPORT:
            reasons, _, _ = matching.evaluate_transport(reqs, case.zone_id, case.sector_id,
                                                        TransportOfferIn(**offer.raw), reg, self.graph)
        else:
            reasons, _, _ = matching.evaluate_destination(reqs, case.zone_id, case.sector_id,
                                                          DestinationOfferIn(**offer.raw), reg, self.graph)
        return reasons

    def _linked(self, a: Assignment) -> Optional[Assignment]:
        return self.store.find_assignment(a.linked_assignment_id) if a.linked_assignment_id else None

    def _assignment_view(self, primary: Assignment, corr: str) -> dict[str, Any]:
        case = self.store.get_case(primary.case_id)
        linked = self._linked(primary)
        transport = primary if primary.service_type == TRANSPORT else None
        if primary.service_type == TRANSPORT:
            shared = {**consent_rules.transport_requirements(case).model_dump(),
                      "pickup_area": f"{self._location(case)}_synthetic"}
        else:
            shared = consent_rules.destination_requirements(case).model_dump()
        return {
            "assignment_id": primary.assignment_id, "case_id": primary.case_id,
            "provider_id": primary.provider_id,
            "destination_provider_id": linked.provider_id if linked else (
                primary.provider_id if primary.service_type == DESTINATION else None),
            "provider_approved": primary.provider_approved, "service_area_allowed": primary.service_area_allowed,
            "zone_rule": primary.zone_rule,
            "provider_response": None if primary.provider_response == ProviderResponse.PENDING
            else primary.provider_response,
            "destination_provider_response": (None if not linked or linked.provider_response == ProviderResponse.PENDING
                                              else linked.provider_response),
            "authorization": primary.authorization, "service_status": primary.status,
            "resident_status": case.resident_status, "shared_with_provider": shared,
            "confirmed_pickup_at": transport.confirmed_pickup_at if transport else None,
            "confirmed_arrival_at": transport.confirmed_arrival_at if transport else None,
            "correlation_id": corr,
        }

    # =================================================== accept_assignment
    def respond_assignment(self, assignment_id: str, provider_id: str, decision: str,
                           correlation_id: Optional[str] = None) -> dict[str, Any]:
        """Provider ACCEPTS or DECLINES freely. ``assignment_id`` is the id from
        propose; the transport or destination provider of that proposal may respond.
        Duplicates are idempotent; late replies never revive canceled assignments."""
        decision = decision.upper()
        if decision not in ("ACCEPTED", "DECLINED"):
            raise Conflict("decision must be ACCEPTED or DECLINED", code="INVALID_DECISION")
        primary = self.store.get_assignment(assignment_id)
        linked = self._linked(primary)
        row = primary if provider_id == primary.provider_id else (
            linked if linked and provider_id == linked.provider_id else None)
        case = self.store.get_case(primary.case_id)
        corr = self._corr(case, correlation_id)
        if row is None:
            self.events.append("PROVIDER_IDENTITY_REJECTED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": assignment_id})
            raise Unauthorized("Provider identity does not match this assignment", reasons=["WRONG_PROVIDER"])
        reg = self.store.get_registration(provider_id)
        if reg is None or not reg.approved:
            raise Unauthorized("Provider is not approved", reasons=["PROVIDER_NOT_APPROVED"])

        accept = decision == "ACCEPTED"
        duplicate = (accept and row.status in (S.ACCEPTED, S.COMPLETED)) or (not accept and row.status == S.DECLINED)
        if not duplicate:
            if row.status in (S.CANCELED, S.DECLINED, S.UNRESOLVED, S.COMPLETED):
                self.events.append("LATE_RESPONSE_IGNORED", case_id=case.case_id, correlation_id=corr,
                                   data={"assignment_id": row.assignment_id, "assignment_status": row.status,
                                         "decision": decision})
                raise InvalidTransition(f"Assignment is {row.status}; late response ignored",
                                        reasons=["LATE_RESPONSE"])
            try:
                with self.db.tx():
                    if accept:
                        self._accept(row, case, corr)
                    elif row.status == S.ACCEPTED:
                        self._provider_cancel(row, case, corr)
                    else:
                        self._decline(row, case, corr)
                    self._save_case(case)
            except DuplicateKeyError as exc:
                raise Conflict("Another assignment for this service was already accepted",
                               code="DUPLICATE_ACCEPTANCE") from exc

        row = self.store.get_assignment(row.assignment_id)
        case = self.store.get_case(case.case_id)
        transport = primary if primary.service_type == TRANSPORT else None
        if transport:
            transport = self.store.get_assignment(transport.assignment_id)
        pickup = None
        if row.service_type == TRANSPORT and row.status == S.ACCEPTED:
            pickup = {"pickup_point": self.store.get_resident(case.resident_id).pickup_point}
        return {"assignment_id": primary.assignment_id, "case_id": case.case_id, "provider_id": row.provider_id,
                "service_type": row.service_type,
                "provider_response": None if row.provider_response == ProviderResponse.PENDING else row.provider_response,
                "service_status": row.status, "resident_status": case.resident_status, "pickup_details": pickup,
                "confirmed_pickup_at": transport.confirmed_pickup_at if transport else None,
                "confirmed_arrival_at": transport.confirmed_arrival_at if transport else None,
                "next_step": case.next_step, "duplicate": duplicate, "correlation_id": corr}

    def _accept(self, a: Assignment, case: Case, corr: str) -> None:
        violations = assignment_safety_violations(a)
        if violations:
            raise SafetyRejection("Assignment fails safety gate", reasons=violations, code=safety_code(violations))
        if a.service_type == TRANSPORT:
            # Check the guard BEFORE mutating anything (whole tx rolls back on failure).
            probe = a.model_copy(update={"status": S.ACCEPTED, "provider_response": ProviderResponse.ACCEPTED})
            check_resident_transition(case.resident_status, R.PROVIDER_ACCEPTED, probe)
        a.status = S.ACCEPTED
        a.provider_response = ProviderResponse.ACCEPTED
        a.updated_at = utc_now_iso()
        self.store.save_assignment(a)  # unique index rejects a second accepted assignment
        for other in self.store.assignments_for_case(a.case_id, a.service_type):
            if other.assignment_id != a.assignment_id and other.status in (S.PROPOSED, S.AWAITING_PROVIDER):
                other.status = S.CANCELED
                other.updated_at = utc_now_iso()
                self.store.save_assignment(other)
                self.events.append("ASSIGNMENT_CANCELED", case_id=a.case_id, correlation_id=corr,
                                   data={"assignment_id": other.assignment_id, "reason": "another provider accepted"})
        request = self.store.find_request(a.case_id, a.service_type, a.request_id)
        request.status = S.ACCEPTED
        self.store.save_request(request)
        self.events.append("PROVIDER_ACCEPTED", case_id=a.case_id, correlation_id=corr, actor=a.provider_id,
                           data={"assignment_id": a.assignment_id, "service_type": a.service_type,
                                 "authorization": a.authorization})
        name = self._provider_name(a.provider_id)
        if a.service_type == TRANSPORT:
            self._set_resident_status(case, R.PROVIDER_ACCEPTED, assignment=a, actor=a.provider_id,
                                      reason="transport provider accepted", correlation_id=corr)
            self.events.append("PICKUP_DETAILS_RELEASED", case_id=a.case_id, correlation_id=corr,
                               actor=a.provider_id, data={"assignment_id": a.assignment_id})
            if a.volunteer_id:  # contract v2: a registered volunteer accepted
                self._message_resident(case, "help_on_the_way", corr, eta=str(a.eta_minutes or "?"))
            else:
                self._message_resident(case, "provider_accepted", corr, provider=name)
            dest = self.store.accepted_assignment(a.case_id, DESTINATION)
            case.next_step = ("Awaiting pickup confirmation." if dest
                              else "Transport accepted; destination acceptance still needed before arrival.")
        else:
            case.next_step = (f"Destination {name} accepted (simulated). "
                              + ("Awaiting pickup confirmation." if case.resident_status == R.PROVIDER_ACCEPTED
                                 else "Transport acceptance still needed."))

    def _decline(self, a: Assignment, case: Case, corr: str) -> None:
        a.status = S.DECLINED
        a.provider_response = ProviderResponse.DECLINED
        a.updated_at = utc_now_iso()
        self.store.save_assignment(a)
        self.events.append("PROVIDER_DECLINED", case_id=a.case_id, correlation_id=corr, actor=a.provider_id,
                           data={"assignment_id": a.assignment_id, "service_type": a.service_type})
        self._after_provider_loss(a, case, corr)

    def _provider_cancel(self, a: Assignment, case: Case, corr: str) -> None:
        if a.confirmed_pickup_at:
            raise InvalidTransition("Pickup already confirmed; coordinator must handle this change",
                                    reasons=["PICKUP_ALREADY_CONFIRMED"])
        a.status = S.CANCELED
        a.updated_at = utc_now_iso()
        self.store.save_assignment(a)
        self.events.append("PROVIDER_CANCELED_AFTER_ACCEPTANCE", case_id=a.case_id, correlation_id=corr,
                           actor=a.provider_id, data={"assignment_id": a.assignment_id})
        if a.service_type == TRANSPORT and case.resident_status == R.PROVIDER_ACCEPTED:
            self._set_resident_status(case, R.NEEDS_ASSISTANCE, reason="provider canceled", correlation_id=corr)
        self._after_provider_loss(a, case, corr)

    def _after_provider_loss(self, a: Assignment, case: Case, corr: str) -> None:
        request = self.store.find_request(a.case_id, a.service_type, a.request_id)
        history = self.store.assignments_for_case(a.case_id, a.service_type)
        tried = {x.provider_id for x in history if x.status in TERMINAL_ASSIGNMENT_STATES}
        pending = [x for x in history if x.status in (S.AWAITING_PROVIDER, S.ACCEPTED)]
        alternates = [o for o in self.store.offers_for_request(a.case_id, request.request_id)
                      if o.eligible and o.provider_id not in tried]
        kind = "transport" if a.service_type == TRANSPORT else "destination"
        if pending:
            request.status = S.AWAITING_PROVIDER
        elif alternates:
            request.status = S.PROPOSED
            case.next_step = (f"{kind.title()} provider declined. Alternate eligible offer: "
                              f"{alternates[0].offer_id} ({self._provider_name(alternates[0].provider_id)}).")
        else:
            request.status = S.UNRESOLVED
            if a.service_type == TRANSPORT and self._can_move(case, R.REQUIRES_COORDINATOR):
                self._set_resident_status(case, R.REQUIRES_COORDINATOR, reason="no remaining eligible provider",
                                          correlation_id=corr)
            case.next_step = f"No remaining eligible {kind} provider. Unresolved: escalate per partner policy."
        self.store.save_request(request)

    def get_pickup_details(self, assignment_id: str, provider_id: str) -> dict[str, Any]:
        """Synthetic pickup point: only for the approved transport provider that accepted."""
        a = self.store.get_assignment(assignment_id)
        if a.service_type != TRANSPORT or provider_id != a.provider_id:
            raise Unauthorized("Not the transport provider for this assignment")
        reg = self.store.get_registration(provider_id)
        if reg is None or not reg.approved:
            raise Unauthorized("Provider is not approved", reasons=["PROVIDER_NOT_APPROVED"])
        if a.status != S.ACCEPTED:
            raise Unauthorized("Pickup details are released only after acceptance", reasons=["NOT_ACCEPTED"])
        case = self.store.get_case(a.case_id)
        consent_rules.transport_requirements(case)  # raises CONSENT_MISSING
        resident = self.store.get_resident(case.resident_id)
        return {"assignment_id": assignment_id, "pickup_point": resident.pickup_point, "simulated": True,
                "route_note": ROUTE_DISCLAIMER}

    # ================================================== pickup / arrival
    def _transport_row(self, assignment_id: str) -> Assignment:
        a = self.store.get_assignment(assignment_id)
        if a.service_type == TRANSPORT:
            return a
        linked = self._linked(a)
        if linked and linked.service_type == TRANSPORT:
            return linked
        raise Conflict("Pickup and arrival are confirmed on a transport assignment", code="INVALID_TRANSITION")

    def _evidence_view(self, a: Assignment, case: Case, corr: str, duplicate: bool) -> dict[str, Any]:
        return {"assignment_id": a.assignment_id, "case_id": case.case_id, "service_status": a.status,
                "resident_status": case.resident_status, "confirmed_pickup_at": a.confirmed_pickup_at,
                "confirmed_arrival_at": a.confirmed_arrival_at, "next_step": case.next_step,
                "duplicate": duplicate, "correlation_id": corr}

    def confirm_pickup(self, assignment_id: str, evidence: Evidence,
                       correlation_id: Optional[str] = None) -> dict[str, Any]:
        a = self._transport_row(assignment_id)
        case = self.store.get_case(a.case_id)
        corr = self._corr(case, correlation_id)
        if a.confirmed_pickup_at:
            return self._evidence_view(a, case, corr, True)
        if a.status != S.ACCEPTED:
            raise InvalidTransition(f"Assignment is {a.status}; pickup requires an accepted assignment",
                                    reasons=["NOT_ACCEPTED"])
        resident = self.store.get_resident(case.resident_id)
        ids_verified = verification.check_pickup_evidence(evidence, resident, a)
        check_resident_transition(case.resident_status, R.PICKUP_CONFIRMED,
                                  a.model_copy(update={"confirmed_pickup_at": "pending"}))
        with self.db.tx():
            a.confirmed_pickup_at = utc_now_iso()
            a.updated_at = a.confirmed_pickup_at
            self.store.save_assignment(a)
            v = VerificationEvent(verification_id=self.db.next_id("verif"), case_id=case.case_id,
                                  assignment_id=a.assignment_id, kind="pickup", evidence=evidence,
                                  party_ids_verified=ids_verified, correlation_id=corr)
            self.store.save_verification(v)
            self.events.append("PICKUP_CONFIRMED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": a.assignment_id, "verification_id": v.verification_id,
                                     "evidence": evidence.type, "party_ids_verified": ids_verified})
            self._set_resident_status(case, R.PICKUP_CONFIRMED, assignment=a, reason="pickup evidence recorded",
                                      correlation_id=corr)
            case.next_step = "Awaiting arrival confirmation at the agreed destination."
            self._save_case(case)
        return self._evidence_view(a, case, corr, False)

    def confirm_arrival(self, assignment_id: str, evidence: Evidence,
                        correlation_id: Optional[str] = None) -> dict[str, Any]:
        a = self._transport_row(assignment_id)
        case = self.store.get_case(a.case_id)
        corr = self._corr(case, correlation_id)
        if a.confirmed_arrival_at:
            return self._evidence_view(a, case, corr, True)
        if not a.confirmed_pickup_at:
            raise InvalidTransition("Arrival requires a confirmed pickup first", reasons=["PICKUP_NOT_CONFIRMED"])
        destination = self.store.accepted_assignment(case.case_id, DESTINATION)
        if destination is None:
            raise InvalidTransition("No accepted destination; arrival must be at an agreed destination",
                                    reasons=["NO_AGREED_DESTINATION"])
        resident = self.store.get_resident(case.resident_id)
        ids_verified = verification.check_arrival_evidence(evidence, resident, a, destination)
        check_resident_transition(case.resident_status, R.ARRIVAL_CONFIRMED,
                                  a.model_copy(update={"confirmed_arrival_at": "pending"}))
        with self.db.tx():
            a.confirmed_arrival_at = utc_now_iso()
            a.status = S.COMPLETED
            a.updated_at = a.confirmed_arrival_at
            self.store.save_assignment(a)
            request = self.store.find_request(a.case_id, TRANSPORT, a.request_id)
            request.status = S.COMPLETED
            self.store.save_request(request)
            v = VerificationEvent(verification_id=self.db.next_id("verif"), case_id=case.case_id,
                                  assignment_id=a.assignment_id, kind="arrival", evidence=evidence,
                                  party_ids_verified=ids_verified, correlation_id=corr)
            self.store.save_verification(v)
            self.events.append("ARRIVAL_CONFIRMED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": a.assignment_id, "verification_id": v.verification_id,
                                     "destination_assignment_id": destination.assignment_id,
                                     "evidence": evidence.type, "party_ids_verified": ids_verified})
            self._set_resident_status(case, R.ARRIVAL_CONFIRMED, assignment=a, reason="arrival evidence recorded",
                                      correlation_id=corr)
            if a.volunteer_id:  # free the volunteer for other cases
                self.store.partners.release_volunteer(a.volunteer_id, case.case_id)
                self.events.append("VOLUNTEER_RELEASED", case_id=case.case_id, correlation_id=corr,
                                   data={"org_id": a.provider_id, "volunteer_id": a.volunteer_id})
            self._message_resident(case, "arrival_confirmed", corr,
                                   destination=self._destination_label(destination))
            case.next_step = "Ask resident for consent before any recovery-support referral."
            self._save_case(case)
        return self._evidence_view(a, case, corr, False)

    # =================================================== recovery handoff
    def request_recovery_handoff(self, case_id: str, *, share_recovery_needs: bool, granted_by: str,
                                 granted_at: Optional[str] = None, idempotency_key: Optional[str] = None,
                                 correlation_id: Optional[str] = None) -> tuple[dict[str, Any], bool]:
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        party_id = self._party_for_role(resident, granted_by)
        corr = self._corr(case, correlation_id)
        key = idempotency_key or f"{case_id}:recovery:v1"
        existing = self.store.referral_by_key(key)
        if existing and share_recovery_needs:
            return self._referral_view(existing, corr), False

        with self.db.tx():
            self.store.add_consent_grant(ConsentGrant(case_id=case_id, scope="share_recovery_needs",
                                                      granted=share_recovery_needs, granted_by=party_id,
                                                      created_at=granted_at or utc_now_iso()))
            case.consent = case.consent.model_copy(update={"share_recovery_needs": share_recovery_needs})
            if not share_recovery_needs:
                self.events.append("RECOVERY_CONSENT_DECLINED", case_id=case_id, correlation_id=corr)
                case.next_step = "Resident declined recovery referral. Nothing shared."
                self._save_case(case)
        if not share_recovery_needs:
            raise ConsentRequired("Resident did not consent to share recovery needs; nothing was shared")

        with self.db.tx():
            payload = consent_rules.recovery_payload(case)
            referral = RecoveryReferral(referral_id=self.db.next_id("ref"), case_id=case_id,
                                        provider_id=RECOVERY_PROVIDER_ID, shared_fields=payload,
                                        idempotency_key=key, correlation_id=corr)
            self.store.save_referral(referral)
            self.events.append("RECOVERY_CONSENT_GRANTED", case_id=case_id, correlation_id=corr, actor=party_id)
            self.events.append("RECOVERY_REFERRAL_REQUESTED", case_id=case_id, correlation_id=corr,
                               data={"referral_id": referral.referral_id, "provider_id": RECOVERY_PROVIDER_ID,
                                     "field_names": sorted(payload)})
            case.next_step = "Recovery referral REQUESTED. Housing is not secured unless the provider confirms."
            self._save_case(case)
        return self._referral_view(referral, corr), True

    @staticmethod
    def _referral_view(r: RecoveryReferral, corr: str) -> dict[str, Any]:
        return {"referral_id": r.referral_id, "case_id": r.case_id, "status": r.status,
                "shared_fields": sorted(r.shared_fields), "housing_secured": False, "correlation_id": corr}

    def respond_recovery(self, referral_id: str, provider_id: str, decision: str,
                         correlation_id: Optional[str] = None) -> dict[str, Any]:
        """Simulated recovery-provider response. ACCEPTED == follow-up request accepted, not housing."""
        referral = self.store.get_referral(referral_id)
        if provider_id != referral.provider_id:
            raise Unauthorized("Provider identity does not match this referral")
        target = ReferralStatus.ACCEPTED if decision.upper() == "ACCEPTED" else ReferralStatus.UNRESOLVED
        case = self.store.get_case(referral.case_id)
        corr = self._corr(case, correlation_id)
        if referral.status == target:
            return self._referral_view(referral, corr)
        if referral.status != ReferralStatus.REQUESTED:
            raise InvalidTransition(f"Referral already {referral.status}", reasons=["LATE_RESPONSE"])
        with self.db.tx():
            referral.status = target
            referral.updated_at = utc_now_iso()
            self.store.save_referral(referral)
            self.events.append(f"RECOVERY_REFERRAL_{target.value}", case_id=case.case_id, correlation_id=corr,
                               actor=provider_id, data={"referral_id": referral_id})
            case.next_step = ("Recovery follow-up request accepted by simulated provider (not housing secured)."
                              if target == ReferralStatus.ACCEPTED else "Recovery referral unresolved; coordinator follow-up.")
            self._save_case(case)
        return self._referral_view(referral, corr)

    # ======================================================= escalate_case
    def escalate_case(self, case_id: str, reason: str, *, idempotency_key: Optional[str] = None,
                      correlation_id: Optional[str] = None) -> tuple[dict[str, Any], bool]:
        """Simulated escalation. Never contacts 911; acknowledgment == request received only."""
        reason = EscalationReason(reason).value
        case = self.store.get_case(case_id)
        corr = self._corr(case, correlation_id)
        key = idempotency_key or f"{case_id}:escalation:{reason}"
        existing = self.store.escalation_by_key(key)
        if existing:
            return self._escalation_view(existing, self.store.get_case(case_id), corr), False
        if reason == EscalationReason.ACTIVE_EVACUATION_ORDER_ZONE and \
                self._zone_rule(case) == ZoneRule.OUTSIDE_ACTIVE_ORDER:
            raise Conflict("Case is not inside a simulated active-order zone", code="REASON_MISMATCH")
        if reason == EscalationReason.NO_REPLY_AFTER_DEADLINE and case.communication_status != C.NO_REPLY_AFTER_DEADLINE:
            raise Conflict("Communication status is not NO_REPLY_AFTER_DEADLINE", code="REASON_MISMATCH")
        if case.resident_status == R.ARRIVAL_CONFIRMED:
            raise InvalidTransition("Arrival already confirmed; nothing to escalate")
        acknowledge = self.db.get_setting("escalation_ack", "true") == "true"
        with self.db.tx():
            esc = Escalation(escalation_id=self.db.next_id("esc"), case_id=case_id, reason=reason,
                             recipient=ESCALATION_RECIPIENT, status=EscalationStatus.REQUESTED,
                             idempotency_key=key, correlation_id=corr)
            self.events.append("ESCALATION_REQUESTED", case_id=case_id, correlation_id=corr,
                               data={"escalation_id": esc.escalation_id, "reason": reason,
                                     "recipient": ESCALATION_RECIPIENT, "simulated": True})
            if acknowledge:
                esc.status = EscalationStatus.ACKNOWLEDGED_REQUEST_ONLY
                esc.acknowledged_at = utc_now_iso()
                self.events.append("ESCALATION_ACKNOWLEDGED_REQUEST_ONLY", case_id=case_id, correlation_id=corr,
                                   actor=ESCALATION_RECIPIENT,
                                   data={"escalation_id": esc.escalation_id, "assistance_confirmed": False})
            else:
                esc.status = EscalationStatus.NO_ACKNOWLEDGMENT
                self.events.append("ESCALATION_NO_ACKNOWLEDGMENT", case_id=case_id, correlation_id=corr,
                                   data={"escalation_id": esc.escalation_id})
            esc.assistance_confirmed = False
            self.store.save_escalation(esc)
            for req in self.store.requests_for_case(case_id):
                if req.service_type == TRANSPORT and req.status not in (S.ACCEPTED, S.COMPLETED):
                    req.status = S.UNRESOLVED
                    self.store.save_request(req)
            if self._can_move(case, R.REQUIRES_COORDINATOR):
                self._set_resident_status(case, R.REQUIRES_COORDINATOR, reason=f"escalated: {reason}",
                                          correlation_id=corr)
            self._message_resident(case, "coordinator_followup", corr)
            case.next_step = (
                "Coordinator follows up with simulated authorized response service; assistance not confirmed."
                if acknowledge else
                "No acknowledgment received. Assistance not confirmed; coordinator must follow up (simulated).")
            self._save_case(case)
        return self._escalation_view(esc, case, corr), True

    def _transport_service_status(self, case_id: str) -> str:
        accepted = self.store.accepted_assignment(case_id, TRANSPORT)
        if accepted:
            return accepted.status
        reqs = [r for r in self.store.requests_for_case(case_id) if r.service_type == TRANSPORT]
        return reqs[-1].status if reqs else S.UNRESOLVED.value

    def _escalation_view(self, e: Escalation, case: Case, corr: str) -> dict[str, Any]:
        return {"escalation_id": e.escalation_id, "case_id": e.case_id, "reason": e.reason,
                "recipient": e.recipient, "status": e.status, "assistance_confirmed": False,
                "resident_status": case.resident_status,
                "service_status": self._transport_service_status(case.case_id),
                "next_step": case.next_step, "correlation_id": corr}

    # ================================================ simulator injections
    def inbound_sms(self, sender: str, text: str, external_id: Optional[str] = None,
                    language: Optional[str] = None) -> dict[str, Any]:
        """Route a simulated inbound SMS by sender. Unknown senders change nothing."""
        resident = next((r for r in self.store.list_residents()
                         if sender == r.contact_channel or (r.caregiver and sender == r.caregiver.contact_channel)),
                        None)
        case = self.store.case_for_resident(resident.resident_id) if resident else None
        if case is None:
            found = self.alerts.volunteer_by_phone(sender)
            if found:  # a volunteer answering outreach (YES/NO)
                return self.alerts.volunteer_reply(found, text, external_id)
            self.events.append("UNKNOWN_SENDER_REJECTED", case_id=None, data={"sender_known": False})
            raise Unauthorized("Unknown sender; no case updated", reasons=["UNKNOWN_SENDER"])
        return self.submit_resident_response(case.case_id, text, language, sender=sender, external_id=external_id)

    def set_delivery_outcome(self, message_id: str, delivered: bool) -> dict[str, Any]:
        msg = self.sim.set_outcome(message_id, delivered)
        case = self.store.get_case(msg.case_id) if msg.case_id else None
        if case is None:
            return {"message": msg.model_dump()}
        with self.db.tx():
            self.events.append("MESSAGE_DELIVERED" if delivered else "MESSAGE_DELIVERY_FAILED",
                               case_id=case.case_id, data={"message_id": message_id, "simulated": True})
            try:
                self._set_comm_status(case, C.DELIVERED if delivered else C.DELIVERY_FAILED,
                                      reason="simulated delivery receipt")
            except InvalidTransition:
                pass  # e.g. already REPLIED: a late receipt does not regress communication status
            if not delivered and case.communication_status == C.DELIVERY_FAILED:
                case.next_step = ("Check-in delivery FAILED (this is not 'no reply'). "
                                  "Try an alternate approved channel or coordinator follow-up.")
            self._save_case(case)
        return {"message": msg.model_dump(), "communication_status": case.communication_status}

    def _linked_sender(self, case: Case, resident, sender: str, via_doorstep_agent: bool) -> str:
        """Contract v2.2 (plan §0.5.1): an ASI:One sender is accepted only from the Doorstep agent
        (token checked by the API) and only if it is the address linked to this case's resident.
        It is then treated as the resident's own contact for the rest of the rules."""
        link = self.links.by_address(sender)
        if link is None:
            return sender  # not an ASI:One link: the normal contact check below applies (sim phone etc.)
        if via_doorstep_agent:
            if link["role"] == "RESIDENT" and link["person_id"] == case.resident_id:
                return resident.contact_channel
            self.events.append("UNKNOWN_SENDER_REJECTED", case_id=None,
                               data={"target_case_id": case.case_id, "sender_known": True, "via": "ASI_ONE"})
            raise Unauthorized("Sender is not the ASI:One account linked to this case", reasons=["UNKNOWN_SENDER"])
        if link:  # a linked ASI:One address must come through the Doorstep agent
            raise Unauthenticated("ASI:One senders are accepted only from the Doorstep agent",
                                  reasons=["DOORSTEP_AGENT_TOKEN_REQUIRED"])
        return sender

    def mark_no_reply_deadline(self, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        with self.db.tx():
            if case.communication_status in (C.SENT, C.DELIVERED):
                self._set_comm_status(case, C.NO_REPLY_AFTER_DEADLINE, reason="simulated reply deadline passed")
                resident = self.store.get_resident(case.resident_id)
                contact = "approved caregiver contact" if resident.caregiver else "coordinator follow-up"
                case.next_step = (f"No reply after deadline. Silence is NOT evidence of danger or of safety. "
                                  f"Next: {contact} (simulated).")
            elif case.communication_status == C.DELIVERY_FAILED:
                case.next_step = "Delivery failed earlier; status stays DELIVERY_FAILED (not 'no reply')."
            self.events.append("REPLY_DEADLINE_CHECKED", case_id=case_id,
                               data={"communication_status": case.communication_status})
            self._save_case(case)
        return self._response_view(case, case.correlation_id)

    # ====================================================== get_case_status
    def get_case_status(self, case_id: str, correlation_id: Optional[str] = None) -> dict[str, Any]:
        self.store.get_case(case_id)  # 404 before any side effect
        self.deadlines.apply()  # the 15-minute reply deadline holds even if no agent swept
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        corr = self._corr(case, correlation_id)
        requests = self.store.requests_for_case(case_id)
        escalations = self.store.escalations_for_case(case_id)
        referrals = self.store.referrals_for_case(case_id)
        transport = self.store.accepted_assignment(case_id, TRANSPORT)
        pending_transport = next((a for a in reversed(self.store.assignments_for_case(case_id, TRANSPORT))
                                  if a.status in (S.AWAITING_PROVIDER, S.PROPOSED)), None)
        shown = transport or pending_transport
        destination = self.store.accepted_assignment(case_id, DESTINATION)
        color, label = map_color(case.resident_status)
        replay_ok = (self.events.replay_resident_status(case_id) == case.resident_status
                     and self.events.replay_communication_status(case_id) == case.communication_status)
        unresolved = case.resident_status == R.REQUIRES_COORDINATOR or (
            case.resident_status != R.ARRIVAL_CONFIRMED and any(r.status == S.UNRESOLVED for r in requests)) or (
            # no reply by the deadline: coordinator follows up (silence is never safety)
            case.resident_status != R.ARRIVAL_CONFIRMED and case.communication_status == C.NO_REPLY_AFTER_DEADLINE)
        view = {
            "case_id": case.case_id,
            "resident_id": case.resident_id,
            "display_name": resident.display_name,
            "zone_id": case.zone_id,
            "zone_rule": self._zone_rule(case),
            "preferred_language": case.needs.preferred_language,
            "resident_status": case.resident_status,
            "communication_status": case.communication_status,
            "needs_confirmed": case.needs_confirmed,
            "consent": case.consent.model_dump(),
            "active_assignment": None if shown is None else {
                "assignment_id": shown.assignment_id, "provider_id": shown.provider_id,
                "service_status": shown.status, "confirmed_pickup_at": shown.confirmed_pickup_at,
                "confirmed_arrival_at": shown.confirmed_arrival_at,
                **({"org_id": shown.provider_id, "volunteer_id": shown.volunteer_id,
                    "vehicle_type": shown.vehicle_type, "assignment_status": shown.status,
                    "eta": {"minutes": shown.eta_minutes, "label": "Illustrative estimate, not a guarantee"}}
                   if shown.volunteer_id else {})},
            "escalations": [{"escalation_id": e.escalation_id, "reason": e.reason, "status": e.status,
                             "assistance_confirmed": False} for e in escalations],
            "referrals": [{"referral_id": r.referral_id, "status": r.status,
                           "shared_fields": sorted(r.shared_fields), "housing_secured": False} for r in referrals],
            "timeline": [self._timeline_item(e) for e in self.events.for_case(case_id)],
            "correlation_id": corr,
            # --- additions beyond contract v1.0 (safe to ignore) ---
            **self._zone_view(case.resident_id),
            "recovery": self.recovery.case_view(case.case_id),
            "route": self.routes.latest_for_case(case.case_id),
            "progress_steps": self.dashboard.progress_steps(case.case_id),
            "contact": self.links.contact("RESIDENT", case.resident_id),
            "reachability": self.links.reachability("RESIDENT", case.resident_id, resident.contact_channel),
            "reply_by": case.reply_by,
            "alert_id": case.alert_id,
            "sector_id": case.sector_id,
            "needs": case.needs.model_dump(),
            "destination_assignment": None if destination is None else {
                "assignment_id": destination.assignment_id, "provider_id": destination.provider_id,
                "service_status": destination.status, "site_id": destination.site_id},
            "map": {"color": color, "label": label},
            "unresolved": unresolved,
            "next_step": case.next_step,
            "evidence": {
                "provider_accepted": transport is not None,
                "pickup_confirmed": bool(transport and transport.confirmed_pickup_at),
                "arrival_confirmed": bool(transport and transport.confirmed_arrival_at),
                "destination_accepted": destination is not None,
                "timeline_replay_matches_status": replay_ok,
            },
            "simulated": True,
        }
        view["summary_text"] = self._summary_text(view, transport, destination, escalations, referrals)
        return view

    def _zone_view(self, resident_id: str) -> dict[str, Any]:
        profile = self.store.find_resident_profile(resident_id)
        if profile is None:
            return {"zone_status": "UNKNOWN", "zone_sources": []}
        zone = self.alerts.zone_for(profile)
        return {"zone_status": zone["zone_status"], "zone_sources": zone["zone_sources"]}

    @staticmethod
    def _timeline_item(e) -> dict[str, Any]:
        item = {"event_id": e.event_id, "type": e.event_type, "created_at": e.created_at, "actor": e.actor}
        if e.from_status or e.to_status:
            item.update({"from_status": e.from_status, "to_status": e.to_status})
        if "evidence" in e.data:
            item["evidence"] = e.data["evidence"]
        return item

    def _summary_text(self, view: dict, transport: Optional[Assignment], destination: Optional[Assignment],
                      escalations: list[Escalation], referrals: list[RecoveryReferral]) -> str:
        """Plain-text, evidence-backed summary (ASI:One text fallback)."""
        lines = [f"[SIMULATION] {view['display_name']} | case {view['case_id']} | {view['map']['label']} "
                 f"({view['map']['color']})"]
        if transport:
            t = f"Transport: {self._provider_name(transport.provider_id)} ACCEPTED"
            t += f"; pickup confirmed {transport.confirmed_pickup_at}" if transport.confirmed_pickup_at else "; pickup NOT yet confirmed"
            t += f"; arrival confirmed {transport.confirmed_arrival_at}" if transport.confirmed_arrival_at else "; arrival NOT yet confirmed"
            lines.append(t)
        else:
            lines.append("Transport: no provider acceptance.")
        if destination:
            lines.append(f"Destination: {self._provider_name(destination.provider_id)} accepted (simulated).")
        for e in escalations:
            lines.append(f"Escalation to {e.recipient}: {e.status}; assistance confirmed: NO.")
        for r in referrals:
            lines.append(f"Recovery referral: {r.status} (housing not secured).")
        if view["unresolved"]:
            lines.append("UNRESOLVED: assistance not confirmed.")
        lines.append(f"Next step: {view['next_step'] or '-'}")
        return "\n".join(lines)

    def list_cases(self, zone_id: Optional[str] = None, resident_status: Optional[str] = None,
                   unresolved_only: bool = False) -> list[dict[str, Any]]:
        out = []
        for case in self.store.list_cases(resident_status):
            if zone_id and zone_id not in (case.zone_id, case.sector_id):
                continue
            view = self.get_case_status(case.case_id)
            if unresolved_only and not view["unresolved"]:
                continue
            out.append({"case_id": case.case_id, "display_name": view["display_name"], "zone_id": case.zone_id,
                        "zone_rule": view["zone_rule"], "resident_status": case.resident_status,
                        "communication_status": case.communication_status, "map": view["map"],
                        "unresolved": view["unresolved"], "next_step": case.next_step})
        return out

    def registry_view(self) -> dict[str, Any]:
        return {"providers": [p.model_dump() for p in self.store.registry().values()],
                "organizations": self.registry.list_organizations(), "simulated": True}

    def zones_view(self) -> dict[str, Any]:
        return {
            "zones": [{"zone_id": z.zone_id, "label": z.label, "parent_zone": z.parent_zone,
                       "active_evacuation_order": z.active_evacuation_order} for z in self.graph.zones.values()],
            "edges": [{"zones": sorted(e), "km": km, "closed": e in self.graph.closed_edges}
                      for e, km in self.graph.edges.items()],
            "note": ROUTE_DISCLAIMER,
        }

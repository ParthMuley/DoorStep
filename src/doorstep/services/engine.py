"""DoorstepService: the authoritative implementation of the shared contract
(execution plan Section 2). The FastAPI app is a thin layer over this class.

Every state change happens inside one SQLite transaction together with the
timeline event that explains it, so displayed status == persisted evidence.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from doorstep.demo import seed
from doorstep.demo.synthetic_zone_graph import ZoneGraph, build_demo_graph
from doorstep.integrations.message_simulator import MessageSimulator
from doorstep.models import (
    AlertEvent,
    Assignment,
    Case,
    CommunicationStatus as C,
    ConsentGrant,
    Escalation,
    EscalationReason,
    EscalationStatus,
    Evidence,
    MessageDirection,
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
    DomainError,
    InvalidTransition,
    NotFound,
    SafetyRejection,
    Unauthorized,
)
from .event_log import EventLog
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


class DoorstepService:
    def __init__(self, db: Database, graph: Optional[ZoneGraph] = None):
        self.db = db
        self.store = Store(db)
        self.events = EventLog(db)
        self.sim = MessageSimulator(db, self.store)
        self.graph = graph or build_demo_graph()

    # ------------------------------------------------------------------ demo
    def reset(self) -> dict[str, Any]:
        """Wipe and reseed deterministic synthetic data."""
        self.db.wipe()
        self.graph = build_demo_graph()
        with self.db.tx():
            for o in seed.organizations():
                self.store.save_organization(o)
            for r in seed.residents():
                self.store.save_resident(r)
            for p in seed.transport_providers():
                self.store.save_transport_provider(p)
            for d in seed.destinations():
                self.store.save_destination(d)
            self.db.set_setting("escalation_ack", "true")
            self.events.append("DEMO_RESET", case_id=None, data={"simulated": True})
        return {"status": "reset", "residents": len(seed.residents()), "simulated": True}

    def set_escalation_ack(self, acknowledge: bool) -> dict[str, Any]:
        self.db.set_setting("escalation_ack", "true" if acknowledge else "false")
        return {"escalation_ack": acknowledge}

    # --------------------------------------------------------------- helpers
    def _corr(self, case: Case, correlation_id: Optional[str]) -> str:
        return correlation_id or case.correlation_id

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
        self.events.append("MESSAGE_SENT", case_id=case.case_id, correlation_id=msg.correlation_id,
                           data={"message_id": msg.message_id, "template_id": template_id, "simulated": True})
        return msg

    def _provider_name(self, service_type: str, provider_id: str) -> str:
        p = (self.store.get_transport_provider(provider_id) if service_type == TRANSPORT
             else self.store.get_destination(provider_id))
        return p.display_name if p else provider_id

    def _authorized_party_ids(self, resident: Resident) -> set[str]:
        ids = {resident.resident_id}
        if resident.caregiver:
            ids.add(resident.caregiver.caregiver_id)
        return ids

    # ------------------------------------------------- start_demo_warning
    def start_demo_warning(self, zone_id: str, scenario_id: Optional[str] = None,
                           correlation_id: Optional[str] = None) -> dict[str, Any]:
        """Simulated OFFICIAL warning (demo-authorized callers only). Creates
        check-in cases for residents in the zone and its child zones."""
        if zone_id not in self.graph.zones:
            raise NotFound(f"Unknown synthetic zone {zone_id!r}")
        covered = self.graph.zones_covered_by(zone_id)
        created, existing, skipped = [], [], []
        with self.db.tx():
            alert = AlertEvent(alert_id=self.db.next_id("alert"), zone_id=zone_id, official_verified=True,
                               scenario_id=scenario_id, created_at=utc_now_iso(),
                               message=f"SIMULATED official warning for {zone_id} (DEMO)")
            self.store.save_alert(alert)
            self.events.append("SIMULATED_OFFICIAL_WARNING", case_id=None, correlation_id=correlation_id or "",
                               actor="demo_control",
                               data={"alert_id": alert.alert_id, "zone_id": zone_id, "covered_zones": covered,
                                     "scenario_id": scenario_id, "simulated": True})
            for resident in self.store.list_residents():
                if resident.zone_id not in covered:
                    continue
                case_id = seed.CASE_IDS.get(resident.resident_id, f"case_{resident.resident_id}")
                if self.store.find_case(case_id):
                    existing.append(case_id)
                    continue
                case = Case(
                    case_id=case_id, resident_id=resident.resident_id, zone_id=resident.zone_id,
                    scenario_id=scenario_id, needs=resident.needs, consent=resident.consent,
                    alert_id=alert.alert_id, correlation_id=correlation_id or f"corr_{case_id}",
                    created_at=utc_now_iso(),
                )
                self.events.append("CASE_CREATED", case_id=case_id, correlation_id=case.correlation_id,
                                   data={"alert_id": alert.alert_id, "zone_id": resident.zone_id})
                if not resident.consent.contact_for_checkins:
                    case.next_step = "No check-in consent on file; coordinator decides next step."
                    skipped.append(case_id)
                else:
                    self._message_resident(case, "checkin")
                    self._set_comm_status(case, C.SENT, reason="simulated check-in sent")
                    case.next_step = "Awaiting resident reply. Silence is not evidence of danger or safety."
                    created.append(case_id)
                self._save_case(case)
        return {"alert": alert.model_dump(), "case_ids": created + skipped, "created": created,
                "already_existing": existing, "no_checkin_consent": skipped, "simulated": True}

    def report_hazard(self, zone_id: str, text: str, reporter: str = "public") -> dict[str, Any]:
        """A user report NEVER activates the official-warning flow."""
        with self.db.tx():
            alert = AlertEvent(alert_id=self.db.next_id("report"), zone_id=zone_id, official_verified=False,
                               created_at=utc_now_iso(), message="User report - requires verification (DEMO)")
            self.store.save_alert(alert)
            self.events.append("REPORT_RECORDED_REQUIRES_VERIFICATION", case_id=None,
                               data={"alert_id": alert.alert_id, "zone_id": zone_id, "reporter": reporter})
        return {"alert": alert.model_dump(), "activated_checkins": False,
                "note": "Report recorded for verification only. It is not an official warning."}

    # --------------------------------------------------- register_resident
    def register_resident(self, profile: Resident, consent: Optional[Any] = None) -> Resident:
        if consent is not None:
            profile = profile.model_copy(update={"consent": consent})
        profile = profile.model_copy(update={"last_confirmed_at": profile.last_confirmed_at or utc_now_iso()})
        with self.db.tx():
            self.store.save_resident(profile)
            self.events.append("RESIDENT_REGISTERED", case_id=None, data={"resident_id": profile.resident_id})
        return profile

    # -------------------------------------------- submit_resident_response
    def submit_resident_response(self, case_id: str, text: str, language: Optional[str] = None, *,
                                 sender: str, external_id: Optional[str] = None,
                                 correlation_id: Optional[str] = None) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        allowed = {resident.contact_channel}
        if resident.caregiver:
            allowed.add(resident.caregiver.contact_channel)
        if sender not in allowed:
            # Unknown sender must not change the case. Logged without case_id or text.
            self.events.append("UNKNOWN_SENDER_REJECTED", case_id=None,
                               data={"target_case_id": case_id, "sender_known": False})
            raise Unauthorized("Sender is not an authorized contact for this case",
                               reasons=["UNKNOWN_SENDER"])
        corr = self._corr(case, correlation_id)
        lang = language or case.needs.preferred_language
        external_id = external_id or self.db.next_id("inbound")

        if self.store.message_by_external_id(external_id):
            self.events.append("MESSAGE_DUPLICATE_IGNORED", case_id=case_id, correlation_id=corr,
                               data={"external_id": external_id})
            return {**self._response_view(case), "duplicate": True, "intent": None,
                    "candidate_needs": {}, "requires_confirmation": False, "confirmation_prompt": None}

        parsed = intake.extract(text, lang)
        prompt: Optional[str] = None
        with self.db.tx():
            msg = self.sim.record_inbound(case_id=case_id, sender=sender, body=text, language=lang,
                                          external_id=external_id, correlation_id=corr)
            self.events.append("MESSAGE_RECEIVED", case_id=case_id, correlation_id=corr,
                               data={"message_id": msg.message_id, "intent": parsed.intent,
                                     "parse_method": parsed.method})
            self._set_comm_status(case, C.REPLIED, reason="resident replied", correlation_id=corr)
            actor = "caregiver" if sender != resident.contact_channel else "resident"
            intent = parsed.intent

            if intent == ResponseIntent.CONFIRM_YES:
                if case.pending_candidate_needs is not None:
                    self._confirm(case, case.pending_candidate_needs, actor, corr)
                else:
                    self.events.append("CONFIRMATION_IGNORED_NOTHING_PENDING", case_id=case_id,
                                       correlation_id=corr)
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
                        prompt = self._message_resident(case, "confirm_needs", corr, summary=summary).body
                        case.next_step = "Awaiting resident confirmation of needs (YES/NO)."
                elif intent == ResponseIntent.CALL_ME:
                    if self._can_move(case, R.REQUIRES_COORDINATOR):
                        self._set_resident_status(case, R.REQUIRES_COORDINATOR, actor=actor,
                                                  reason="resident asked for a call", correlation_id=corr)
                    case.next_step = "Coordinator to call resident (simulated)."
                elif intent in (ResponseIntent.HAS_PLAN, ResponseIntent.ALREADY_LEFT):
                    case.next_step = ("Resident self-reported "
                                      f"{'having a plan' if intent == ResponseIntent.HAS_PLAN else 'already leaving'}"
                                      " (not verified). No assistance requested.")
                else:
                    case.next_step = "Coordinator to review an unparsed free-text reply."
            self._save_case(case)
        return {**self._response_view(case), "duplicate": False, "message_id": msg.message_id,
                "original_text": text, "intent": parsed.intent, "candidate_needs": parsed.candidate_needs,
                "requires_confirmation": case.pending_candidate_needs is not None,
                "confirmation_prompt": prompt}

    def _response_view(self, case: Case) -> dict[str, Any]:
        return {"case_id": case.case_id, "resident_status": case.resident_status,
                "communication_status": case.communication_status, "needs_confirmed": case.needs_confirmed,
                "pending_candidate_needs": case.pending_candidate_needs.model_dump()
                if case.pending_candidate_needs else None,
                "next_step": case.next_step}

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
        case.next_step = "Find eligible transport and destination offers."

    def _reject_candidates(self, case: Case, actor: str, corr: str) -> None:
        case.pending_candidate_needs = None
        case.needs_confirmed = False
        self.events.append("NEEDS_REJECTED_BY_RESIDENT", case_id=case.case_id, correlation_id=corr, actor=actor)
        if self._can_move(case, R.REQUIRES_COORDINATOR):
            self._set_resident_status(case, R.REQUIRES_COORDINATOR, actor=actor,
                                      reason="resident did not confirm extracted needs", correlation_id=corr)
        self._message_resident(case, "coordinator_followup", corr)
        case.next_step = "Coordinator to clarify needs with resident (simulated call)."

    def confirm_needs(self, case_id: str, *, confirmed: bool, confirmed_by: str,
                      needs: Optional[Needs] = None, correlation_id: Optional[str] = None) -> dict[str, Any]:
        """API alternative to replying YES/NO by SMS. confirmed_by must be the
        resident or their authorized caregiver."""
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        if confirmed_by not in self._authorized_party_ids(resident):
            raise Unauthorized("Only the resident or authorized caregiver can confirm needs")
        corr = self._corr(case, correlation_id)
        actor = "resident" if confirmed_by == resident.resident_id else "caregiver"
        with self.db.tx():
            if confirmed:
                chosen = needs or case.pending_candidate_needs or case.needs
                self._confirm(case, chosen, actor, corr)
            else:
                self._reject_candidates(case, actor, corr)
            self._save_case(case)
        return self._response_view(case)

    # ------------------------------------------- find_transport / destination
    def find_transport(self, case_id: str, correlation_id: Optional[str] = None) -> dict[str, Any]:
        return self._find(case_id, TRANSPORT, correlation_id)

    def find_destination(self, case_id: str, correlation_id: Optional[str] = None) -> dict[str, Any]:
        return self._find(case_id, DESTINATION, correlation_id)

    def _find(self, case_id: str, service_type: str, correlation_id: Optional[str]) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        corr = self._corr(case, correlation_id)
        if not case.needs_confirmed:
            raise Conflict("Resident needs must be confirmed before requesting offers",
                           reasons=["NEEDS_NOT_CONFIRMED"])
        if case.resident_status == R.UNKNOWN:
            raise Conflict("Resident has not requested assistance", reasons=["NO_ASSISTANCE_REQUESTED"])
        with self.db.tx():
            key = f"{case_id}:{'transport' if service_type == TRANSPORT else 'destination'}:v1"
            request = self.store.request_by_key(key)
            if request is None:
                if service_type == TRANSPORT:
                    reqs = {"transport_requirements": consent_rules.transport_requirements(case)}
                else:
                    reqs = {"destination_requirements": consent_rules.destination_requirements(case)}
                request = ServiceRequest(request_id=self.db.next_id("req"), case_id=case_id,
                                         service_type=service_type, zone_id=case.zone_id, status=S.DRAFT,
                                         idempotency_key=key, **reqs)
                self.events.append("SERVICE_REQUEST_CREATED", case_id=case_id, correlation_id=corr,
                                   data={"request_id": request.request_id, "service_type": service_type})

            make_id = lambda pid: f"offer_{request.request_id}_{pid}"  # noqa: E731
            if service_type == TRANSPORT:
                offers = matching.find_transport(request, self.store.list_transport_providers(), self.graph, make_id)
            else:
                offers = matching.find_destination(request, self.store.list_destinations(), self.graph, make_id)
            for o in offers:
                self.store.save_offer(o)
            eligible = [o for o in offers if o.eligible]

            active = [a for a in self.store.assignments_for_case(case_id, service_type)
                      if a.status in (S.AWAITING_PROVIDER, S.ACCEPTED, S.COMPLETED)]
            if not active:
                declined = {a.provider_id for a in self.store.assignments_for_case(case_id, service_type)
                            if a.status in TERMINAL_ASSIGNMENT_STATES}
                open_offers = [o for o in eligible if o.provider_id not in declined]
                request.status = S.PROPOSED if open_offers else S.UNRESOLVED
            self.store.save_request(request)
            self.events.append("OFFERS_EVALUATED", case_id=case_id, correlation_id=corr,
                               data={"request_id": request.request_id, "service_type": service_type,
                                     "eligible": [o.provider_id for o in eligible],
                                     "rejected": {o.provider_id: o.reasons for o in offers if not o.eligible}})

            if request.status == S.UNRESOLVED and service_type == TRANSPORT:
                inside = self.graph.is_active_order(case.zone_id)
                if self._can_move(case, R.REQUIRES_COORDINATOR):
                    self._set_resident_status(
                        case, R.REQUIRES_COORDINATOR, correlation_id=corr,
                        reason="inside active-order zone" if inside else "no eligible provider")
                case.next_step = (
                    "Inside a simulated active evacuation-order zone: ordinary volunteer dispatch is blocked. "
                    "Escalate to the simulated authorized response service."
                    if inside else "No eligible provider. Escalate per partner policy; case stays unresolved.")
                self._save_case(case)
            elif request.status == S.UNRESOLVED:
                case.next_step = "No eligible accessible destination. Coordinator follow-up required."
                self._save_case(case)
            elif request.status == S.PROPOSED:
                case.next_step = f"Propose an eligible {service_type.replace('_', ' ')} offer to the provider."
                self._save_case(case)

        return {"request": request.model_dump(), "offers": [self._offer_view(o, service_type) for o in offers],
                "eligible_count": len(eligible), "case_id": case_id,
                "resident_status": case.resident_status, "next_step": case.next_step,
                "route_note": ROUTE_DISCLAIMER}

    def _offer_view(self, o: Offer, service_type: str) -> dict[str, Any]:
        return {**o.model_dump(), "provider_name": self._provider_name(service_type, o.provider_id)}

    # --------------------------------------------------- propose_assignment
    def propose_assignment(self, case_id: str, offer_id: str, correlation_id: Optional[str] = None) -> Assignment:
        case = self.store.get_case(case_id)
        offer = self.store.get_offer(offer_id)
        corr = self._corr(case, correlation_id)
        if offer.case_id != case_id:
            raise Conflict("Offer does not belong to this case")
        request = self.store.get_request(offer.request_id)
        st = offer.service_type

        # Re-evaluate against CURRENT inventory: stale offers must not slip through.
        if st == TRANSPORT:
            provider = self.store.get_transport_provider(offer.provider_id)
            if provider is None:
                raise NotFound("Provider not found")
            reasons, _ = matching.evaluate_transport(request.transport_requirements, case.zone_id, provider, self.graph)
            approved, area_ok, rule = provider.approved, case.zone_id in provider.service_area_zones, zone_rule(self.graph, case.zone_id)
        else:
            dest = self.store.get_destination(offer.provider_id)
            if dest is None:
                raise NotFound("Destination not found")
            reasons, _ = matching.evaluate_destination(request.destination_requirements, case.zone_id, dest, self.graph)
            approved, area_ok, rule = dest.approved, True, zone_rule(self.graph, dest.zone_id)
        if reasons:
            self.events.append("ASSIGNMENT_REJECTED_BY_SAFETY", case_id=case_id, correlation_id=corr,
                               data={"offer_id": offer_id, "provider_id": offer.provider_id, "reasons": reasons})
            raise SafetyRejection("Offer fails deterministic eligibility/safety checks", reasons=reasons)

        if self.store.accepted_assignment(case_id, st):
            raise Conflict("Case already has an accepted assignment for this service",
                           reasons=["ALREADY_ACCEPTED"])

        key = f"{case_id}:{st}:{offer.provider_id}:v1"
        existing = self.store.assignment_by_key(key)
        if existing:
            if existing.status in TERMINAL_ASSIGNMENT_STATES:
                raise Conflict(f"Provider previously responded ({existing.status}); choose another offer",
                               reasons=[f"ASSIGNMENT_{existing.status}"])
            return existing  # idempotent re-proposal

        with self.db.tx():
            a = Assignment(
                assignment_id=self.db.next_id("assign"), case_id=case_id, request_id=request.request_id,
                offer_id=offer_id, provider_id=offer.provider_id, service_type=st,
                provider_approved=approved, service_area_allowed=area_ok, zone_rule=rule,
                authorization="SIMULATED_PREAPPROVED" if (approved and rule == ZoneRule.OUTSIDE_ACTIVE_ORDER)
                else "REQUIRES_AUTHORIZED_RESPONSE",
                status=S.AWAITING_PROVIDER, idempotency_key=key, correlation_id=corr,
                created_at=utc_now_iso(),
            )
            violations = assignment_safety_violations(a)
            if violations:  # belt and braces; matching should already have caught this
                raise SafetyRejection("Assignment blocked by safety gate", reasons=violations)
            self.store.save_assignment(a)
            request.status = S.AWAITING_PROVIDER
            self.store.save_request(request)
            self.events.append("ASSIGNMENT_PROPOSED", case_id=case_id, correlation_id=corr,
                               data={"assignment_id": a.assignment_id, "provider_id": a.provider_id,
                                     "service_type": st})
            case.next_step = f"Awaiting response from {self._provider_name(st, a.provider_id)}. Not confirmed yet."
            self._save_case(case)
        return a

    # ---------------------------------------------------- accept_assignment
    def respond_assignment(self, assignment_id: str, provider_id: str, accept: bool,
                           correlation_id: Optional[str] = None) -> dict[str, Any]:
        """Provider accepts or declines freely. Deduplicated; late replies to
        canceled/declined assignments never revive them."""
        a = self.store.get_assignment(assignment_id)
        case = self.store.get_case(a.case_id)
        corr = self._corr(case, correlation_id)
        if provider_id != a.provider_id:
            self.events.append("PROVIDER_IDENTITY_REJECTED", case_id=a.case_id, correlation_id=corr,
                               data={"assignment_id": assignment_id})
            raise Unauthorized("Provider identity does not match this assignment", reasons=["WRONG_PROVIDER"])
        record = (self.store.get_transport_provider(provider_id) if a.service_type == TRANSPORT
                  else self.store.get_destination(provider_id))
        if record is None or not record.approved:
            raise Unauthorized("Provider is not approved", reasons=["PROVIDER_NOT_APPROVED"])

        # Idempotent duplicates.
        if accept and a.status in (S.ACCEPTED, S.COMPLETED):
            return {"assignment": a.model_dump(), "duplicate": True, "resident_status": case.resident_status}
        if not accept and a.status == S.DECLINED:
            return {"assignment": a.model_dump(), "duplicate": True, "resident_status": case.resident_status}
        if a.status in (S.CANCELED, S.DECLINED, S.UNRESOLVED, S.COMPLETED):
            self.events.append("LATE_RESPONSE_IGNORED", case_id=a.case_id, correlation_id=corr,
                               data={"assignment_id": assignment_id, "assignment_status": a.status,
                                     "accept": accept})
            raise Conflict(f"Assignment is {a.status}; late response ignored", reasons=["LATE_RESPONSE"])

        try:
            with self.db.tx():
                if accept:
                    self._accept(a, case, record, corr)
                elif a.status == S.ACCEPTED:
                    self._provider_cancel(a, case, corr)
                else:
                    self._decline(a, case, corr)
                self._save_case(case)
        except sqlite3.IntegrityError as exc:
            raise Conflict("Another assignment for this service was already accepted",
                           reasons=["DUPLICATE_ACCEPTANCE"]) from exc
        return {"assignment": self.store.get_assignment(assignment_id).model_dump(), "duplicate": False,
                "resident_status": case.resident_status, "next_step": case.next_step}

    def _accept(self, a: Assignment, case: Case, record: Any, corr: str) -> None:
        violations = assignment_safety_violations(a)
        if violations:
            raise SafetyRejection("Assignment fails safety gate", reasons=violations)
        if a.service_type == TRANSPORT:
            if not record.available or record.available_trips < 1:
                raise Conflict("Provider has no remaining capacity", reasons=["NO_AVAILABLE_CAPACITY"])
            record.available_trips -= 1
            self.store.save_transport_provider(record)
        else:
            if record.available_capacity < 1:
                raise Conflict("Destination has no remaining capacity", reasons=["NO_AVAILABLE_CAPACITY"])
            record.available_capacity -= 1
            self.store.save_destination(record)

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
        request = self.store.get_request(a.request_id)
        request.status = S.ACCEPTED
        self.store.save_request(request)
        self.events.append("PROVIDER_ACCEPTED", case_id=a.case_id, correlation_id=corr, actor=a.provider_id,
                           data={"assignment_id": a.assignment_id, "service_type": a.service_type,
                                 "authorization": a.authorization})
        name = self._provider_name(a.service_type, a.provider_id)
        if a.service_type == TRANSPORT:
            self._set_resident_status(case, R.PROVIDER_ACCEPTED, assignment=a, actor=a.provider_id,
                                      reason="transport provider accepted", correlation_id=corr)
            self._message_resident(case, "provider_accepted", corr, provider=name)
            case.next_step = "Awaiting pickup confirmation from provider and resident."
        else:
            case.next_step = (f"Destination {name} accepted (simulated reservation). "
                              + ("Awaiting pickup confirmation." if case.resident_status == R.PROVIDER_ACCEPTED
                                 else "Transport still needed."))

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
            raise Conflict("Pickup already confirmed; coordinator must handle this change",
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
        request = self.store.get_request(a.request_id)
        tried = {x.provider_id for x in self.store.assignments_for_case(a.case_id, a.service_type)
                 if x.status in TERMINAL_ASSIGNMENT_STATES}
        pending = [x for x in self.store.assignments_for_case(a.case_id, a.service_type)
                   if x.status in (S.AWAITING_PROVIDER, S.ACCEPTED)]
        alternates = [o for o in self.store.offers_for_request(request.request_id)
                      if o.eligible and o.provider_id not in tried]
        if pending:
            request.status = S.AWAITING_PROVIDER
        elif alternates:
            request.status = S.PROPOSED
            case.next_step = ("Provider declined. Alternate eligible offer available: "
                              f"{alternates[0].offer_id} ({self._provider_name(a.service_type, alternates[0].provider_id)}).")
        else:
            request.status = S.UNRESOLVED
            if a.service_type == TRANSPORT and self._can_move(case, R.REQUIRES_COORDINATOR):
                self._set_resident_status(case, R.REQUIRES_COORDINATOR, reason="no remaining eligible provider",
                                          correlation_id=corr)
            case.next_step = "No remaining eligible provider. Unresolved: escalate per partner policy."
        self.store.save_request(request)

    def get_pickup_details(self, assignment_id: str, provider_id: str) -> dict[str, Any]:
        """Synthetic pickup point, released only to the approved provider that
        accepted, and only with transport-sharing consent."""
        a = self.store.get_assignment(assignment_id)
        if a.service_type != TRANSPORT or provider_id != a.provider_id:
            raise Unauthorized("Not the transport provider for this assignment")
        provider = self.store.get_transport_provider(provider_id)
        if provider is None or not provider.approved:
            raise Unauthorized("Provider is not approved", reasons=["PROVIDER_NOT_APPROVED"])
        if a.status != S.ACCEPTED:
            raise Unauthorized("Pickup details are released only after acceptance", reasons=["NOT_ACCEPTED"])
        case = self.store.get_case(a.case_id)
        consent_rules.transport_requirements(case)  # raises ConsentRequired if missing
        resident = self.store.get_resident(case.resident_id)
        self.events.append("PICKUP_DETAILS_RELEASED", case_id=case.case_id, correlation_id=case.correlation_id,
                           actor=provider_id, data={"assignment_id": assignment_id})
        return {"assignment_id": assignment_id, "zone_id": case.zone_id, "pickup_point": resident.pickup_point,
                "simulated": True, "route_note": ROUTE_DISCLAIMER}

    # ------------------------------------------------ pickup / arrival
    def confirm_pickup(self, assignment_id: str, evidence: Evidence,
                       correlation_id: Optional[str] = None) -> dict[str, Any]:
        a = self.store.get_assignment(assignment_id)
        case = self.store.get_case(a.case_id)
        corr = self._corr(case, correlation_id)
        if a.service_type != TRANSPORT:
            raise Conflict("Pickup applies to transport assignments only")
        if a.confirmed_pickup_at:
            return {"assignment": a.model_dump(), "duplicate": True, "resident_status": case.resident_status}
        if a.status != S.ACCEPTED:
            raise InvalidTransition(f"Assignment is {a.status}; pickup requires an accepted assignment")
        resident = self.store.get_resident(case.resident_id)
        verification.check_pickup_evidence(evidence, resident, a)
        with self.db.tx():
            a.confirmed_pickup_at = utc_now_iso()
            a.updated_at = a.confirmed_pickup_at
            self.store.save_assignment(a)
            v = VerificationEvent(verification_id=self.db.next_id("verif"), case_id=case.case_id,
                                  assignment_id=assignment_id, kind="pickup", evidence=evidence, correlation_id=corr)
            self.store.save_verification(v)
            self.events.append("PICKUP_CONFIRMED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": assignment_id, "verification_id": v.verification_id,
                                     "parties": [c.party for c in evidence.confirmations]})
            self._set_resident_status(case, R.PICKUP_CONFIRMED, assignment=a, reason="pickup evidence recorded",
                                      correlation_id=corr)
            case.next_step = "Awaiting arrival confirmation at the agreed destination."
            self._save_case(case)
        return {"assignment": a.model_dump(), "duplicate": False, "resident_status": case.resident_status}

    def confirm_arrival(self, assignment_id: str, evidence: Evidence,
                        correlation_id: Optional[str] = None) -> dict[str, Any]:
        a = self.store.get_assignment(assignment_id)
        case = self.store.get_case(a.case_id)
        corr = self._corr(case, correlation_id)
        if a.service_type != TRANSPORT:
            raise Conflict("Arrival is confirmed on the transport assignment")
        if a.confirmed_arrival_at:
            return {"assignment": a.model_dump(), "duplicate": True, "resident_status": case.resident_status}
        if not a.confirmed_pickup_at:
            raise InvalidTransition("Arrival requires a confirmed pickup first", reasons=["PICKUP_NOT_CONFIRMED"])
        destination = self.store.accepted_assignment(case.case_id, DESTINATION)
        if destination is None:
            raise Conflict("No accepted destination; arrival must be at an agreed destination",
                           reasons=["NO_AGREED_DESTINATION"])
        resident = self.store.get_resident(case.resident_id)
        verification.check_arrival_evidence(evidence, resident, a, destination)
        with self.db.tx():
            a.confirmed_arrival_at = utc_now_iso()
            a.status = S.COMPLETED
            a.updated_at = a.confirmed_arrival_at
            self.store.save_assignment(a)
            request = self.store.get_request(a.request_id)
            request.status = S.COMPLETED
            self.store.save_request(request)
            v = VerificationEvent(verification_id=self.db.next_id("verif"), case_id=case.case_id,
                                  assignment_id=assignment_id, kind="arrival", evidence=evidence, correlation_id=corr)
            self.store.save_verification(v)
            self.events.append("ARRIVAL_CONFIRMED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": assignment_id, "verification_id": v.verification_id,
                                     "destination_assignment_id": destination.assignment_id,
                                     "parties": [c.party for c in evidence.confirmations]})
            self._set_resident_status(case, R.ARRIVAL_CONFIRMED, assignment=a, reason="arrival evidence recorded",
                                      correlation_id=corr)
            dest_name = self._provider_name(DESTINATION, destination.provider_id)
            self._message_resident(case, "arrival_confirmed", corr, destination=dest_name)
            case.next_step = "Ask resident for consent before any recovery-support referral."
            self._save_case(case)
        return {"assignment": a.model_dump(), "duplicate": False, "resident_status": case.resident_status}

    # --------------------------------------------- recovery handoff
    def request_recovery_handoff(self, case_id: str, consent: bool, granted_by: str,
                                 correlation_id: Optional[str] = None) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        if granted_by not in self._authorized_party_ids(resident):
            raise Unauthorized("Only the resident or authorized caregiver can grant consent")
        corr = self._corr(case, correlation_id)
        with self.db.tx():
            self.store.add_consent_grant(ConsentGrant(case_id=case_id, scope="share_recovery_needs",
                                                      granted=consent, granted_by=granted_by,
                                                      created_at=utc_now_iso()))
            case.consent = case.consent.model_copy(update={"share_recovery_needs": consent})
            if not consent:
                self.events.append("RECOVERY_CONSENT_DECLINED", case_id=case_id, correlation_id=corr)
                case.next_step = "Resident declined recovery referral. Nothing shared."
                self._save_case(case)
                return {"case_id": case_id, "consent_granted": False, "referral": None, "shared_fields": {}}

            key = f"{case_id}:recovery:v1"
            referral = self.store.referral_by_key(key)
            if referral is None:
                payload = consent_rules.recovery_payload(case)
                referral = RecoveryReferral(referral_id=self.db.next_id("ref"), case_id=case_id,
                                            provider_id=RECOVERY_PROVIDER_ID, shared_fields=payload,
                                            idempotency_key=key, correlation_id=corr)
                self.store.save_referral(referral)
                self.events.append("RECOVERY_CONSENT_GRANTED", case_id=case_id, correlation_id=corr)
                self.events.append("RECOVERY_REFERRAL_REQUESTED", case_id=case_id, correlation_id=corr,
                                   data={"referral_id": referral.referral_id, "provider_id": RECOVERY_PROVIDER_ID,
                                         "field_names": sorted(payload)})
            case.next_step = "Recovery referral REQUESTED. Housing is not secured unless the provider confirms."
            self._save_case(case)
        return {"case_id": case_id, "consent_granted": True, "referral": referral.model_dump(),
                "shared_fields": referral.shared_fields}

    def respond_recovery(self, referral_id: str, provider_id: str, accept: bool,
                         correlation_id: Optional[str] = None) -> RecoveryReferral:
        """Simulated recovery-provider response. ACCEPTED means the follow-up
        request was accepted -- not that housing is secured."""
        referral = self.store.get_referral(referral_id)
        if provider_id != referral.provider_id:
            raise Unauthorized("Provider identity does not match this referral")
        target = ReferralStatus.ACCEPTED if accept else ReferralStatus.UNRESOLVED
        if referral.status == target:
            return referral
        if referral.status != ReferralStatus.REQUESTED:
            raise Conflict(f"Referral already {referral.status}", reasons=["LATE_RESPONSE"])
        case = self.store.get_case(referral.case_id)
        corr = self._corr(case, correlation_id)
        with self.db.tx():
            referral.status = target
            referral.updated_at = utc_now_iso()
            self.store.save_referral(referral)
            self.events.append(f"RECOVERY_REFERRAL_{target.value}", case_id=case.case_id, correlation_id=corr,
                               actor=provider_id, data={"referral_id": referral_id})
            case.next_step = ("Recovery follow-up request accepted by simulated provider (not housing secured)."
                              if accept else "Recovery referral unresolved; coordinator follow-up.")
            self._save_case(case)
        return referral

    # ------------------------------------------------------- escalate_case
    def escalate_case(self, case_id: str, reason: str, correlation_id: Optional[str] = None) -> Escalation:
        """Simulated escalation. Never contacts 911; acknowledgment == received only."""
        reason = EscalationReason(reason).value
        case = self.store.get_case(case_id)
        corr = self._corr(case, correlation_id)
        if reason == EscalationReason.ACTIVE_EVACUATION_ORDER_ZONE and not self.graph.is_active_order(case.zone_id):
            raise Conflict("Case zone is not inside a simulated active-order zone", reasons=["REASON_MISMATCH"])
        if case.resident_status == R.ARRIVAL_CONFIRMED:
            raise Conflict("Arrival already confirmed; nothing to escalate")
        key = f"{case_id}:escalation:{reason}"
        existing = self.store.escalation_by_key(key)
        if existing:
            return existing
        acknowledge = self.db.get_setting("escalation_ack", "true") == "true"
        with self.db.tx():
            esc = Escalation(escalation_id=self.db.next_id("esc"), case_id=case_id, reason=reason,
                             recipient=ESCALATION_RECIPIENT, idempotency_key=key, correlation_id=corr)
            self.events.append("ESCALATION_SENT", case_id=case_id, correlation_id=corr,
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
                "Simulated authorized response service acknowledged RECEIPT ONLY. Assistance NOT confirmed; "
                "coordinator owns follow-up." if acknowledge else
                "No acknowledgment received. Assistance NOT confirmed; coordinator must follow up (simulated).")
            self._save_case(case)
        return esc

    # ------------------------------------------------ simulator injections
    def inbound_sms(self, sender: str, text: str, external_id: Optional[str] = None,
                    language: Optional[str] = None) -> dict[str, Any]:
        """Route a simulated inbound SMS by sender. Unknown senders change nothing."""
        resident = next((r for r in self.store.list_residents()
                         if sender == r.contact_channel or (r.caregiver and sender == r.caregiver.contact_channel)),
                        None)
        case = self.store.case_for_resident(resident.resident_id) if resident else None
        if case is None:
            self.events.append("UNKNOWN_SENDER_REJECTED", case_id=None, data={"sender_known": False})
            raise Unauthorized("Unknown sender; no case updated", reasons=["UNKNOWN_SENDER"])
        return self.submit_resident_response(case.case_id, text, language, sender=sender, external_id=external_id)

    def set_delivery_outcome(self, message_id: str, delivered: bool) -> dict[str, Any]:
        msg = self.sim.set_outcome(message_id, delivered)
        case = self.store.get_case(msg.case_id) if msg.case_id else None
        if case is None:
            return {"message": msg.model_dump()}
        target = C.DELIVERED if delivered else C.DELIVERY_FAILED
        with self.db.tx():
            self.events.append("MESSAGE_DELIVERED" if delivered else "MESSAGE_DELIVERY_FAILED",
                               case_id=case.case_id, data={"message_id": message_id, "simulated": True})
            try:
                self._set_comm_status(case, target, reason="simulated delivery receipt")
            except InvalidTransition:
                pass  # e.g. already REPLIED: a late receipt does not regress communication status
            if not delivered and case.communication_status == C.DELIVERY_FAILED:
                case.next_step = ("Check-in delivery FAILED (this is not 'no reply'). "
                                  "Try an alternate approved channel or coordinator follow-up.")
            self._save_case(case)
        return {"message": msg.model_dump(), "communication_status": case.communication_status}

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
        return self._response_view(case)

    # ------------------------------------------------------ get_case_status
    def get_case_status(self, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        resident = self.store.get_resident(case.resident_id)
        assignments = self.store.assignments_for_case(case_id)
        requests = self.store.requests_for_case(case_id)
        escalations = self.store.escalations_for_case(case_id)
        referrals = self.store.referrals_for_case(case_id)
        timeline = self.events.for_case(case_id)
        color, label = map_color(case.resident_status)
        transport = self.store.accepted_assignment(case_id, TRANSPORT)
        destination = self.store.accepted_assignment(case_id, DESTINATION)
        replay_ok = (self.events.replay_resident_status(case_id) == case.resident_status
                     and self.events.replay_communication_status(case_id) == case.communication_status)
        unresolved = case.resident_status == R.REQUIRES_COORDINATOR or (
            case.resident_status != R.ARRIVAL_CONFIRMED and any(r.status == S.UNRESOLVED for r in requests))
        view = {
            "case": case.model_dump(),
            "resident_label": resident.display_name,
            "map": {"color": color, "label": label, "zone_id": case.zone_id,
                    "zone_label": self.graph.zones[case.zone_id].label if case.zone_id in self.graph.zones else "",
                    "inside_active_order": self.graph.is_active_order(case.zone_id)},
            "evidence": {
                "provider_accepted": transport is not None,
                "pickup_confirmed": bool(transport and transport.confirmed_pickup_at),
                "arrival_confirmed": bool(transport and transport.confirmed_arrival_at),
                "destination_accepted": destination is not None,
                "assistance_confirmed": transport is not None,
                "timeline_replay_matches_status": replay_ok,
            },
            "unresolved": unresolved,
            "next_step": case.next_step,
            "service_requests": [r.model_dump() for r in requests],
            "offers": [self._offer_view(o, o.service_type) for o in self.store.offers_for_case(case_id)],
            "assignments": [{**a.model_dump(), "provider_name": self._provider_name(a.service_type, a.provider_id)}
                            for a in assignments],
            "verifications": [v.model_dump() for v in self.store.verifications_for_case(case_id)],
            "escalations": [e.model_dump() for e in escalations],
            "recovery_referrals": [r.model_dump(exclude={"shared_fields"}) | {"shared_field_names": sorted(r.shared_fields)}
                                   for r in referrals],
            "consent_grants": [g.model_dump() for g in self.store.consent_grants_for_case(case_id)],
            "messages": [m.model_dump() for m in self.store.list_messages(case_id)],
            "timeline": [e.model_dump() for e in timeline],
            "simulated": True,
        }
        view["summary_text"] = self._summary_text(view, transport, destination, escalations, referrals)
        return view

    def _summary_text(self, view: dict, transport: Optional[Assignment], destination: Optional[Assignment],
                      escalations: list[Escalation], referrals: list[RecoveryReferral]) -> str:
        """Plain-text, evidence-backed summary (ASI:One text fallback)."""
        case = view["case"]
        lines = [f"[SIMULATION] {view['resident_label']} | case {case['case_id']} | {view['map']['label']} "
                 f"({view['map']['color']})"]
        if transport:
            t = f"Transport: {self._provider_name(TRANSPORT, transport.provider_id)} ACCEPTED"
            t += f"; pickup confirmed {transport.confirmed_pickup_at}" if transport.confirmed_pickup_at else "; pickup NOT yet confirmed"
            t += f"; arrival confirmed {transport.confirmed_arrival_at}" if transport.confirmed_arrival_at else "; arrival NOT yet confirmed"
            lines.append(t)
        else:
            lines.append("Transport: no provider acceptance.")
        if destination:
            lines.append(f"Destination: {self._provider_name(DESTINATION, destination.provider_id)} accepted (simulated).")
        for e in escalations:
            lines.append(f"Escalation to {e.recipient}: {e.status}; assistance confirmed: NO.")
        for r in referrals:
            lines.append(f"Recovery referral: {r.status} (not housing secured).")
        if view["unresolved"]:
            lines.append("UNRESOLVED: assistance not confirmed.")
        lines.append(f"Next step: {view['next_step'] or '-'}")
        return "\n".join(lines)

    def list_cases(self, resident_status: Optional[str] = None, unresolved_only: bool = False) -> list[dict[str, Any]]:
        out = []
        for case in self.store.list_cases(resident_status):
            view = self.get_case_status(case.case_id)
            if unresolved_only and not view["unresolved"]:
                continue
            out.append({"case_id": case.case_id, "resident_label": view["resident_label"],
                        "zone_id": case.zone_id, "resident_status": case.resident_status,
                        "communication_status": case.communication_status, "map": view["map"],
                        "unresolved": view["unresolved"], "next_step": case.next_step})
        return out

    def providers_view(self) -> dict[str, Any]:
        return {
            "transport": [p.model_dump() for p in self.store.list_transport_providers()],
            "destinations": [d.model_dump() for d in self.store.list_destinations()],
            "organizations": [o.model_dump() for o in self.store.list_organizations()],
            "simulated": True,
        }

    def zones_view(self) -> dict[str, Any]:
        return {
            "zones": [{"zone_id": z.zone_id, "label": z.label, "parent_zone": z.parent_zone,
                       "active_evacuation_order": z.active_evacuation_order} for z in self.graph.zones.values()],
            "edges": [{"zones": sorted(e), "km": km, "closed": e in self.graph.closed_edges}
                      for e, km in self.graph.edges.items()],
            "note": ROUTE_DISCLAIMER,
        }


__all__ = ["DoorstepService", "DomainError"]

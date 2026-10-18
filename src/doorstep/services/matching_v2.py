"""Contract v2.0 matching, acceptance and escalation (§5.6–§5.7).

Matches a resident with a volunteer who answered AVAILABLE for this alert (org DB)
and a shelter site; reserves the volunteer atomically; org agents accept/decline
on the same assignment id; escalation is REQUESTED then acknowledged (receipt only).
Pickup/arrival reuse the engine's evidence rules.
"""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any, Optional

from pymongo.errors import DuplicateKeyError

from doorstep.models import (
    Assignment,
    Case,
    CommunicationStatus as C,
    Escalation,
    EscalationReason,
    EscalationStatus,
    ProviderResponse,
    ResidentStatus as R,
    ServiceRequest,
    ServiceStatus as S,
    ServiceType,
    ZoneRule,
    utc_now_iso,
)

from . import geo
from .errors import Conflict, ConsentRequired, InvalidTransition, NotFound, SafetyRejection, Unauthorized
from .volunteer_matching import Candidate, apply_drive_times, eta_minutes, evaluate_shelters, evaluate_volunteers

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

TRANSPORT = ServiceType.ACCESSIBLE_TRANSPORT.value
DESTINATION = ServiceType.ACCESSIBLE_DESTINATION.value
PREAPPROVED = "SIMULATED_PREAPPROVED"
BLOCKING_ZONES = {"ORDER": ("ORDER_ZONE", "UNSAFE_ZONE"), "STALE": ("ZONE_STALE", "ZONE_STALE"),
                  "UNKNOWN": ("ZONE_UNKNOWN", "ZONE_UNKNOWN")}
ETA_LABEL = "Illustrative estimate, not a guarantee"
RECIPIENT = "SIMULATED_AUTHORIZED_RESPONSE_SERVICE"


class MatchService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store
        self.events = engine.events

    # ------------------------------------------------------------- context
    def _context(self, case: Case) -> dict[str, Any]:
        profile = self.store.get_resident_profile(case.resident_id)
        zone = self.engine.alerts.zone_for(profile)
        alert = None
        if case.alert_id:
            try:
                alert = self.engine.alerts.get_alert(case.alert_id)
            except NotFound:
                alert = None
        order_polygons = [g for g in (geo.polygon(a.geometry) for a in self.engine.alerts._alerts(
            {"active": True, "source_type": "OFFICIAL_SIMULATION", "status": "ORDER"})) if g is not None]
        transport_rows = self.store.assignments_for_case(case.case_id, TRANSPORT)
        shelter_rows = self.store.assignments_for_case(case.case_id, DESTINATION)
        return {
            "profile": profile, "zone": zone, "alert": alert,
            "alert_id": alert.alert_id if alert else None,
            "event_alert_ids": self.engine.alerts.same_event_alert_ids(alert.alert_id if alert else None),
            "calamity": alert.calamity_type if alert else "UNKNOWN",
            "orders": order_polygons, "entries": list(self.store.partners.entries()),
            "declined_volunteers": {a.volunteer_id for a in transport_rows
                                    if a.volunteer_id and a.status in (S.DECLINED, S.CANCELED)},
            "declined_sites": {a.site_id for a in shelter_rows if a.site_id and a.status in (S.DECLINED, S.CANCELED)},
        }

    def _evaluate(self, case: Case, ctx: dict[str, Any]) -> tuple[list[Candidate], list[Candidate]]:
        vols = evaluate_volunteers(ctx["profile"], case.case_id, ctx["event_alert_ids"], ctx["calamity"],
                                   ctx["entries"], ctx["orders"], ctx["declined_volunteers"])
        sites = [c for c in evaluate_shelters(ctx["profile"], ctx["calamity"], ctx["entries"], ctx["orders"])]
        for c in sites:
            if c.entity_id in ctx["declined_sites"] and c.eligible:
                c.eligible, c.reason_codes, c.rank = False, ["ALREADY_DECLINED"], None
        blocked = BLOCKING_ZONES.get(ctx["zone"]["zone_status"])
        if blocked:  # the resident's own zone blocks every ordinary volunteer assignment
            for c in vols:
                rest = [r for r in c.reason_codes if r != "ROUTE_THROUGH_ORDER_ZONE"] if not c.eligible else []
                c.eligible, c.rank = False, None
                c.reason_codes = [blocked[0]] + rest
        return vols, sites

    @staticmethod
    def _split(cands: list[Candidate], kind: str) -> dict[str, list[dict]]:
        return {"eligible": [c.view(kind) for c in cands if c.eligible],
                "rejected": [c.view(kind) for c in cands if not c.eligible]}

    def _available_count(self, ctx: dict[str, Any]) -> int:
        return sum(1 for _r, o in ctx["entries"] if o.approved and "TRANSPORT" in o.services for v in o.volunteers
                   if v.approved and v.availability and v.availability.alert_id in ctx["event_alert_ids"]
                   and v.availability.state == "AVAILABLE")

    # ------------------------------------------------------------- propose
    def propose(self, case_id: str, *, idempotency_key: Optional[str] = None, create_proposal: bool = True,
                authorization: str = PREAPPROVED, select_volunteer: Optional[str] = None,
                select_site: Optional[str] = None, correlation_id: Optional[str] = None,
                drive_minutes: Optional[dict[str, float]] = None) -> tuple[dict, bool]:
        eng = self.engine
        case = self.store.get_case(case_id)
        eng.deadlines.apply()  # volunteers past their reply deadline count as NO_REPLY
        case = self.store.get_case(case_id)
        corr = eng._corr(case, correlation_id)
        key = idempotency_key or f"{case_id}:match:v1"
        if create_proposal:
            prior = self.db.coll("match_results").find_one({"_id": key})
            if prior:
                return {**{k: v for k, v in prior.items() if not k.startswith("_")}, "duplicate": True}, False
        if not case.needs_confirmed:
            raise Conflict("Resident needs must be confirmed before matching", code="NEEDS_NOT_CONFIRMED")
        if case.resident_status == R.UNKNOWN:
            raise Conflict("Resident has not requested assistance", code="NO_ASSISTANCE_REQUESTED")
        profile = self.store.get_resident_profile(case.resident_id)
        if not profile.consents.get("TRANSPORT"):
            raise ConsentRequired("Resident has not consented to share transport needs")
        if authorization != PREAPPROVED:
            raise SafetyRejection("Only SIMULATED_PREAPPROVED arrangements can be proposed", code="NOT_AUTHORIZED",
                                  reasons=["NOT_PREAPPROVED"])

        ctx = self._context(case)
        vols, sites = self._evaluate(case, ctx)
        ignored = apply_drive_times(vols, drive_minutes)  # re-orders eligible only; eligibility unchanged
        zone_status = ctx["zone"]["zone_status"]
        blocked = BLOCKING_ZONES.get(zone_status)
        base = {"case_id": case_id, "alert_id": ctx["alert_id"], "zone_status": zone_status,
                "evaluation": {"volunteers": self._split(vols, "volunteer"), "shelters": self._split(sites, "shelter")},
                "ranking": "DRIVE_TIME" if drive_minutes else "DISTANCE",
                "correlation_id": corr}
        if ignored:
            base["drive_minutes_ignored"] = ignored

        if blocked and (select_volunteer or select_site):
            raise SafetyRejection(f"Resident zone is {zone_status}", code=blocked[1], reasons=[blocked[0]])
        if not create_proposal:
            return {**base, "escalation_required": bool(blocked), "no_match_reason": blocked[0] if blocked else None,
                    "match": None, "duplicate": False}, False

        open_rows = [a for a in self.store.assignments_for_case(case_id, TRANSPORT)
                     if a.status in (S.PROPOSED, S.AWAITING_PROVIDER, S.ACCEPTED)]
        if any(a.status == S.ACCEPTED for a in open_rows):
            raise Conflict("Case already has an accepted volunteer", code="ALREADY_ACCEPTED")
        if open_rows:
            raise Conflict("A match is already awaiting the volunteer's answer", code="MATCH_PENDING")

        if blocked:
            return self._no_match(case, base, blocked[0], corr, key), False

        # ---- choose and reserve a volunteer (atomic; first eligible that can be reserved wins)
        chosen: Optional[Candidate] = None
        if select_volunteer:
            cand = next((c for c in vols if c.entity_id == select_volunteer), None)
            if cand is None:
                raise NotFound(f"Volunteer {select_volunteer!r} not found")
            if not cand.eligible:
                code = "ALREADY_RESERVED" if "ALREADY_RESERVED" in cand.reason_codes else "NOT_ELIGIBLE"
                raise Conflict("Selected volunteer is not eligible", code=code, reasons=cand.reason_codes)
            order = [cand]
        else:
            order = [c for c in vols if c.eligible]
        for cand in order:
            if self.store.partners.reserve_volunteer(cand.entity_id, case_id, ctx["event_alert_ids"]):
                chosen = cand
                break
            if select_volunteer:
                raise Conflict("Selected volunteer was just reserved by another case", code="ALREADY_RESERVED")
        if chosen is None:
            reason = "NO_SUITABLE_VOLUNTEER" if self._available_count(ctx) else "NO_AVAILABLE_VOLUNTEER"
            return self._no_match(case, base, reason, corr, key), False

        # ---- shelter: keep an already-accepted one, else select / top eligible
        shelter_row = self.store.accepted_assignment(case_id, DESTINATION)
        site: Optional[Candidate] = None
        if shelter_row is None:
            if not profile.consents.get("DESTINATION"):
                self.store.partners.release_volunteer(chosen.entity_id, case_id)
                raise ConsentRequired("Resident has not consented to share destination needs")
            pool = [c for c in sites if c.eligible and (not select_site or c.entity_id == select_site)]
            if select_site and not pool:
                self.store.partners.release_volunteer(chosen.entity_id, case_id)
                raise Conflict("Selected shelter site is not eligible", code="NOT_ELIGIBLE")
            site = pool[0] if pool else None
            if site is None:
                self.store.partners.release_volunteer(chosen.entity_id, case_id)
                return self._no_match(case, base, "NO_SHELTER", corr, key, transport_unresolved=False), False

        with self.db.tx():
            request_id = f"match_{case_id}"
            for st in (TRANSPORT, DESTINATION):
                rkey = f"{case_id}:{st}:{request_id}"
                req = self.store.request_by_key(rkey) or ServiceRequest(
                    request_id=request_id, case_id=case_id, service_type=st, zone_id=case.zone_id,
                    status=S.DRAFT, idempotency_key=rkey)
                req.status = S.AWAITING_PROVIDER
                self.store.save_request(req)
            aid = self.db.next_id("assign")
            drive = chosen.extra.get("drive_minutes")
            eta = max(1, math.ceil(drive)) if drive is not None else eta_minutes(chosen.distance_km)
            transport = Assignment(
                assignment_id=aid, case_id=case_id, request_id=request_id, offer_id=chosen.entity_id,
                provider_id=chosen.org_id, service_type=TRANSPORT, provider_approved=True,
                service_area_allowed=True, zone_rule=ZoneRule.OUTSIDE_ACTIVE_ORDER, authorization=PREAPPROVED,
                status=S.PROPOSED, idempotency_key=key, volunteer_id=chosen.entity_id,
                vehicle_type=chosen.extra.get("vehicle_type"), region_id=chosen.extra.get("region_id"),
                alert_id=ctx["alert_id"], eta_minutes=eta,
                correlation_id=corr, created_at=utc_now_iso())
            shelter = None
            if site is not None:
                shelter = Assignment(
                    assignment_id=f"{aid}_dest", case_id=case_id, request_id=request_id, offer_id=site.entity_id,
                    provider_id=site.org_id, service_type=DESTINATION, provider_approved=True,
                    service_area_allowed=True, zone_rule=ZoneRule.OUTSIDE_ACTIVE_ORDER, authorization=PREAPPROVED,
                    status=S.PROPOSED, idempotency_key=f"{key}:shelter", site_id=site.entity_id,
                    region_id=site.extra.get("region_id"),
                    alert_id=ctx["alert_id"], linked_assignment_id=aid, correlation_id=corr,
                    created_at=utc_now_iso())
                transport.linked_assignment_id = shelter.assignment_id
            self.store.save_assignment(transport)
            if shelter:
                self.store.save_assignment(shelter)
            self.events.append("MATCH_PROPOSED", case_id=case_id, correlation_id=corr,
                               data={"assignment_id": aid, "org_id": chosen.org_id, "volunteer_id": chosen.entity_id,
                                     "site_id": site.entity_id if site else (shelter_row.site_id if shelter_row else None),
                                     "distance_km": chosen.distance_km,
                                     "drive_minutes": chosen.extra.get("drive_minutes")})
            self.events.append("VOLUNTEER_RESERVED", case_id=case_id, correlation_id=corr,
                               data={"org_id": chosen.org_id, "volunteer_id": chosen.entity_id})
            if case.resident_status == R.REQUIRES_COORDINATOR:
                eng._set_resident_status(case, R.NEEDS_ASSISTANCE, reason="eligible volunteer found",
                                         correlation_id=corr)
            case.next_step = f"Awaiting volunteer acceptance ({eng._provider_name(chosen.org_id)}). Nothing is confirmed yet."
            eng._save_case(case)

        shelter_org = site.org_id if site else (shelter_row.provider_id if shelter_row else None)
        shelter_site = site.entity_id if site else (shelter_row.site_id if shelter_row else None)
        needs_shared = [c for c in profile.needs if c not in (6,)]
        match = {
            "assignment_id": aid, "status": S.PROPOSED.value, "reserved": True,
            "org_id": chosen.org_id, "region_id": chosen.extra.get("region_id"),
            "volunteer_id": chosen.entity_id, "vehicle_type": chosen.extra.get("vehicle_type"),
            "shelter_org_id": shelter_org, "site_id": shelter_site,
            "network_agent_address": self.store.partners.agent_address("volunteer_network"),
            "reason_codes": [c for c in chosen.reason_codes if c not in (
                "ORG_APPROVED", "VOLUNTEER_APPROVED", "CALAMITY_TYPE_SUPPORTED", "WITHIN_SERVICE_RADIUS",
                "AVAILABLE_FOR_THIS_ALERT", "SEATS_OK", "ROUTE_AVOIDS_ORDER_ZONES")],
            "authorization": PREAPPROVED, "route_status": "ILLUSTRATIVE_ONLY",
            "shared_with_volunteer": {"needs": needs_shared, "pet_count": profile.pet_count,
                                      "language": profile.language,
                                      "pickup_area": f"{case.sector_id or case.zone_id} (synthetic)"},
            "eta_estimate": {"minutes": eta, "label": ETA_LABEL}, "idempotency_key": key,
            "drive_minutes": chosen.extra.get("drive_minutes"),
        }
        result = {**base, "escalation_required": False, "no_match_reason": None, "match": match}
        self._remember(key, result)
        return {**result, "duplicate": False}, True

    def _remember(self, key: str, result: dict[str, Any]) -> None:
        self.db.coll("match_results").update_one({"_id": key}, {"$set": result}, upsert=True)

    def _no_match(self, case: Case, base: dict, reason: str, corr: str, key: str,
                  transport_unresolved: bool = True) -> dict[str, Any]:
        eng = self.engine
        with self.db.tx():
            if transport_unresolved and eng._can_move(case, R.REQUIRES_COORDINATOR):
                eng._set_resident_status(case, R.REQUIRES_COORDINATOR, reason=f"no match: {reason}",
                                         correlation_id=corr)
            case.next_step = {
                "ORDER_ZONE": "Inside a simulated active evacuation-order zone: ordinary volunteer dispatch is blocked. "
                              "Escalate to the simulated authorized response service.",
                "ZONE_STALE": "Zone data is stale: no assignment until the feed is fresh. Coordinator follow-up.",
                "ZONE_UNKNOWN": "Zone is unknown: no automated assignment. Coordinator follow-up.",
                "NO_AVAILABLE_VOLUNTEER": "No volunteer has said they are available yet. Unresolved; escalate per policy.",
                "NO_SUITABLE_VOLUNTEER": "No available volunteer covers these needs. Unresolved; escalate per policy.",
                "NO_SHELTER": "No suitable shelter with beds. Coordinator follow-up required.",
            }.get(reason, "Unresolved. Coordinator follow-up.")
            self.events.append("MATCH_NOT_POSSIBLE", case_id=case.case_id, correlation_id=corr, data={"reason": reason})
            eng._save_case(case)
        return {**base, "escalation_required": True, "no_match_reason": reason, "match": None, "duplicate": False}

    # -------------------------------------------------------------- accept
    def accept(self, assignment_id: str, *, org_id: str, volunteer_id: Optional[str] = None,
               site_id: Optional[str] = None, decision: str, idempotency_key: Optional[str] = None,
               correlation_id: Optional[str] = None) -> dict[str, Any]:
        eng = self.engine
        decision = decision.upper()
        if decision not in ("ACCEPTED", "DECLINED"):
            raise Conflict("decision must be ACCEPTED or DECLINED", code="INVALID_DECISION")
        if bool(volunteer_id) == bool(site_id):
            raise Conflict("Send exactly one of volunteer_id or site_id", code="VALIDATION_ERROR")
        primary = self.store.get_assignment(assignment_id)
        linked = eng._linked(primary)
        rows = [r for r in (primary, linked) if r is not None]
        case = self.store.get_case(primary.case_id)
        corr = eng._corr(case, correlation_id)
        if volunteer_id:
            row = next((r for r in rows if r.volunteer_id == volunteer_id and r.provider_id == org_id), None)
        else:
            row = next((r for r in rows if r.site_id == site_id and r.provider_id == org_id), None)
        if row is None:
            self.events.append("PROVIDER_IDENTITY_REJECTED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": assignment_id, "org_id": org_id})
            raise Unauthorized("Organization/volunteer/site does not match this assignment", reasons=["WRONG_PROVIDER"])
        org = self.store.partners.get_org(org_id)
        if not org.approved:
            raise Unauthorized("Organization is not approved", reasons=["ORG_NOT_APPROVED"])

        key = idempotency_key or f"{assignment_id}:accept:{volunteer_id or site_id}:{decision}"
        prior = self.db.coll("provider_events").find_one({"_id": key})
        if prior and prior.get("result"):
            return {**prior["result"], "duplicate": True}
        accept = decision == "ACCEPTED"
        if (accept and row.status in (S.ACCEPTED, S.COMPLETED)) or (not accept and row.status == S.DECLINED):
            return self._accept_view(primary, row, case, decision, corr, duplicate=True)
        if row.status in (S.CANCELED, S.DECLINED, S.UNRESOLVED, S.COMPLETED):
            self.events.append("LATE_RESPONSE_IGNORED", case_id=case.case_id, correlation_id=corr,
                               data={"assignment_id": row.assignment_id, "assignment_status": row.status})
            raise InvalidTransition(f"Assignment is {row.status}; late response ignored", reasons=["LATE_RESPONSE"])

        next_alt = None
        if accept and row.service_type == TRANSPORT:
            zone = eng.alerts.zone_for(self.store.get_resident_profile(case.resident_id))["zone_status"]
            if zone in BLOCKING_ZONES:  # the zone may have changed since the proposal
                raise SafetyRejection(f"Resident zone is now {zone}", code=BLOCKING_ZONES[zone][1],
                                      reasons=[BLOCKING_ZONES[zone][0]])
            located = self.store.partners.locate_volunteer(row.volunteer_id)
            vol = located[2] if located and located[1].org_id == org_id else None
            if vol is None or vol.reserved_case_id != case.case_id:
                raise Conflict("Volunteer reservation for this case was lost", code="RESERVATION_LOST")
            try:
                with self.db.tx():
                    eng._accept(row, case, corr)
                    eng._save_case(case)
            except DuplicateKeyError as exc:
                raise Conflict("Another volunteer was already accepted", code="DUPLICATE_ACCEPTANCE") from exc
        elif accept:  # shelter confirms a bed
            if not self.store.partners.take_bed(row.site_id):
                raise Conflict("Shelter site has no beds left", code="NO_BEDS")
            try:
                with self.db.tx():
                    eng._accept(row, case, corr)
                    eng._save_case(case)
            except Exception:
                self.store.partners.return_bed(row.site_id)
                raise
        else:
            next_alt = self._decline(row, case, corr)

        result = self._accept_view(primary, self.store.get_assignment(row.assignment_id),
                                   self.store.get_case(case.case_id), decision, corr, duplicate=False,
                                   next_alternate=next_alt)
        self.store.record_provider_event(key, {"type": "ASSIGNMENT_DECISION", "assignment_id": assignment_id,
                                               "org_id": org_id, "decision": decision, "result": result})
        return result

    def _decline(self, row: Assignment, case: Case, corr: str) -> Optional[dict[str, str]]:
        eng = self.engine
        is_transport = row.service_type == TRANSPORT
        if row.status == S.ACCEPTED and row.confirmed_pickup_at:
            raise InvalidTransition("Pickup already confirmed; coordinator must handle this change",
                                    reasons=["PICKUP_ALREADY_CONFIRMED"])
        with self.db.tx():
            was_accepted = row.status == S.ACCEPTED
            row.status = S.CANCELED if was_accepted else S.DECLINED
            row.provider_response = ProviderResponse.DECLINED
            row.updated_at = utc_now_iso()
            self.store.save_assignment(row)
            self.events.append("PROVIDER_CANCELED_AFTER_ACCEPTANCE" if was_accepted else "PROVIDER_DECLINED",
                               case_id=case.case_id, correlation_id=corr, actor=row.provider_id,
                               data={"assignment_id": row.assignment_id, "volunteer_id": row.volunteer_id,
                                     "site_id": row.site_id})
            if is_transport:
                self.store.partners.release_volunteer(row.volunteer_id, case.case_id)
                linked = eng._linked(row)
                if linked and linked.status in (S.PROPOSED, S.AWAITING_PROVIDER):
                    linked.status = S.CANCELED
                    self.store.save_assignment(linked)
                if was_accepted and case.resident_status == R.PROVIDER_ACCEPTED:
                    eng._set_resident_status(case, R.NEEDS_ASSISTANCE, reason="volunteer canceled",
                                             correlation_id=corr)
            elif was_accepted:
                self.store.partners.return_bed(row.site_id)

            ctx = self._context(case)
            vols, sites = self._evaluate(case, ctx)
            pool = vols if is_transport else sites
            alt = next((c for c in pool if c.eligible), None)
            req = self.store.find_request(case.case_id, row.service_type, row.request_id)
            if alt:
                req.status = S.PROPOSED
                label = "volunteer" if is_transport else "shelter"
                case.next_step = (f"{label.title()} declined. Next eligible {label}: {alt.entity_id} "
                                  f"({eng._provider_name(alt.org_id)}). Propose again with select.")
                next_alt = {"org_id": alt.org_id, ("volunteer_id" if is_transport else "site_id"): alt.entity_id}
            else:
                req.status = S.UNRESOLVED
                next_alt = None
                if is_transport and eng._can_move(case, R.REQUIRES_COORDINATOR):
                    eng._set_resident_status(case, R.REQUIRES_COORDINATOR, reason="no remaining eligible volunteer",
                                             correlation_id=corr)
                case.next_step = ("No remaining eligible volunteer. Unresolved: escalate (NO_SUITABLE_VOLUNTEER)."
                                  if is_transport else "No remaining eligible shelter. Coordinator follow-up.")
            self.store.save_request(req)
            eng._save_case(case)
        return next_alt

    def _accept_view(self, primary: Assignment, row: Assignment, case: Case, decision: str, corr: str, *,
                     duplicate: bool, next_alternate: Optional[dict] = None) -> dict[str, Any]:
        transport = self.store.get_assignment(primary.assignment_id) if primary.service_type == TRANSPORT else None
        is_transport = row.service_type == TRANSPORT
        accepted_transport = is_transport and row.status == S.ACCEPTED
        profile = self.store.get_resident_profile(case.resident_id)
        return {
            "assignment_id": primary.assignment_id, "case_id": case.case_id,
            "responding": "volunteer" if is_transport else "shelter", "org_id": row.provider_id,
            **({"volunteer_id": row.volunteer_id} if is_transport else {"site_id": row.site_id}),
            "decision": decision, "assignment_status": row.status, "resident_status": case.resident_status,
            "pickup_details": {"pickup_point": profile.address.label, "resident_phone": profile.phone}
            if accepted_transport else None,
            "help_on_the_way_sent": accepted_transport and not duplicate,
            "eta": {"minutes": transport.eta_minutes, "label": ETA_LABEL} if transport and accepted_transport else None,
            "confirmed_pickup_at": transport.confirmed_pickup_at if transport else None,
            "confirmed_arrival_at": transport.confirmed_arrival_at if transport else None,
            "next_alternate": next_alternate, "next_step": case.next_step, "duplicate": duplicate,
            "correlation_id": corr,
        }

    # ------------------------------------------------------------ escalate
    @staticmethod
    def _auto_ack(db) -> bool:
        return (os.environ.get("AUTO_ESCALATION_ACK", "true").lower() == "true"
                and db.get_setting("escalation_ack", "true") != "false")

    def escalate(self, case_id: str, reason: str, *, idempotency_key: Optional[str] = None,
                 correlation_id: Optional[str] = None) -> tuple[dict[str, Any], bool]:
        eng = self.engine
        reason = EscalationReason(reason).value
        case = self.store.get_case(case_id)
        corr = eng._corr(case, correlation_id)
        profile = self.store.get_resident_profile(case.resident_id)
        zone = eng.alerts.zone_for(profile)
        key = idempotency_key or f"{case_id}:escalation:{reason}"
        existing = self.store.escalation_by_key(key)
        if existing:
            return self._escalation_view(existing, self.store.get_case(case_id), profile, zone, corr), False
        if reason == EscalationReason.ACTIVE_EVACUATION_ORDER_ZONE and zone["zone_status"] != "ORDER":
            raise Conflict("Resident is not inside a simulated active-order zone", code="REASON_MISMATCH")
        if reason == EscalationReason.NO_REPLY_AFTER_DEADLINE and case.communication_status != C.NO_REPLY_AFTER_DEADLINE:
            raise Conflict("Communication status is not NO_REPLY_AFTER_DEADLINE", code="REASON_MISMATCH")
        if case.resident_status == R.ARRIVAL_CONFIRMED:
            raise InvalidTransition("Arrival already confirmed; nothing to escalate")
        auto = self._auto_ack(self.db)
        with self.db.tx():
            esc = Escalation(escalation_id=self.db.next_id("esc"), case_id=case_id, reason=reason, recipient=RECIPIENT,
                             status=EscalationStatus.REQUESTED, idempotency_key=key, correlation_id=corr)
            self.events.append("ESCALATION_REQUESTED", case_id=case_id, correlation_id=corr,
                               data={"escalation_id": esc.escalation_id, "reason": reason, "simulated": True})
            if auto:
                esc.status, esc.acknowledged_at = EscalationStatus.ACKNOWLEDGED_REQUEST_ONLY, utc_now_iso()
                self.events.append("ESCALATION_ACKNOWLEDGED_REQUEST_ONLY", case_id=case_id, correlation_id=corr,
                                   actor=RECIPIENT, data={"escalation_id": esc.escalation_id, "auto": True,
                                                          "assistance_confirmed": False})
            esc.assistance_confirmed = False
            self.store.save_escalation(esc)
            for req in self.store.requests_for_case(case_id):
                if req.service_type == TRANSPORT and req.status not in (S.ACCEPTED, S.COMPLETED):
                    req.status = S.UNRESOLVED
                    self.store.save_request(req)
            if eng._can_move(case, R.REQUIRES_COORDINATOR):
                eng._set_resident_status(case, R.REQUIRES_COORDINATOR, reason=f"escalated: {reason}",
                                         correlation_id=corr)
            eng._message_resident(case, "coordinator_followup", corr)
            case.next_step = self._escalation_next_step(esc.status)
            eng._save_case(case)
        return self._escalation_view(esc, case, profile, zone, corr), True

    @staticmethod
    def _escalation_next_step(status: str) -> str:
        return {
            "REQUESTED": "Awaiting simulated authorized service acknowledgment; assistance not confirmed.",
            "ACKNOWLEDGED_REQUEST_ONLY": "Coordinator follows up with simulated authorized response service; "
                                         "assistance not confirmed.",
            "NO_ACKNOWLEDGMENT": "No acknowledgment received. Assistance not confirmed; coordinator must follow up.",
        }[status]

    def acknowledge(self, escalation_id: str, status: str, *, recipient_agent_address: Optional[str] = None,
                    idempotency_key: Optional[str] = None, correlation_id: Optional[str] = None) -> dict[str, Any]:
        eng = self.engine
        status = EscalationStatus(status).value
        if status == EscalationStatus.REQUESTED:
            raise Conflict("Acknowledgment status must be ACKNOWLEDGED_REQUEST_ONLY or NO_ACKNOWLEDGMENT",
                           code="VALIDATION_ERROR")
        esc = self.store.get_escalation(escalation_id)
        case = self.store.get_case(esc.case_id)
        corr = eng._corr(case, correlation_id)
        profile = self.store.get_resident_profile(case.resident_id)
        zone = eng.alerts.zone_for(profile)
        if esc.status == status:
            return {**self._escalation_view(esc, case, profile, zone, corr), "duplicate": True}
        if esc.status != EscalationStatus.REQUESTED:
            raise InvalidTransition(f"Escalation already {esc.status}", reasons=["LATE_RESPONSE"])
        with self.db.tx():
            esc.status = status
            esc.acknowledged_at = utc_now_iso() if status == EscalationStatus.ACKNOWLEDGED_REQUEST_ONLY else None
            esc.assistance_confirmed = False
            self.store.save_escalation(esc)
            self.events.append(f"ESCALATION_{status}", case_id=case.case_id, correlation_id=corr, actor=RECIPIENT,
                               data={"escalation_id": escalation_id, "recipient_agent": recipient_agent_address,
                                     "assistance_confirmed": False})
            case.next_step = self._escalation_next_step(status)
            eng._save_case(case)
        return {**self._escalation_view(esc, case, profile, zone, corr), "duplicate": False}

    def _escalation_view(self, esc: Escalation, case: Case, profile, zone: dict, corr: str) -> dict[str, Any]:
        zone_id = case.zone_id
        if case.alert_id:
            try:
                zone_id = self.engine.alerts.get_alert(case.alert_id).zone_id
            except NotFound:
                pass
        return {"escalation_id": esc.escalation_id, "case_id": esc.case_id, "reason": esc.reason,
                "recipient": esc.recipient, "status": esc.status, "assistance_confirmed": False,
                "case_summary_for_recipient": {"case_id": case.case_id, "zone_id": zone_id,
                                               "zone_status": zone["zone_status"], "language": profile.language,
                                               "needs": profile.needs},
                "resident_status": case.resident_status, "assignment_status": S.UNRESOLVED.value,
                "next_step": case.next_step, "correlation_id": corr}

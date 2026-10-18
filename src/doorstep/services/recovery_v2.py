"""Post-calamity help (contract v2.1 §5.8). A referral is NOT completed assistance.

* Only after confirmed arrival, or for residents who self-reported leaving / having a
  plan; only with RECOVERY consent from the resident or their caregiver.
* One referral per help type, to the nearest approved org (by region) whose
  ``recovery_services`` include it, within the org's service radius.
* Shares only the fields that help type needs (``shared_payload``).
* Statuses: REQUESTED → ACCEPTED → COMPLETED (needs evidence); DECLINED → UNRESOLVED.
  ``housing_secured`` is true only for a COMPLETED TEMPORARY_HOUSING referral.
* Never files claims or applications; INSURANCE_GUIDANCE is a referral to a helper org.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from shapely.geometry import Point

from doorstep.models import (
    ConsentGrant,
    RecoveryHelpType,
    RecoveryReferral,
    ReferralStatus as RS,
    ResidentStatus as R,
    ResponseIntent,
    utc_now_iso,
)

from .errors import Conflict, ConsentRequired, InvalidTransition, NotFound, Unauthorized

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

ACTIVE = (RS.REQUESTED.value, RS.ACCEPTED.value, RS.COMPLETED.value)
# Need codes a recovery org may see, per help type (purpose limitation).
SHARED_NEEDS = {
    "TEMPORARY_HOUSING": {1, 3, 4, 5, 6, 8},
    "MEDICAL_EQUIPMENT_REPLACEMENT": {3, 8, 9},
    "SUPPLIES": {3, 4, 5},
}
HELP_LABELS = {
    "TEMPORARY_HOUSING": {"en": "temporary housing", "es": "alojamiento temporal"},
    "INSURANCE_GUIDANCE": {"en": "insurance guidance", "es": "orientación sobre seguros"},
    "SUPPLIES": {"en": "supplies", "es": "suministros"},
    "MEDICAL_EQUIPMENT_REPLACEMENT": {"en": "medical equipment replacement", "es": "reemplazo de equipo médico"},
    "CASEWORK": {"en": "casework", "es": "manejo de casos"},
}


class RecoveryService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store
        self.events = engine.events

    # ------------------------------------------------------------- helpers
    def _party(self, case, granted_by: str) -> str:
        return self.engine._party_for_role(self.store.get_resident(case.resident_id), granted_by)

    def _eligible_for_recovery(self, case) -> bool:
        return case.resident_status == R.ARRIVAL_CONFIRMED or case.response_intent in (
            ResponseIntent.ALREADY_LEFT.value, ResponseIntent.HAS_PLAN.value)

    def _payload(self, referral_id: str, help_type: str, profile) -> dict[str, Any]:
        payload: dict[str, Any] = {"referral_id": referral_id, "help_type": help_type, "language": profile.language}
        allowed = SHARED_NEEDS.get(help_type)
        if allowed:
            payload["needs"] = sorted(set(profile.needs) & allowed)
        if help_type in ("TEMPORARY_HOUSING", "SUPPLIES"):
            payload["pet_count"] = profile.pet_count
        return payload

    def _nearest_org(self, help_type: str, profile, exclude: set[str]) -> Optional[dict[str, Any]]:
        partners = self.store.partners
        radii = [o.service_radius_km for o in partners.list_orgs() if o.approved]
        here = Point(profile.address.lon, profile.address.lat)
        for region, km in partners.regions_near(here, max(radii) if radii else 0):
            for entry in sorted(region.orgs, key=lambda e: e.org_id):
                if (entry.approved and help_type in entry.recovery_services and entry.org_id not in exclude
                        and km <= entry.service_radius_km):
                    return {"org_id": entry.org_id, "name": entry.name, "region_id": region.region_id,
                            "distance_km": km}
        return None

    def aggregate_status(self, case_id: str) -> str:
        """In progress wins (ACCEPTED, then REQUESTED); then COMPLETED; otherwise UNRESOLVED."""
        statuses = {r.status for r in self.store.referrals_for_case(case_id) if r.help_type}
        if not statuses:
            return RS.NOT_REQUESTED.value
        for s in (RS.ACCEPTED.value, RS.REQUESTED.value, RS.COMPLETED.value):
            if s in statuses:
                return s
        return RS.UNRESOLVED.value

    def _view(self, r: RecoveryReferral) -> dict[str, Any]:
        return {"referral_id": r.referral_id, "help_type": r.help_type, "org_id": r.provider_id,
                "org_name": self.engine._provider_name(r.provider_id), "region_id": r.region_id,
                "distance_km": r.distance_km, "status": r.status, "shared_payload": r.shared_fields,
                "housing_secured": self._housing_secured(r)}

    @staticmethod
    def _housing_secured(r: RecoveryReferral) -> bool:
        return r.help_type == "TEMPORARY_HOUSING" and r.status == RS.COMPLETED.value and bool(r.evidence)

    def case_view(self, case_id: str) -> dict[str, Any]:
        refs = [r for r in self.store.referrals_for_case(case_id) if r.help_type]
        return {"status": self.aggregate_status(case_id),
                "referrals": [{k: v for k, v in self._view(r).items() if k != "shared_payload"} for r in refs],
                "housing_secured": any(self._housing_secured(r) for r in refs)}

    # ---------------------------------------------- consent by SMS reply
    def sms_reply_after_arrival(self, case, resident, actor_party: str, yes: bool, corr: str) -> None:
        """The arrival message asks to share needs for housing help: SI = consent, NO = decline."""
        self.store.add_consent_grant(ConsentGrant(case_id=case.case_id, scope="share_recovery_needs", granted=yes,
                                                  granted_by=actor_party, created_at=utc_now_iso()))
        profile = self.store.get_resident_profile(case.resident_id)
        self.store.save_resident_profile(profile.model_copy(
            update={"consents": {**profile.consents, "RECOVERY": yes}}))
        case.consent = case.consent.model_copy(update={"share_recovery_needs": yes})
        self.events.append("RECOVERY_CONSENT_GRANTED" if yes else "RECOVERY_CONSENT_DECLINED", case_id=case.case_id,
                           correlation_id=corr, actor=actor_party, data={"channel": "sms"})
        case.next_step = ("Resident wants further help: request referrals (e.g. TEMPORARY_HOUSING)."
                          if yes else "Resident declined further help. Nothing shared.")

    # -------------------------------------------------------------- request
    def request(self, case_id: str, *, share_recovery_needs: bool, granted_by: str, help_types: list[str],
                granted_at: Optional[str] = None, idempotency_key: Optional[str] = None,
                correlation_id: Optional[str] = None) -> tuple[dict[str, Any], bool]:
        eng = self.engine
        case = self.store.get_case(case_id)
        corr = eng._corr(case, correlation_id)
        key = idempotency_key or f"{case_id}:recovery:v2:{'-'.join(sorted(help_types))}"
        prior = self.db.coll("match_results").find_one({"_id": key})
        if prior:
            return {**{k: v for k, v in prior.items() if not k.startswith("_")}, "duplicate": True}, False
        party = self._party(case, granted_by)
        types = [RecoveryHelpType(t).value for t in dict.fromkeys(help_types)]
        if not types:
            raise Conflict("Choose at least one help type", code="VALIDATION_ERROR")
        if not self._eligible_for_recovery(case):
            raise InvalidTransition("Post-calamity help starts after confirmed arrival (or a self-reported departure)",
                                    reasons=["NOT_YET_EVACUATED"])
        profile = self.store.get_resident_profile(case.resident_id)

        self.store.add_consent_grant(ConsentGrant(case_id=case_id, scope="share_recovery_needs",
                                                  granted=share_recovery_needs, granted_by=party,
                                                  created_at=granted_at or utc_now_iso()))
        self.store.save_resident_profile(profile.model_copy(
            update={"consents": {**profile.consents, "RECOVERY": share_recovery_needs}}))
        if not share_recovery_needs:
            with self.db.tx():
                case.consent = case.consent.model_copy(update={"share_recovery_needs": False})
                self.events.append("RECOVERY_CONSENT_DECLINED", case_id=case_id, correlation_id=corr, actor=party)
                case.next_step = "Resident declined recovery referral. Nothing shared."
                eng._save_case(case)
            raise ConsentRequired("Resident did not consent to share recovery needs; nothing was shared")

        existing = [r for r in self.store.referrals_for_case(case_id) if r.help_type]
        referrals, unmatched = [], []
        with self.db.tx():
            case.consent = case.consent.model_copy(update={"share_recovery_needs": True})
            self.events.append("RECOVERY_CONSENT_GRANTED", case_id=case_id, correlation_id=corr, actor=party)
            for help_type in types:
                active = next((r for r in existing if r.help_type == help_type and r.status in ACTIVE), None)
                if active:  # already requested/accepted/completed: reuse, never duplicate
                    referrals.append(self._view(active))
                    continue
                declined = {r.provider_id for r in existing if r.help_type == help_type and r.status == RS.UNRESOLVED}
                org = self._nearest_org(help_type, profile, declined)
                if org is None:
                    unmatched.append(help_type)
                    continue
                rid = self.db.next_id("ref")
                ref = RecoveryReferral(referral_id=rid, case_id=case_id, provider_id=org["org_id"], help_type=help_type,
                                       region_id=org["region_id"], distance_km=org["distance_km"],
                                       shared_fields=self._payload(rid, help_type, profile),
                                       idempotency_key=f"{key}:{help_type}", correlation_id=corr)
                self.store.save_referral(ref)
                self.events.append("RECOVERY_REFERRAL_REQUESTED", case_id=case_id, correlation_id=corr,
                                   data={"referral_id": rid, "help_type": help_type, "org_id": org["org_id"],
                                         "field_names": sorted(ref.shared_fields)})
                lang = profile.language if profile.language in ("en", "es") else "en"
                eng._message_resident(case, "recovery_requested", corr, org=org["name"],
                                      help=HELP_LABELS[help_type][lang])
                referrals.append(self._view(ref))
            case.next_step = ("Recovery referrals REQUESTED. Nothing is secured unless a provider confirms."
                              if referrals else "No recovery organization offers this help nearby. Coordinator follow-up.")
            eng._save_case(case)
        result = {"case_id": case_id, "referrals": referrals, "unmatched_help_types": unmatched,
                  "recovery_status": self.aggregate_status(case_id),
                  "housing_secured": any(r["housing_secured"] for r in referrals), "correlation_id": corr}
        self.db.coll("match_results").update_one({"_id": key}, {"$set": result}, upsert=True)
        return {**result, "duplicate": False}, bool(referrals)

    # -------------------------------------------------------------- respond
    def respond(self, referral_id: str, *, org_id: str, decision: str, evidence: Optional[dict] = None,
                idempotency_key: Optional[str] = None, correlation_id: Optional[str] = None) -> dict[str, Any]:
        eng = self.engine
        ref = self.store.get_referral(referral_id)
        if not ref.help_type:
            raise NotFound("Not a v2 recovery referral (use the v1 route)")
        if org_id != ref.provider_id:
            raise Unauthorized("Organization does not match this referral", reasons=["WRONG_ORG"])
        decision = decision.upper()
        target = {"ACCEPTED": RS.ACCEPTED.value, "DECLINED": RS.UNRESOLVED.value,
                  "COMPLETED": RS.COMPLETED.value}.get(decision)
        if target is None:
            raise Conflict("decision must be ACCEPTED, DECLINED or COMPLETED", code="INVALID_DECISION")
        case = self.store.get_case(ref.case_id)
        corr = eng._corr(case, correlation_id)
        if ref.status == target:
            return {**self._respond_view(ref, corr), "duplicate": True}
        allowed = {RS.REQUESTED.value: {RS.ACCEPTED.value, RS.UNRESOLVED.value, RS.COMPLETED.value},
                   RS.ACCEPTED.value: {RS.COMPLETED.value, RS.UNRESOLVED.value}}
        if target not in allowed.get(ref.status, set()):
            raise InvalidTransition(f"Referral is {ref.status}; cannot become {target}", reasons=["LATE_RESPONSE"])
        if target == RS.COMPLETED.value and not (evidence and evidence.get("type") == "SIMULATED_SERVICE_CONFIRMED"
                                                 and evidence.get("reference")):
            raise Conflict("COMPLETED needs evidence {type: SIMULATED_SERVICE_CONFIRMED, reference}",
                           code="INSUFFICIENT_EVIDENCE")
        profile = self.store.get_resident_profile(case.resident_id)
        lang = profile.language if profile.language in ("en", "es") else "en"
        org_name = eng._provider_name(org_id)
        next_alt = None
        with self.db.tx():
            ref.status = target
            ref.updated_at = utc_now_iso()
            if target == RS.COMPLETED.value:
                ref.evidence = evidence
            self.store.save_referral(ref)
            self.events.append(f"RECOVERY_REFERRAL_{target}", case_id=case.case_id, correlation_id=corr,
                               actor=org_id, data={"referral_id": referral_id, "help_type": ref.help_type})
            if target == RS.ACCEPTED.value:
                eng._message_resident(case, "recovery_accepted", corr, org=org_name, help=HELP_LABELS[ref.help_type][lang])
                case.next_step = f"{org_name} accepted the {ref.help_type} request (not a confirmed service)."
            elif target == RS.COMPLETED.value:
                eng._message_resident(case, "recovery_completed", corr, org=org_name,
                                      help=HELP_LABELS[ref.help_type][lang], ref=str(evidence.get("reference")))
                case.next_step = f"{ref.help_type} confirmed by {org_name} (simulated)."
            else:
                declined = {r.provider_id for r in self.store.referrals_for_case(case.case_id)
                            if r.help_type == ref.help_type and r.status == RS.UNRESOLVED.value}
                alt = self._nearest_org(ref.help_type, profile, declined)
                next_alt = {"org_id": alt["org_id"], "region_id": alt["region_id"]} if alt else None
                case.next_step = (f"{org_name} declined. Next nearest org for {ref.help_type}: {alt['org_id']}. "
                                  "Request again to refer there." if alt else
                                  f"No other org offers {ref.help_type} nearby. Coordinator follow-up.")
            eng._save_case(case)
        return {**self._respond_view(ref, corr), "next_alternate": next_alt, "duplicate": False}

    def _respond_view(self, ref: RecoveryReferral, corr: str) -> dict[str, Any]:
        return {"referral_id": ref.referral_id, "case_id": ref.case_id, "help_type": ref.help_type,
                "org_id": ref.provider_id, "status": ref.status, "housing_secured": self._housing_secured(ref),
                "recovery_status": self.aggregate_status(ref.case_id), "correlation_id": corr}

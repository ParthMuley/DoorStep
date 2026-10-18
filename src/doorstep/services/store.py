"""Typed repository over MongoDB collections.

Each document is the model's JSON dump plus ``_id`` and internal fields that
start with ``_`` (``_ord`` insertion order, ``_accepted_slot`` for the
one-accepted-assignment unique index). Internal fields are stripped before
validating back into the model.
"""

from __future__ import annotations

from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from doorstep.models import (
    AlertEvent,
    Assignment,
    Case,
    ConsentGrant,
    Escalation,
    MessageEvent,
    Offer,
    ProviderRegistration,
    RecoveryReferral,
    Resident,
    ResidentProfile,
    ServiceRequest,
    VerificationEvent,
)

from pymongo.errors import DuplicateKeyError

from .db import Database
from .errors import NotFound
from .legacy import to_legacy_resident
from .partners import PartnerStore

M = TypeVar("M", bound=BaseModel)
ACCEPTED_STATES = ("ACCEPTED", "COMPLETED")


def _strip(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


class Store:
    def __init__(self, db: Database):
        self.db = db
        self.partners = PartnerStore(db)

    # --- generic helpers -------------------------------------------------
    def _get(self, coll: str, query: dict[str, Any], model: Type[M]) -> Optional[M]:
        doc = self.db.coll(coll).find_one(query)
        return model.model_validate(_strip(doc)) if doc else None

    def _require(self, coll: str, query: dict[str, Any], model: Type[M], label: str) -> M:
        obj = self._get(coll, query, model)
        if obj is None:
            raise NotFound(f"{model.__name__} {label!r} not found")
        return obj

    def _list(self, coll: str, query: dict[str, Any], model: Type[M], sort: str = "_ord",
              direction: int = 1, limit: int = 0) -> list[M]:
        cursor = self.db.coll(coll).find(query).sort(sort, direction)
        if limit:
            cursor = cursor.limit(limit)
        return [model.model_validate(_strip(d)) for d in cursor]

    def _upsert(self, coll: str, key: str, model: BaseModel, extra_set: Optional[dict] = None,
                unset: Optional[list[str]] = None) -> None:
        update: dict[str, Any] = {"$set": {**model.model_dump(mode="json"), **(extra_set or {})},
                                  "$setOnInsert": {"_ord": self.db.next_ord()}}
        if unset:
            update["$unset"] = {f: "" for f in unset}
        self.db.coll(coll).update_one({"_id": key}, update, upsert=True)

    # --- partners (doorstep_partners): see services/partners.py ----------------
    def record_provider_event(self, key: str, payload: dict) -> tuple[dict, bool]:
        """Idempotent provider-side event. Returns (stored payload, created?)."""
        coll = self.db.coll("provider_events")
        try:
            coll.insert_one({"_id": key, "_ord": self.db.next_ord(), **payload})
            return payload, True
        except DuplicateKeyError:
            doc = coll.find_one({"_id": key}) or {}
            return {k: v for k, v in doc.items() if not k.startswith("_")}, False

    # --- residents (doorstep_users) -----------------------------------------
    def save_resident_profile(self, p: ResidentProfile, legacy_sector: Optional[str] = None) -> None:
        extra = {"_legacy_sector": legacy_sector} if legacy_sector else None
        self._upsert("residents", p.resident_id, p, extra_set=extra)

    def get_resident_profile(self, resident_id: str) -> ResidentProfile:
        return self._require("residents", {"_id": resident_id}, ResidentProfile, resident_id)

    def find_resident_profile(self, resident_id: str) -> Optional[ResidentProfile]:
        return self._get("residents", {"_id": resident_id}, ResidentProfile)

    def list_resident_profiles(self) -> list[ResidentProfile]:
        return self._list("residents", {}, ResidentProfile, sort="_id")

    def resident_by_phone(self, phone: str) -> Optional[ResidentProfile]:
        return self._get("residents", {"phone": phone}, ResidentProfile)

    # v1 view used by the current engine until the v2 switch-over (services/legacy.py).
    def _legacy(self, doc: dict) -> Resident:
        return to_legacy_resident(ResidentProfile.model_validate(_strip(doc)), doc.get("_legacy_sector"))

    def get_resident(self, resident_id: str) -> Resident:
        doc = self.db.coll("residents").find_one({"_id": resident_id})
        if doc is None:
            raise NotFound(f"Resident {resident_id!r} not found")
        return self._legacy(doc)

    def list_residents(self) -> list[Resident]:
        return [self._legacy(d) for d in self.db.coll("residents").find({}).sort("_id", 1)]

    def save_registration(self, p: ProviderRegistration) -> None:
        self._upsert("provider_registry", p.provider_id, p)

    def get_registration(self, provider_id: str) -> Optional[ProviderRegistration]:
        return self._get("provider_registry", {"_id": provider_id}, ProviderRegistration)

    def registry(self) -> dict[str, ProviderRegistration]:
        return {r.provider_id: r for r in self._list("provider_registry", {}, ProviderRegistration, sort="_id")}

    # --- alerts / cases ---------------------------------------------------
    def save_alert(self, a: AlertEvent) -> None:
        self._upsert("alerts", a.alert_id, a)

    def list_alerts(self) -> list[AlertEvent]:
        return self._list("alerts", {}, AlertEvent)

    def save_case(self, c: Case) -> None:
        self._upsert("cases", c.case_id, c)

    def get_case(self, case_id: str) -> Case:
        return self._require("cases", {"_id": case_id}, Case, case_id)

    def find_case(self, case_id: str) -> Optional[Case]:
        return self._get("cases", {"_id": case_id}, Case)

    def list_cases(self, resident_status: Optional[str] = None) -> list[Case]:
        query = {"resident_status": resident_status} if resident_status else {}
        return self._list("cases", query, Case, sort="_id")

    def case_for_resident(self, resident_id: str) -> Optional[Case]:
        found = self._list("cases", {"resident_id": resident_id}, Case, direction=-1, limit=1)
        return found[0] if found else None

    # --- requests / offers / assignments ---------------------------------
    def save_request(self, r: ServiceRequest) -> None:
        self._upsert("service_requests", r.idempotency_key, r)

    def request_by_key(self, key: str) -> Optional[ServiceRequest]:
        return self._get("service_requests", {"_id": key}, ServiceRequest)

    def find_request(self, case_id: str, service_type: str, request_id: str) -> ServiceRequest:
        return self._require("service_requests",
                             {"case_id": case_id, "service_type": service_type, "request_id": request_id},
                             ServiceRequest, request_id)

    def requests_for_case(self, case_id: str) -> list[ServiceRequest]:
        return self._list("service_requests", {"case_id": case_id}, ServiceRequest)

    def save_offer(self, o: Offer) -> None:
        self._upsert("offers", f"{o.case_id}:{o.offer_id}", o)

    def get_offer(self, case_id: str, offer_id: str) -> Offer:
        return self._require("offers", {"_id": f"{case_id}:{offer_id}"}, Offer, offer_id)

    def offers_for_request(self, case_id: str, request_id: str) -> list[Offer]:
        return self._list("offers", {"case_id": case_id, "request_id": request_id}, Offer)

    def offers_for_case(self, case_id: str) -> list[Offer]:
        return self._list("offers", {"case_id": case_id}, Offer)

    def save_assignment(self, a: Assignment) -> None:
        """Raises pymongo DuplicateKeyError if a second assignment for the same
        case + service would become ACCEPTED/COMPLETED, or on a reused idempotency key."""
        if a.status in ACCEPTED_STATES:
            self._upsert("assignments", a.assignment_id, a,
                         extra_set={"_accepted_slot": f"{a.case_id}:{a.service_type}"})
        else:
            self._upsert("assignments", a.assignment_id, a, unset=["_accepted_slot"])

    def get_assignment(self, assignment_id: str) -> Assignment:
        return self._require("assignments", {"_id": assignment_id}, Assignment, assignment_id)

    def find_assignment(self, assignment_id: str) -> Optional[Assignment]:
        return self._get("assignments", {"_id": assignment_id}, Assignment)

    def assignment_by_key(self, key: str) -> Optional[Assignment]:
        return self._get("assignments", {"idempotency_key": key}, Assignment)

    def assignments_for_case(self, case_id: str, service_type: Optional[str] = None) -> list[Assignment]:
        query: dict[str, Any] = {"case_id": case_id}
        if service_type:
            query["service_type"] = service_type
        return self._list("assignments", query, Assignment)

    def accepted_assignment(self, case_id: str, service_type: str) -> Optional[Assignment]:
        return self._get("assignments", {"case_id": case_id, "service_type": service_type,
                                         "status": {"$in": list(ACCEPTED_STATES)}}, Assignment)

    # --- evidence / messages / escalations / referrals --------------------
    def save_verification(self, v: VerificationEvent) -> None:
        self._upsert("verifications", v.verification_id, v)

    def verifications_for_case(self, case_id: str) -> list[VerificationEvent]:
        return self._list("verifications", {"case_id": case_id}, VerificationEvent)

    def save_message(self, m: MessageEvent) -> None:
        self._upsert("messages", m.message_id, m)

    def get_message(self, message_id: str) -> MessageEvent:
        return self._require("messages", {"_id": message_id}, MessageEvent, message_id)

    def message_by_external_id(self, external_id: str) -> Optional[MessageEvent]:
        return self._get("messages", {"external_id": external_id}, MessageEvent)

    def list_messages(self, case_id: Optional[str] = None) -> list[MessageEvent]:
        return self._list("messages", {"case_id": case_id} if case_id else {}, MessageEvent)

    def save_escalation(self, e: Escalation) -> None:
        self._upsert("escalations", e.escalation_id, e)

    def get_escalation(self, escalation_id: str) -> Escalation:
        return self._require("escalations", {"_id": escalation_id}, Escalation, escalation_id)

    def escalation_by_key(self, key: str) -> Optional[Escalation]:
        return self._get("escalations", {"idempotency_key": key}, Escalation)

    def escalations_for_case(self, case_id: str) -> list[Escalation]:
        return self._list("escalations", {"case_id": case_id}, Escalation)

    def save_referral(self, r: RecoveryReferral) -> None:
        self._upsert("referrals", r.referral_id, r)

    def get_referral(self, referral_id: str) -> RecoveryReferral:
        return self._require("referrals", {"_id": referral_id}, RecoveryReferral, referral_id)

    def referral_by_key(self, key: str) -> Optional[RecoveryReferral]:
        return self._get("referrals", {"idempotency_key": key}, RecoveryReferral)

    def referrals_for_case_all(self) -> list[RecoveryReferral]:
        return self._list("referrals", {}, RecoveryReferral)

    def referrals_for_case(self, case_id: str) -> list[RecoveryReferral]:
        return self._list("referrals", {"case_id": case_id}, RecoveryReferral)

    def add_consent_grant(self, g: ConsentGrant) -> None:
        self.db.coll("consent_grants").insert_one({**g.model_dump(mode="json"), "_ord": self.db.next_ord()})

    def consent_grants_for_case(self, case_id: str) -> list[ConsentGrant]:
        return self._list("consent_grants", {"case_id": case_id}, ConsentGrant)

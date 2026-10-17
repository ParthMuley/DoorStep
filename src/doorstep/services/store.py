"""Typed repository over the SQLite tables (JSON blob + indexed columns)."""

from __future__ import annotations

from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from doorstep.models import (
    AlertEvent,
    Assignment,
    Case,
    ConsentGrant,
    Escalation,
    MessageEvent,
    Offer,
    Organization,
    ProviderRegistration,
    RecoveryReferral,
    Resident,
    ServiceRequest,
    VerificationEvent,
)

from .db import Database
from .errors import NotFound

M = TypeVar("M", bound=BaseModel)


class Store:
    def __init__(self, db: Database):
        self.db = db

    # --- generic helpers -------------------------------------------------
    def _get(self, table: str, key_col: str, key: str, model: Type[M]) -> Optional[M]:
        with self.db.read() as conn:
            row = conn.execute(f"SELECT data FROM {table} WHERE {key_col} = ?", (key,)).fetchone()
        return model.model_validate_json(row["data"]) if row else None

    def _require(self, table: str, key_col: str, key: str, model: Type[M]) -> M:
        obj = self._get(table, key_col, key, model)
        if obj is None:
            raise NotFound(f"{model.__name__} {key!r} not found")
        return obj

    def _list(self, sql: str, params: tuple, model: Type[M]) -> list[M]:
        with self.db.read() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [model.model_validate_json(r["data"]) for r in rows]

    def _upsert(self, table: str, cols: dict[str, object]) -> None:
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        key = next(iter(cols))
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != key)
        with self.db.tx() as conn:
            conn.execute(
                f"INSERT INTO {table} ({names}) VALUES ({marks}) "
                f"ON CONFLICT({key}) DO UPDATE SET {updates}",
                tuple(cols.values()),
            )

    # --- organizations / residents / inventories ------------------------
    def save_organization(self, o: Organization) -> None:
        self._upsert("organizations", {"organization_id": o.organization_id, "data": o.model_dump_json()})

    def list_organizations(self) -> list[Organization]:
        return self._list("SELECT data FROM organizations ORDER BY organization_id", (), Organization)

    def save_resident(self, r: Resident) -> None:
        self._upsert("residents", {"resident_id": r.resident_id, "zone_id": r.zone_id,
                                   "contact_channel": r.contact_channel, "data": r.model_dump_json()})

    def get_resident(self, resident_id: str) -> Resident:
        return self._require("residents", "resident_id", resident_id, Resident)

    def list_residents(self) -> list[Resident]:
        return self._list("SELECT data FROM residents ORDER BY resident_id", (), Resident)

    def save_registration(self, p: ProviderRegistration) -> None:
        self._upsert("provider_registry", {"provider_id": p.provider_id, "data": p.model_dump_json()})

    def get_registration(self, provider_id: str) -> Optional[ProviderRegistration]:
        return self._get("provider_registry", "provider_id", provider_id, ProviderRegistration)

    def registry(self) -> dict[str, ProviderRegistration]:
        regs = self._list("SELECT data FROM provider_registry ORDER BY provider_id", (), ProviderRegistration)
        return {r.provider_id: r for r in regs}

    # --- alerts / cases ---------------------------------------------------
    def save_alert(self, a: AlertEvent) -> None:
        self._upsert("alerts", {"alert_id": a.alert_id, "zone_id": a.zone_id,
                                "official_verified": int(a.official_verified), "data": a.model_dump_json()})

    def list_alerts(self) -> list[AlertEvent]:
        return self._list("SELECT data FROM alerts ORDER BY rowid", (), AlertEvent)

    def save_case(self, c: Case) -> None:
        self._upsert("cases", {"case_id": c.case_id, "resident_id": c.resident_id, "zone_id": c.zone_id,
                               "resident_status": c.resident_status,
                               "communication_status": c.communication_status,
                               "data": c.model_dump_json()})

    def get_case(self, case_id: str) -> Case:
        return self._require("cases", "case_id", case_id, Case)

    def find_case(self, case_id: str) -> Optional[Case]:
        return self._get("cases", "case_id", case_id, Case)

    def list_cases(self, resident_status: Optional[str] = None) -> list[Case]:
        if resident_status:
            return self._list("SELECT data FROM cases WHERE resident_status = ? ORDER BY case_id",
                              (resident_status,), Case)
        return self._list("SELECT data FROM cases ORDER BY case_id", (), Case)

    def case_for_resident(self, resident_id: str) -> Optional[Case]:
        found = self._list("SELECT data FROM cases WHERE resident_id = ? ORDER BY rowid DESC LIMIT 1",
                           (resident_id,), Case)
        return found[0] if found else None

    # --- requests / offers / assignments ---------------------------------
    def save_request(self, r: ServiceRequest) -> None:
        self._upsert("service_requests", {"idempotency_key": r.idempotency_key, "request_id": r.request_id,
                                          "case_id": r.case_id, "service_type": r.service_type,
                                          "status": r.status, "data": r.model_dump_json()})

    def request_by_key(self, key: str) -> Optional[ServiceRequest]:
        return self._get("service_requests", "idempotency_key", key, ServiceRequest)

    def find_request(self, case_id: str, service_type: str, request_id: str) -> ServiceRequest:
        found = self._list("SELECT data FROM service_requests WHERE case_id = ? AND service_type = ? "
                           "AND request_id = ?", (case_id, service_type, request_id), ServiceRequest)
        if not found:
            raise NotFound(f"Service request {request_id!r} not found")
        return found[0]

    def requests_for_case(self, case_id: str) -> list[ServiceRequest]:
        return self._list("SELECT data FROM service_requests WHERE case_id = ? ORDER BY rowid",
                          (case_id,), ServiceRequest)

    def save_offer(self, o: Offer) -> None:
        self._upsert("offers", {"offer_key": f"{o.case_id}:{o.offer_id}", "offer_id": o.offer_id,
                                "request_id": o.request_id, "case_id": o.case_id, "provider_id": o.provider_id,
                                "eligible": int(o.eligible), "data": o.model_dump_json()})

    def get_offer(self, case_id: str, offer_id: str) -> Offer:
        return self._require("offers", "offer_key", f"{case_id}:{offer_id}", Offer)

    def offers_for_request(self, case_id: str, request_id: str) -> list[Offer]:
        return self._list("SELECT data FROM offers WHERE case_id = ? AND request_id = ? ORDER BY rowid",
                          (case_id, request_id), Offer)

    def offers_for_case(self, case_id: str) -> list[Offer]:
        return self._list("SELECT data FROM offers WHERE case_id = ? ORDER BY rowid", (case_id,), Offer)

    def save_assignment(self, a: Assignment) -> None:
        self._upsert("assignments", {"assignment_id": a.assignment_id, "case_id": a.case_id,
                                     "service_type": a.service_type, "provider_id": a.provider_id,
                                     "status": a.status, "idempotency_key": a.idempotency_key,
                                     "data": a.model_dump_json()})

    def get_assignment(self, assignment_id: str) -> Assignment:
        return self._require("assignments", "assignment_id", assignment_id, Assignment)

    def find_assignment(self, assignment_id: str) -> Optional[Assignment]:
        return self._get("assignments", "assignment_id", assignment_id, Assignment)

    def assignment_by_key(self, key: str) -> Optional[Assignment]:
        return self._get("assignments", "idempotency_key", key, Assignment)

    def assignments_for_case(self, case_id: str, service_type: Optional[str] = None) -> list[Assignment]:
        if service_type:
            return self._list("SELECT data FROM assignments WHERE case_id = ? AND service_type = ? ORDER BY rowid",
                              (case_id, service_type), Assignment)
        return self._list("SELECT data FROM assignments WHERE case_id = ? ORDER BY rowid", (case_id,), Assignment)

    def accepted_assignment(self, case_id: str, service_type: str) -> Optional[Assignment]:
        found = self._list(
            "SELECT data FROM assignments WHERE case_id = ? AND service_type = ? "
            "AND status IN ('ACCEPTED', 'COMPLETED')", (case_id, service_type), Assignment)
        return found[0] if found else None

    # --- evidence / messages / escalations / referrals --------------------
    def save_verification(self, v: VerificationEvent) -> None:
        self._upsert("verifications", {"verification_id": v.verification_id, "assignment_id": v.assignment_id,
                                       "kind": v.kind, "data": v.model_dump_json()})

    def verifications_for_case(self, case_id: str) -> list[VerificationEvent]:
        return [v for v in self._list("SELECT data FROM verifications ORDER BY rowid", (), VerificationEvent)
                if v.case_id == case_id]

    def save_message(self, m: MessageEvent) -> None:
        self._upsert("messages", {"message_id": m.message_id, "case_id": m.case_id, "direction": m.direction,
                                  "external_id": m.external_id, "status": m.status, "data": m.model_dump_json()})

    def get_message(self, message_id: str) -> MessageEvent:
        return self._require("messages", "message_id", message_id, MessageEvent)

    def message_by_external_id(self, external_id: str) -> Optional[MessageEvent]:
        return self._get("messages", "external_id", external_id, MessageEvent)

    def list_messages(self, case_id: Optional[str] = None) -> list[MessageEvent]:
        if case_id:
            return self._list("SELECT data FROM messages WHERE case_id = ? ORDER BY rowid", (case_id,), MessageEvent)
        return self._list("SELECT data FROM messages ORDER BY rowid", (), MessageEvent)

    def save_escalation(self, e: Escalation) -> None:
        self._upsert("escalations", {"escalation_id": e.escalation_id, "case_id": e.case_id,
                                     "idempotency_key": e.idempotency_key, "data": e.model_dump_json()})

    def escalation_by_key(self, key: str) -> Optional[Escalation]:
        return self._get("escalations", "idempotency_key", key, Escalation)

    def escalations_for_case(self, case_id: str) -> list[Escalation]:
        return self._list("SELECT data FROM escalations WHERE case_id = ? ORDER BY rowid", (case_id,), Escalation)

    def save_referral(self, r: RecoveryReferral) -> None:
        self._upsert("referrals", {"referral_id": r.referral_id, "case_id": r.case_id, "status": r.status,
                                   "idempotency_key": r.idempotency_key, "data": r.model_dump_json()})

    def get_referral(self, referral_id: str) -> RecoveryReferral:
        return self._require("referrals", "referral_id", referral_id, RecoveryReferral)

    def referral_by_key(self, key: str) -> Optional[RecoveryReferral]:
        return self._get("referrals", "idempotency_key", key, RecoveryReferral)

    def referrals_for_case(self, case_id: str) -> list[RecoveryReferral]:
        return self._list("SELECT data FROM referrals WHERE case_id = ? ORDER BY rowid", (case_id,), RecoveryReferral)

    def add_consent_grant(self, g: ConsentGrant) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT INTO consent_grants (case_id, data) VALUES (?, ?)", (g.case_id, g.model_dump_json()))

    def consent_grants_for_case(self, case_id: str) -> list[ConsentGrant]:
        return self._list("SELECT data FROM consent_grants WHERE case_id = ? ORDER BY id", (case_id,), ConsentGrant)

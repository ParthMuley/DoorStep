"""HTTP routes for docs/interface-contract.md v1.0 (thin layer over DoorstepService).

Writes require ``Authorization: Bearer <DEMO_AUTH_TOKEN>``. Every response carries
``schema_version``; ``X-Correlation-ID`` (header) wins over a body correlation_id.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from doorstep.models import SCHEMA_VERSION
from doorstep.services.engine import DoorstepService

from . import schemas as s
from .security import correlation_header, require_demo_token

router = APIRouter()
write = APIRouter(dependencies=[Depends(require_demo_token)])


def svc(request: Request) -> DoorstepService:
    return request.app.state.service


def out(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(status_code=status, content=jsonable_encoder({"schema_version": SCHEMA_VERSION, **payload}))


def pick(header: Optional[str], body: Optional[s.Body]) -> Optional[str]:
    return header or (body.correlation_id if body else None)


# ------------------------------------------------------------------ reads
@router.get("/health")
def health(service: DoorstepService = Depends(svc)):
    return out({"status": "ok", "simulation_mode": True, "databases": service.db.ping()})


@router.get("/cases")
def list_cases(zone_id: Optional[str] = None, resident_status: Optional[str] = None, unresolved: bool = False,
               service: DoorstepService = Depends(svc)):
    return out({"cases": service.list_cases(zone_id, resident_status, unresolved)})


@router.get("/cases/{case_id}")
def get_case_status(case_id: str, corr: Optional[str] = Depends(correlation_header),
                    service: DoorstepService = Depends(svc)):
    return out(service.get_case_status(case_id, corr))


@router.get("/providers")
def providers(service: DoorstepService = Depends(svc)):
    return out(service.registry_view())


@router.get("/zones")
def zones(service: DoorstepService = Depends(svc)):
    return out(service.zones_view())


@router.get("/sim/messages")
def sim_messages(case_id: Optional[str] = None, service: DoorstepService = Depends(svc)):
    return out({"messages": [m.model_dump() for m in service.sim.outbox(case_id)], "simulated": True})


# ----------------------------------------------------------------- writes
@write.post("/demo/reset")
def demo_reset(service: DoorstepService = Depends(svc)):
    return out(service.reset())


@write.post("/demo/warnings")
def start_demo_warning(body: s.WarningBody, corr: Optional[str] = Depends(correlation_header),
                       service: DoorstepService = Depends(svc)):
    return out(service.start_demo_warning(body.zone_id, body.scenario_id, body.alert_source, pick(corr, body)), 201)


@write.post("/residents")
def register_resident(body: s.RegisterResidentBody, service: DoorstepService = Depends(svc)):
    return out(service.register_resident(body.profile, body.consent).model_dump(), 201)


@write.post("/cases/{case_id}/responses")
def submit_resident_response(case_id: str, body: s.ResponseBody, corr: Optional[str] = Depends(correlation_header),
                             service: DoorstepService = Depends(svc)):
    return out(service.submit_resident_response(
        case_id, body.text, body.language, sender=body.sender,
        external_id=body.external_id or body.idempotency_key, correlation_id=pick(corr, body)))


@write.post("/cases/{case_id}/transport/evaluate")
def find_transport(case_id: str, body: s.TransportEvaluateBody, corr: Optional[str] = Depends(correlation_header),
                   service: DoorstepService = Depends(svc)):
    return out(service.evaluate_transport(case_id, body.candidate_offers, body.request_id, pick(corr, body)))


@write.post("/cases/{case_id}/destination/evaluate")
def find_destination(case_id: str, body: s.DestinationEvaluateBody,
                     corr: Optional[str] = Depends(correlation_header), service: DoorstepService = Depends(svc)):
    return out(service.evaluate_destination(case_id, body.candidate_offers, body.request_id, pick(corr, body)))


@write.post("/cases/{case_id}/assignments")
def propose_assignment(case_id: str, body: s.ProposeBody, corr: Optional[str] = Depends(correlation_header),
                       service: DoorstepService = Depends(svc)):
    view, created = service.propose_assignment(
        case_id, transport_offer_id=body.transport_offer_id, destination_offer_id=body.destination_offer_id,
        authorization=body.authorization, idempotency_key=body.idempotency_key, correlation_id=pick(corr, body))
    return out(view, 201 if created else 200)


@write.post("/assignments/{assignment_id}/acceptance")
def accept_assignment(assignment_id: str, body: s.AcceptanceBody, corr: Optional[str] = Depends(correlation_header),
                      service: DoorstepService = Depends(svc)):
    return out(service.respond_assignment(assignment_id, body.provider_id, body.decision, pick(corr, body)))


@write.post("/assignments/{assignment_id}/pickup")
def confirm_pickup(assignment_id: str, body: s.EvidenceBody, corr: Optional[str] = Depends(correlation_header),
                   service: DoorstepService = Depends(svc)):
    return out(service.confirm_pickup(assignment_id, body.evidence, pick(corr, body)))


@write.post("/assignments/{assignment_id}/arrival")
def confirm_arrival(assignment_id: str, body: s.EvidenceBody, corr: Optional[str] = Depends(correlation_header),
                    service: DoorstepService = Depends(svc)):
    return out(service.confirm_arrival(assignment_id, body.evidence, pick(corr, body)))


@write.get("/assignments/{assignment_id}/pickup-details")
def pickup_details(assignment_id: str, provider_id: str, service: DoorstepService = Depends(svc)):
    return out(service.get_pickup_details(assignment_id, provider_id))


@write.post("/cases/{case_id}/recovery-referrals")
def request_recovery_handoff(case_id: str, body: s.RecoveryBody, corr: Optional[str] = Depends(correlation_header),
                             service: DoorstepService = Depends(svc)):
    view, created = service.request_recovery_handoff(
        case_id, share_recovery_needs=body.consent.share_recovery_needs, granted_by=body.consent.granted_by,
        granted_at=body.consent.granted_at, idempotency_key=body.idempotency_key, correlation_id=pick(corr, body))
    return out(view, 201 if created else 200)


@write.post("/recovery-referrals/{referral_id}/response")
def respond_recovery(referral_id: str, body: s.RecoveryResponseBody,
                     corr: Optional[str] = Depends(correlation_header), service: DoorstepService = Depends(svc)):
    return out(service.respond_recovery(referral_id, body.provider_id, body.decision, pick(corr, body)))


@write.post("/cases/{case_id}/escalations")
def escalate_case(case_id: str, body: s.EscalateBody, corr: Optional[str] = Depends(correlation_header),
                  service: DoorstepService = Depends(svc)):
    view, created = service.escalate_case(case_id, body.reason, idempotency_key=body.idempotency_key,
                                          correlation_id=pick(corr, body))
    return out(view, 201 if created else 200)


# ------------------------------------------------- message simulator (B extras)
@write.post("/sim/inbound")
def sim_inbound(body: s.InboundSmsBody, service: DoorstepService = Depends(svc)):
    return out(service.inbound_sms(body.sender, body.text, body.external_id, body.language))


@write.post("/sim/delivery")
def sim_delivery(body: s.DeliveryBody, service: DoorstepService = Depends(svc)):
    return out(service.set_delivery_outcome(body.message_id, body.delivered))


@write.post("/sim/cases/{case_id}/no-reply-deadline")
def sim_no_reply(case_id: str, service: DoorstepService = Depends(svc)):
    return out(service.mark_no_reply_deadline(case_id))


@write.post("/sim/escalation-ack")
def sim_escalation_ack(body: s.EscalationAckBody, service: DoorstepService = Depends(svc)):
    return out(service.set_escalation_ack(body.acknowledge))


router.include_router(write)

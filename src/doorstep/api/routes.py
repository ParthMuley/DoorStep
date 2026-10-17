"""HTTP routes for the shared contract. Thin layer over DoorstepService.

Every route except /health requires the ``X-Demo-Token`` header.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request

from doorstep.services.engine import DoorstepService

from . import schemas as s
from .security import require_demo_token

router = APIRouter()
protected = APIRouter(dependencies=[Depends(require_demo_token)])


def svc(request: Request) -> DoorstepService:
    return request.app.state.service


@router.get("/health")
def health():
    return {"status": "ok", "service": "doorstep-backend", "simulation_mode": True}


# --- demo control ---------------------------------------------------------
@protected.post("/demo/reset")
def demo_reset(service: DoorstepService = Depends(svc)):
    return service.reset()


@protected.post("/demo/warnings")
def start_demo_warning(body: s.WarningBody, service: DoorstepService = Depends(svc)):
    return service.start_demo_warning(body.zone_id, body.scenario_id, body.correlation_id)


@protected.post("/reports")
def report_hazard(body: s.ReportBody, service: DoorstepService = Depends(svc)):
    return service.report_hazard(body.zone_id, body.text, body.reporter)


@protected.post("/residents")
def register_resident(body: s.RegisterResidentBody, service: DoorstepService = Depends(svc)):
    return service.register_resident(body.profile, body.consent).model_dump()


# --- cases ------------------------------------------------------------------
@protected.get("/cases")
def list_cases(status: Optional[str] = None, unresolved: bool = False, service: DoorstepService = Depends(svc)):
    return {"cases": service.list_cases(status, unresolved)}


@protected.get("/cases/{case_id}")
def get_case_status(case_id: str, service: DoorstepService = Depends(svc)):
    return service.get_case_status(case_id)


@protected.post("/cases/{case_id}/responses")
def submit_resident_response(case_id: str, body: s.ResponseBody, service: DoorstepService = Depends(svc)):
    return service.submit_resident_response(case_id, body.text, body.language, sender=body.sender,
                                            external_id=body.external_id, correlation_id=body.correlation_id)


@protected.post("/cases/{case_id}/needs/confirm")
def confirm_needs(case_id: str, body: s.ConfirmNeedsBody, service: DoorstepService = Depends(svc)):
    return service.confirm_needs(case_id, confirmed=body.confirmed, confirmed_by=body.confirmed_by,
                                 needs=body.needs, correlation_id=body.correlation_id)


@protected.post("/cases/{case_id}/recovery")
def request_recovery_handoff(case_id: str, body: s.RecoveryBody, service: DoorstepService = Depends(svc)):
    return service.request_recovery_handoff(case_id, body.consent, body.granted_by, body.correlation_id)


@protected.post("/cases/{case_id}/escalate")
def escalate_case(case_id: str, body: s.EscalateBody, service: DoorstepService = Depends(svc)):
    return service.escalate_case(case_id, body.reason, body.correlation_id).model_dump()


# --- providers / offers / assignments -----------------------------------------
@protected.post("/transport/find")
def find_transport(body: s.FindBody, service: DoorstepService = Depends(svc)):
    return service.find_transport(body.case_id, body.correlation_id)


@protected.post("/destinations/find")
def find_destination(body: s.FindBody, service: DoorstepService = Depends(svc)):
    return service.find_destination(body.case_id, body.correlation_id)


@protected.post("/assignments/propose")
def propose_assignment(body: s.ProposeBody, service: DoorstepService = Depends(svc)):
    return service.propose_assignment(body.case_id, body.offer_id, body.correlation_id).model_dump()


@protected.post("/assignments/{assignment_id}/respond")
def accept_assignment(assignment_id: str, body: s.ProviderResponseBody, service: DoorstepService = Depends(svc)):
    return service.respond_assignment(assignment_id, body.provider_id, body.accept, body.correlation_id)


@protected.get("/assignments/{assignment_id}/pickup-details")
def pickup_details(assignment_id: str, provider_id: str, service: DoorstepService = Depends(svc)):
    return service.get_pickup_details(assignment_id, provider_id)


@protected.post("/assignments/{assignment_id}/pickup")
def confirm_pickup(assignment_id: str, body: s.EvidenceBody, service: DoorstepService = Depends(svc)):
    return service.confirm_pickup(assignment_id, body.evidence, body.correlation_id)


@protected.post("/assignments/{assignment_id}/arrival")
def confirm_arrival(assignment_id: str, body: s.EvidenceBody, service: DoorstepService = Depends(svc)):
    return service.confirm_arrival(assignment_id, body.evidence, body.correlation_id)


@protected.post("/recovery/{referral_id}/respond")
def respond_recovery(referral_id: str, body: s.ProviderResponseBody, service: DoorstepService = Depends(svc)):
    return service.respond_recovery(referral_id, body.provider_id, body.accept, body.correlation_id).model_dump()


@protected.get("/providers")
def providers(service: DoorstepService = Depends(svc)):
    return service.providers_view()


@protected.get("/zones")
def zones(service: DoorstepService = Depends(svc)):
    return service.zones_view()


# --- message simulator ----------------------------------------------------------
@protected.get("/sim/messages")
def sim_messages(case_id: Optional[str] = None, service: DoorstepService = Depends(svc)):
    return {"messages": [m.model_dump() for m in service.sim.outbox(case_id)], "simulated": True}


@protected.post("/sim/inbound")
def sim_inbound(body: s.InboundSmsBody, service: DoorstepService = Depends(svc)):
    return service.inbound_sms(body.sender, body.text, body.external_id, body.language)


@protected.post("/sim/delivery")
def sim_delivery(body: s.DeliveryBody, service: DoorstepService = Depends(svc)):
    return service.set_delivery_outcome(body.message_id, body.delivered)


@protected.post("/sim/cases/{case_id}/no-reply-deadline")
def sim_no_reply(case_id: str, service: DoorstepService = Depends(svc)):
    return service.mark_no_reply_deadline(case_id)


@protected.post("/sim/escalation-ack")
def sim_escalation_ack(body: s.EscalationAckBody, service: DoorstepService = Depends(svc)):
    return service.set_escalation_ack(body.acknowledge)


router.include_router(protected)

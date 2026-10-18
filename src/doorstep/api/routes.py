"""HTTP routes for docs/interface-contract.md v1.0 (thin layer over DoorstepService).

Writes require ``Authorization: Bearer <DEMO_AUTH_TOKEN>``. Every response carries
``schema_version``; ``X-Correlation-ID`` (header) wins over a body correlation_id.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from doorstep.models import SCHEMA_VERSION
from doorstep.services.engine import DoorstepService

from . import schemas as s
from .security import correlation_header, is_agent, require_agent, require_agent_token, require_demo_token

router = APIRouter()
write = APIRouter(dependencies=[Depends(require_demo_token)])


def svc(request: Request) -> DoorstepService:
    return request.app.state.service


V2 = "2.0"


def out(payload: dict[str, Any], status: int = 200, version: str = SCHEMA_VERSION) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(status_code=status, content=jsonable_encoder({"schema_version": version, **payload}))


def pick(header: Optional[str], body: Optional[s.Body]) -> Optional[str]:
    return header or (body.correlation_id if body else None)


# ------------------------------------------------------------------ reads
@router.get("/health")
def health(service: DoorstepService = Depends(svc)):
    feeds = list(service.db.coll("feeds").find({}))
    return out({"status": "ok", "version": "2.2.0", "simulation_mode": True, "databases": service.db.ping(),
                "alerts": {"feed_freshness": service.alerts.simulated_freshness(),
                           "last_ingest_at": max((f.get("last_ingest_at") or "" for f in feeds), default=None) or None}})


@router.get("/dashboard/summary")
def dashboard_summary(service: DoorstepService = Depends(svc)):
    return out(service.dashboard.summary(), version=V2)


@router.get("/dashboard/cases")
def dashboard_cases(service: DoorstepService = Depends(svc)):
    return out(service.dashboard.cases(), version=V2)


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


@router.get("/organizations")
def list_organizations(service: DoorstepService = Depends(svc)):
    return out({"organizations": service.registry.list_organizations(), "simulated": True}, version=V2)


@router.get("/zones")
def zones(service: DoorstepService = Depends(svc)):
    return out(service.zones_view())


@router.get("/demo/feeds/caloes")
def synthetic_caloes_feed(service: DoorstepService = Depends(svc)):
    """Synthetic feed in the exact Cal OES GeoJSON shape (raw, no envelope)."""
    return service.alerts.feed.render_caloes()


@router.get("/demo/feeds/news")
def synthetic_news_feed(service: DoorstepService = Depends(svc)):
    return service.closures.feed_news()


@router.get("/demo/feeds/closures")
def synthetic_official_closures_feed(service: DoorstepService = Depends(svc)):
    return service.closures.feed_official()


@router.get("/closures")
def list_closures(service: DoorstepService = Depends(svc)):
    return out(service.closures.list_view(), version=V2)


@router.get("/regions/near")
def regions_near(alert_id: Optional[str] = None, zone_id: Optional[str] = None, lat: Optional[float] = None,
                 lon: Optional[float] = None, radius_km: Optional[float] = None, calamity_type: Optional[str] = None,
                 service_type: Optional[str] = Query(default=None, alias="service"),
                 service: DoorstepService = Depends(svc)):
    return out(service.alerts.regions_near_view(alert_id=alert_id, zone_id=zone_id, lat=lat, lon=lon,
                                                radius_km=radius_km, calamity_type=calamity_type,
                                                service=service_type), version=V2)


@router.get("/agents")
def list_agents(service: DoorstepService = Depends(svc)):
    return out({"agents": service.store.partners.list_agents()}, version=V2)


@router.get("/alerts/active")
def alerts_active(service: DoorstepService = Depends(svc)):
    return out(service.alerts.active_view(), version=V2)


@router.get("/alerts/{alert_id}/outreach")
def alert_outreach(alert_id: str, service: DoorstepService = Depends(svc)):
    return out(service.alerts.outreach_summary(alert_id), version=V2)


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
def register_resident(body: s.RegisterResidentBody, corr: Optional[str] = Depends(correlation_header),
                      service: DoorstepService = Depends(svc)):
    return out(service.registry.register_resident(body.resident, pick(corr, body) or ""), 201, V2)


@write.post("/organizations")
def register_organization(body: s.RegisterOrganizationBody, corr: Optional[str] = Depends(correlation_header),
                          service: DoorstepService = Depends(svc)):
    view, created = service.registry.register_organization(body.organization, pick(corr, body) or "")
    return out(view, 201 if created else 200, V2)


@write.post("/regions")
def create_region(body: s.RegionBody, corr: Optional[str] = Depends(correlation_header),
                  service: DoorstepService = Depends(svc)):
    return out(service.registry.create_region(body.region, pick(corr, body) or ""), 201, V2)


@write.post("/regions/{region_id}/orgs/{org_id}")
def add_presence(region_id: str, org_id: str, corr: Optional[str] = Depends(correlation_header),
                 service: DoorstepService = Depends(svc)):
    return out(service.registry.add_presence(region_id, org_id, corr or ""), 201, V2)


@write.post("/regions/{region_id}/orgs/{org_id}/volunteers")
def add_volunteer(region_id: str, org_id: str, body: s.AddVolunteerBody,
                  corr: Optional[str] = Depends(correlation_header), service: DoorstepService = Depends(svc)):
    return out(service.registry.add_volunteer(region_id, org_id, body.volunteer, pick(corr, body) or ""), 201, V2)


@write.post("/regions/{region_id}/orgs/{org_id}/shelter_sites")
def add_site(region_id: str, org_id: str, body: s.SiteBody, corr: Optional[str] = Depends(correlation_header),
             service: DoorstepService = Depends(svc)):
    return out(service.registry.add_site(region_id, org_id, body.site, pick(corr, body) or ""), 201, V2)


@write.post("/alerts/{alert_id}/volunteers/{volunteer_id}/availability", dependencies=[Depends(require_agent_token)])
def record_availability(alert_id: str, volunteer_id: str, body: s.AvailabilityBody,
                        corr: Optional[str] = Depends(correlation_header), service: DoorstepService = Depends(svc)):
    if body.sender is not None:  # v2.2: if relayed from ASI:One, it must be this volunteer's linked account
        link = service.links.by_address(body.sender)
        if not link or link["role"] != "VOLUNTEER" or link["person_id"] != volunteer_id:
            return out({"error": "UNAUTHORIZED", "detail": "Sender is not the ASI:One account linked to this volunteer",
                        "reasons": ["UNKNOWN_SENDER"], "correlation_id": pick(corr, body)}, 403, V2)
    return out(service.registry.record_availability(
        alert_id, volunteer_id, org_id=body.org_id, available=body.available, responded_at=body.responded_at,
        idempotency_key=body.idempotency_key, correlation_id=pick(corr, body) or ""), version=V2)


@write.put("/agents/{role}")
def register_agent(role: str, body: s.AgentAddressBody, service: DoorstepService = Depends(svc)):
    service.store.partners.set_agent(role, body.agent_address)
    return out({"role": role, "agent_address": body.agent_address}, version=V2)


@write.post("/cases/{case_id}/responses")
def submit_resident_response(case_id: str, body: s.ResponseBody, corr: Optional[str] = Depends(correlation_header),
                             x_agent_token: Optional[str] = Header(default=None),
                             service: DoorstepService = Depends(svc)):
    return out(service.submit_resident_response(
        case_id, body.text, body.language, sender=body.sender,
        external_id=body.external_id or body.idempotency_key, correlation_id=pick(corr, body),
        via_doorstep_agent=is_agent("DOORSTEP", x_agent_token)))


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


@write.post("/alerts/ingest")
def alerts_ingest(body: s.AlertIngestBody, corr: Optional[str] = Depends(correlation_header),
                  service: DoorstepService = Depends(svc)):
    return out(service.alerts.ingest(
        source_id=body.source.source_id, source_type=body.source.source_type, url=body.source.url,
        fetched_at=body.source.fetched_at, fetch_ok=body.fetch_ok, http_status=body.http_status, error=body.error,
        payload=body.payload, idempotency_key=body.idempotency_key, correlation_id=pick(corr, body) or ""), version=V2)


@write.post("/demo/alerts/trigger")
def demo_alerts_trigger(body: s.AlertTriggerBody, corr: Optional[str] = Depends(correlation_header),
                        service: DoorstepService = Depends(svc)):
    st = service.alerts.feed.trigger(body.action, preset=body.preset, zone_id=body.zone_id, status=body.status,
                                     event_type=body.event_type, geometry=body.geometry,
                                     expires_in_minutes=body.expires_in_minutes,
                                     freeze_age_minutes=body.freeze_age_minutes)
    poll = None
    if body.poll_now:
        from doorstep.models import utc_now_iso

        poll = service.alerts.ingest(source_id="SYNTHETIC_CALOES", source_type="OFFICIAL_SIMULATION",
                                     url="/demo/feeds/caloes", fetched_at=utc_now_iso(), fetch_ok=True,
                                     http_status=200, error=None, payload=service.alerts.feed.render_caloes(),
                                     idempotency_key=f"SYNTHETIC_CALOES:poll_now:v{st.version}",
                                     correlation_id=pick(corr, body) or "")
    return out({"action": body.action, "feed_version": st.version, "synthetic_feed_url": "/demo/feeds/caloes",
                "frozen": st.frozen_at_ms is not None, "poll_result": poll}, version=V2)


@write.post("/alerts/{alert_id}/outreach", dependencies=[Depends(require_agent_token)])
def alert_outreach_start(alert_id: str, body: s.OutreachBody, corr: Optional[str] = Depends(correlation_header),
                         service: DoorstepService = Depends(svc)):
    return out(service.alerts.start_outreach(alert_id, body.idempotency_key, body.max_orgs,
                                             pick(corr, body) or ""), version=V2)


@write.post("/sim/outreach/{alert_id}/deadline")
def sim_outreach_deadline(alert_id: str, service: DoorstepService = Depends(svc)):
    return out(service.alerts.outreach_deadline(alert_id), version=V2)


@write.post("/demo/closures/trigger")
def demo_closures_trigger(body: s.ClosureTriggerBody, service: DoorstepService = Depends(svc)):
    return out(service.closures.trigger(body.action, road_name=body.road_name, status=body.status,
                                        headline=body.headline, body=body.body,
                                        expires_in_minutes=body.expires_in_minutes), version=V2)


@write.post("/closures/ingest")
def closures_ingest(body: s.ClosureIngestBody, corr: Optional[str] = Depends(correlation_header),
                    service: DoorstepService = Depends(svc)):
    return out(service.closures.ingest(source_id=body.source.source_id, source_type=body.source.source_type,
                                       url=body.source.url, fetched_at=body.source.fetched_at,
                                       items=[i.model_dump() for i in body.items],
                                       idempotency_key=body.idempotency_key,
                                       correlation_id=pick(corr, body) or ""), version=V2)


@write.post("/routes/constraints")
def route_constraints(body: s.RouteConstraintsBody, corr: Optional[str] = Depends(correlation_header),
                      service: DoorstepService = Depends(svc)):
    return out(service.routes.constraints(body.assignment_id, idempotency_key=body.idempotency_key,
                                          correlation_id=pick(corr, body)), version=V2)


@write.post("/routes/previews")
def route_previews(body: s.RoutePreviewBody, corr: Optional[str] = Depends(correlation_header),
                   service: DoorstepService = Depends(svc)):
    return out(service.routes.preview(body.route_request_id, provider=body.provider, polyline=body.polyline,
                                      distance_m=body.distance_m, duration_s=body.duration_s,
                                      provider_notices=body.provider_notices, idempotency_key=body.idempotency_key,
                                      correlation_id=pick(corr, body)), version=V2)


@write.post("/cases/{case_id}/recovery")
def case_recovery(case_id: str, body: s.RecoveryV2Body, corr: Optional[str] = Depends(correlation_header),
                  service: DoorstepService = Depends(svc)):
    view, created = service.recovery.request(
        case_id, share_recovery_needs=body.consent.share_recovery_needs, granted_by=body.consent.granted_by,
        granted_at=body.consent.granted_at, help_types=body.help_types, idempotency_key=body.idempotency_key,
        correlation_id=pick(corr, body))
    return out(view, 201 if created else 200, V2)


@write.post("/recovery/{referral_id}/respond", dependencies=[Depends(require_agent_token)])
def recovery_respond(referral_id: str, body: s.RecoveryRespondBody, corr: Optional[str] = Depends(correlation_header),
                     service: DoorstepService = Depends(svc)):
    return out(service.recovery.respond(referral_id, org_id=body.org_id, decision=body.decision,
                                        evidence=body.evidence, idempotency_key=body.idempotency_key,
                                        correlation_id=pick(corr, body)), version=V2)


@write.post("/matches/propose")
def matches_propose(body: s.ProposeMatchBody, corr: Optional[str] = Depends(correlation_header),
                    service: DoorstepService = Depends(svc)):
    sel = body.select or s.MatchSelect()
    view, created = service.matching.propose(
        body.case_id, idempotency_key=body.idempotency_key, create_proposal=body.create_proposal,
        authorization=body.authorization, select_volunteer=sel.volunteer_id, select_site=sel.site_id,
        correlation_id=pick(corr, body))
    return out(view, 201 if created else 200, V2)


@write.post("/assignments/{assignment_id}/accept", dependencies=[Depends(require_agent_token)])
def assignment_accept(assignment_id: str, body: s.AcceptV2Body, corr: Optional[str] = Depends(correlation_header),
                      service: DoorstepService = Depends(svc)):
    return out(service.matching.accept(
        assignment_id, org_id=body.org_id, volunteer_id=body.volunteer_id, site_id=body.site_id,
        decision=body.decision, idempotency_key=body.idempotency_key, correlation_id=pick(corr, body)), version=V2)


@write.post("/cases/{case_id}/escalate")
def case_escalate(case_id: str, body: s.EscalateBody, corr: Optional[str] = Depends(correlation_header),
                  service: DoorstepService = Depends(svc)):
    view, created = service.matching.escalate(case_id, body.reason, idempotency_key=body.idempotency_key,
                                              correlation_id=pick(corr, body))
    return out(view, 201 if created else 200, V2)


@write.post("/escalations/{escalation_id}/ack")
def escalation_ack(escalation_id: str, body: s.EscalationAckBodyV2, corr: Optional[str] = Depends(correlation_header),
                   service: DoorstepService = Depends(svc)):
    return out(service.matching.acknowledge(escalation_id, body.status,
                                            recipient_agent_address=body.recipient_agent_address,
                                            idempotency_key=body.idempotency_key,
                                            correlation_id=pick(corr, body)), version=V2)


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



# ---- contract v2.2: ASI:One linking, registration, invites, approval, deadlines, maps ----
DOORSTEP_ONLY = [Depends(require_agent("DOORSTEP"))]


@write.post("/link", dependencies=DOORSTEP_ONLY)
def link_account(body: s.LinkBody, corr: Optional[str] = Depends(correlation_header),
                 service: DoorstepService = Depends(svc)):
    return out(service.links.link(body.code, body.asi_one_address, pick(corr, body) or ""), version=V2)


@write.post("/unlink", dependencies=DOORSTEP_ONLY)
def unlink_account(body: s.UnlinkBody, corr: Optional[str] = Depends(correlation_header),
                   service: DoorstepService = Depends(svc)):
    return out(service.links.unlink(body.asi_one_address, pick(corr, body) or ""), version=V2)


@write.post("/register", dependencies=DOORSTEP_ONLY)
def register_and_link(body: s.RegisterBody, corr: Optional[str] = Depends(correlation_header),
                      service: DoorstepService = Depends(svc)):
    return out(service.links.register(body.role, body.asi_one_address, body.profile, body.org_id,
                                      pick(corr, body) or ""), 201, V2)


@write.post("/organizations/{org_id}/invites")
def issue_invite(org_id: str, body: s.InviteBody, corr: Optional[str] = Depends(correlation_header),
                 service: DoorstepService = Depends(svc)):
    return out(service.links.invite(org_id, body.volunteer_id, body.display_name, pick(corr, body) or ""), 201, V2)


@write.post("/orgs/{org_id}/volunteers/{volunteer_id}/approve")
def approve_volunteer(org_id: str, volunteer_id: str, body: Optional[s.ApproveBody] = None,
                      corr: Optional[str] = Depends(correlation_header), service: DoorstepService = Depends(svc)):
    approved = True if body is None else body.approved
    return out(service.links.approve_volunteer(org_id, volunteer_id, approved, pick(corr, body) or ""), version=V2)


@router.get("/volunteers/pending")
def pending_volunteers(org_id: Optional[str] = None, service: DoorstepService = Depends(svc)):
    return out({"volunteers": service.links.pending_volunteers(org_id)}, version=V2)


@write.post("/deadlines/sweep", dependencies=[Depends(require_agent("DOORSTEP", "CALAMITY"))])
def deadline_sweep(body: Optional[s.SweepBody] = None, corr: Optional[str] = Depends(correlation_header),
                   service: DoorstepService = Depends(svc)):
    return out(service.deadlines.sweep(pick(corr, body) or ""), version=V2)


@router.put("/maps/{map_id}", dependencies=[Depends(require_agent("ROUTE"))])
async def put_map(map_id: str, request: Request, assignment_id: Optional[str] = None,
                  service: DoorstepService = Depends(svc)):
    if request.headers.get("content-type", "").split(";")[0].strip() != "image/png":
        return out({"error": "VALIDATION_ERROR", "detail": "Content-Type must be image/png", "reasons": []}, 415, V2)
    data = await request.body()
    return out(service.maps.put(map_id, data, assignment_id=assignment_id, base_url=str(request.base_url)), 201, V2)


@router.get("/maps/{map_id}.png")
def get_map(map_id: str, service: DoorstepService = Depends(svc)):
    return Response(content=service.maps.get(map_id), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600", "X-Robots-Tag": "noindex"})


router.include_router(write)

"""Contract v2.0/v2.1 calls (docs/interface-contract.md §5; team plan rev 3) for A's agents.

Same transport, auth, correlation and error handling as v1 (`DoorstepBackend`); v1
methods are removed in the switch-over PR window. Rev 3: one Volunteer Network agent
acts for all partner orgs; every write names its `org_id` and B checks it.
"""

import os
from typing import Any

from doorstep.workflows.backend_client import BackendError, DoorstepBackend  # noqa: F401

V2 = "2.0"
DEFAULT_NETWORK_TOKEN = "change-me-network-agent-token"  # B's default; real value only in .env


def network_agent_token() -> str:
    return os.getenv("NETWORK_AGENT_TOKEN") or DEFAULT_NETWORK_TOKEN


DEFAULT_DOORSTEP_TOKEN = "change-me-doorstep-agent-token"  # rev 4 §0.5; real value only in .env


def doorstep_agent_token() -> str:
    return os.getenv("DOORSTEP_AGENT_TOKEN") or DEFAULT_DOORSTEP_TOKEN


class DoorstepBackendV2(DoorstepBackend):
    """`agent_token` is set only for the Volunteer Network agent: network-acting routes
    (outreach, availability, accept, recovery respond) need `X-Agent-Token` (contract v2.1 §1)."""

    def __init__(self, *args: Any, agent_token: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.agent_token = agent_token

    def _net(self) -> dict[str, str]:
        return {"X-Agent-Token": self.agent_token} if self.agent_token else {}

    async def register_agent(self, role: str, agent_address: str, correlation_id: str) -> dict[str, Any]:
        """`PUT /agents/{role}`: publish this agent's address so B can hand it out (seed stays private)."""
        return await self._request("PUT", f"/agents/{role}", correlation_id, {"agent_address": agent_address})
    @staticmethod
    def _v2(correlation_id: str, **fields: Any) -> dict[str, Any]:
        return {"schema_version": V2, "correlation_id": correlation_id,
                **{k: v for k, v in fields.items() if v is not None}}

    # ---- alerts (Calamity Checker)
    async def ingest_alerts(self, source: dict[str, Any], fetch_ok: bool, http_status: int | None,
                            error: str | None, payload: dict[str, Any] | None, idempotency_key: str,
                            correlation_id: str) -> dict[str, Any]:
        body = {"schema_version": V2, "correlation_id": correlation_id, "source": source, "fetch_ok": fetch_ok,
                "http_status": http_status, "error": error, "payload": payload, "idempotency_key": idempotency_key}
        return await self._request("POST", "/alerts/ingest", correlation_id, body)

    async def active_alerts(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", "/alerts/active", correlation_id)

    async def trigger_alert(self, action: str, correlation_id: str, preset: str | None = None,
                            poll_now: bool = False) -> dict[str, Any]:
        return await self._request("POST", "/demo/alerts/trigger", correlation_id,
                                   self._v2(correlation_id, action=action, preset=preset, poll_now=poll_now))

    async def alert_outreach(self, alert_id: str, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/alerts/{alert_id}/outreach", correlation_id)

    # ---- volunteer network (rev 3: alert-scoped, location-first; no per-org agents)
    async def regions_near(self, correlation_id: str, zone_id: str | None = None) -> dict[str, Any]:
        return await self._request("GET", "/regions/near", correlation_id,
                                   params={"zone_id": zone_id} if zone_id else None)

    async def start_outreach(self, alert_id: str, idempotency_key: str, correlation_id: str,
                             max_orgs: int | None = None) -> dict[str, Any]:
        return await self._request("POST", f"/alerts/{alert_id}/outreach", correlation_id,
                                   self._v2(correlation_id, idempotency_key=idempotency_key, max_orgs=max_orgs),
                                   extra_headers=self._net())

    async def record_availability(self, alert_id: str, volunteer_id: str, org_id: str, available: bool,
                                  responded_at: str, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/alerts/{alert_id}/volunteers/{volunteer_id}/availability", correlation_id,
            self._v2(correlation_id, org_id=org_id, available=available, responded_at=responded_at,
                     idempotency_key=idempotency_key), extra_headers=self._net())

    # ---- matching + assignments
    async def propose_match(self, case_id: str, create_proposal: bool, idempotency_key: str, correlation_id: str,
                            select_volunteer_id: str | None = None,
                            select_site_id: str | None = None) -> dict[str, Any]:
        return await self._request("POST", "/matches/propose", correlation_id, self._v2(
            correlation_id, case_id=case_id, create_proposal=create_proposal, idempotency_key=idempotency_key,
            authorization="SIMULATED_PREAPPROVED",
            select={"volunteer_id": select_volunteer_id, "site_id": select_site_id}))

    async def accept_v2(self, assignment_id: str, org_id: str, decision: str, idempotency_key: str,
                        correlation_id: str, volunteer_id: str | None = None,
                        site_id: str | None = None) -> dict[str, Any]:
        return await self._request("POST", f"/assignments/{assignment_id}/accept", correlation_id, self._v2(
            correlation_id, org_id=org_id, volunteer_id=volunteer_id, site_id=site_id, decision=decision,
            idempotency_key=idempotency_key), extra_headers=self._net())

    async def pickup_v2(self, assignment_id: str, evidence: dict[str, Any], idempotency_key: str,
                        correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/assignments/{assignment_id}/pickup", correlation_id,
                                   self._v2(correlation_id, evidence=evidence, idempotency_key=idempotency_key))

    async def arrival_v2(self, assignment_id: str, evidence: dict[str, Any], idempotency_key: str,
                         correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/assignments/{assignment_id}/arrival", correlation_id,
                                   self._v2(correlation_id, evidence=evidence, idempotency_key=idempotency_key))

    # ---- escalation
    async def escalate(self, case_id: str, reason: str, idempotency_key: str,
                       correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/escalate", correlation_id,
                                   self._v2(correlation_id, reason=reason, idempotency_key=idempotency_key))

    async def ack_escalation(self, escalation_id: str, recipient_agent_address: str, idempotency_key: str,
                             correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/escalations/{escalation_id}/ack", correlation_id, self._v2(
            correlation_id, status="ACKNOWLEDGED_REQUEST_ONLY", recipient_agent_address=recipient_agent_address,
            idempotency_key=idempotency_key))

    # ---- post-calamity
    async def request_recovery(self, case_id: str, help_types: list[str], share_recovery_needs: bool,
                               granted_by: str, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/recovery", correlation_id, self._v2(
            correlation_id, help_types=help_types, idempotency_key=idempotency_key,
            consent={"share_recovery_needs": share_recovery_needs, "granted_by": granted_by}))

    async def respond_recovery(self, referral_id: str, org_id: str, decision: str, idempotency_key: str,
                               correlation_id: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", f"/recovery/{referral_id}/respond", correlation_id, self._v2(
            correlation_id, org_id=org_id, decision=decision, evidence=evidence, idempotency_key=idempotency_key),
            extra_headers=self._net())

    # ---- road closures (News agent)
    async def news_feed(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", "/demo/feeds/news", correlation_id)

    async def official_closures_feed(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", "/demo/feeds/closures", correlation_id)

    async def ingest_closures(self, source: dict[str, Any], items: list[dict[str, Any]], idempotency_key: str,
                              correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", "/closures/ingest", correlation_id, self._v2(
            correlation_id, source=source, items=items, idempotency_key=idempotency_key))

    async def closures(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", "/closures", correlation_id)

    async def trigger_closure(self, action: str, correlation_id: str, road_name: str | None = None,
                              headline: str | None = None, body: str | None = None) -> dict[str, Any]:
        return await self._request("POST", "/demo/closures/trigger", correlation_id, self._v2(
            correlation_id, action=action, road_name=road_name, headline=headline, body=body))

    # ---- routes (Route agent; contract §5.10)
    async def route_constraints(self, assignment_id: str, idempotency_key: str,
                                correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", "/routes/constraints", correlation_id, self._v2(
            correlation_id, assignment_id=assignment_id, idempotency_key=idempotency_key))

    async def route_preview(self, route_request_id: str, polyline: dict[str, Any] | None, distance_m: int | None,
                            duration_s: int | None, provider_notices: list[dict[str, Any]], computed_at: str,
                            idempotency_key: str, correlation_id: str) -> dict[str, Any]:
        body = {"schema_version": V2, "correlation_id": correlation_id, "route_request_id": route_request_id,
                "provider": "HERE", "polyline": polyline, "distance_m": distance_m, "duration_s": duration_s,
                "provider_notices": provider_notices, "computed_at": computed_at,
                "idempotency_key": idempotency_key}
        return await self._request("POST", "/routes/previews", correlation_id, body)

    # ---- rev 4: account linking + deadlines (contract v2.2, plan §0.4-0.5)
    async def link(self, code: str, asi_one_address: str, correlation_id: str) -> dict[str, Any]:
        """`POST /link`: only the Doorstep agent calls this, with the sender address taken from
        the ASI:One message envelope (never from typed text) and its own agent token."""
        return await self._request("POST", "/link", correlation_id,
                                   self._v2(correlation_id, code=code, asi_one_address=asi_one_address),
                                   extra_headers={"X-Agent-Token": doorstep_agent_token()})

    async def register(self, role: str, asi_one_address: str, profile: dict[str, Any], org_id: str | None,
                       correlation_id: str) -> dict[str, Any]:
        """`POST /register` (plan rev 5): create the person and link the envelope sender."""
        return await self._request("POST", "/register", correlation_id, self._v2(
            correlation_id, role=role, asi_one_address=asi_one_address, profile=profile, org_id=org_id),
            extra_headers={"X-Agent-Token": doorstep_agent_token()})

    async def resident_reply(self, case_id: str, text: str, sender: str, correlation_id: str,
                             language: str | None = None, external_id: str | None = None) -> dict[str, Any]:
        """Resident answer arriving through the Doorstep agent (carries the Doorstep token)."""
        return await self._request("POST", f"/cases/{case_id}/responses", correlation_id, self._body(
            correlation_id, text=text, sender=sender, language=language, external_id=external_id),
            extra_headers={"X-Agent-Token": doorstep_agent_token()})

    async def deadline_sweep(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", "/deadlines/sweep", correlation_id, self._v2(correlation_id),
                                   extra_headers={"X-Agent-Token": doorstep_agent_token()})

    # ---- card data
    async def dashboard_summary(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", "/dashboard/summary", correlation_id)

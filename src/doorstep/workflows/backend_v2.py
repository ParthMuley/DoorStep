"""Contract v2.0 calls (docs/interface-contract.md §5) for A's agents.

Same transport, auth, correlation and error handling as v1 (`DoorstepBackend`); v1
methods are removed in the switch-over PR window. Org-scoped routes send
`X-Org-Agent: <org_id>` so an organization agent can only reach its own org's data.
"""

from typing import Any

from doorstep.workflows.backend_client import BackendError, DoorstepBackend  # noqa: F401

V2 = "2.0"


class DoorstepBackendV2(DoorstepBackend):
    @staticmethod
    def _v2(correlation_id: str, **fields: Any) -> dict[str, Any]:
        return {"schema_version": V2, "correlation_id": correlation_id,
                **{k: v for k, v in fields.items() if v is not None}}

    @staticmethod
    def _org(org_id: str) -> dict[str, str]:
        return {"X-Org-Agent": org_id}

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

    # ---- organizations (Organization agents; org-scoped)
    async def start_outreach(self, org_id: str, alert_id: str, idempotency_key: str,
                             correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/orgs/{org_id}/outreach", correlation_id,
                                   self._v2(correlation_id, alert_id=alert_id, idempotency_key=idempotency_key),
                                   extra_headers=self._org(org_id))

    async def org_volunteers(self, org_id: str, correlation_id: str, alert_id: str | None = None) -> dict[str, Any]:
        params = {"alert_id": alert_id} if alert_id else None
        return await self._request("GET", f"/orgs/{org_id}/volunteers", correlation_id, params=params,
                                   extra_headers=self._org(org_id))

    async def record_availability(self, org_id: str, volunteer_id: str, alert_id: str, available: bool,
                                  responded_at: str, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/orgs/{org_id}/volunteers/{volunteer_id}/availability", correlation_id,
            self._v2(correlation_id, alert_id=alert_id, available=available, responded_at=responded_at,
                     idempotency_key=idempotency_key), extra_headers=self._org(org_id))

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
            idempotency_key=idempotency_key), extra_headers=self._org(org_id))

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
            extra_headers=self._org(org_id))

    # ---- card data
    async def dashboard_summary(self, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", "/dashboard/summary", correlation_id)

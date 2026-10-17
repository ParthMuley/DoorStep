"""DoorstepBackend: the coordinator's only path to case state (Developer B's API).

Talks HTTP to docs/interface-contract.md v1.0 section 3; never imports B's services.
B's backend is the source of truth: the coordinator reads state back after every write.
"""

import os
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_DEMO_TOKEN = "change-me-local-demo-token"  # matches B's default and .env.example


class BackendError(Exception):
    """Non-2xx response. 409 = business-rule refusal (e.g. UNSAFE_ZONE, NEEDS_NOT_CONFIRMED)."""

    def __init__(self, status_code: int, code: str, detail: str, reasons: list[str] | None = None):
        super().__init__(f"{status_code} {code}: {detail}")
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.reasons = reasons or []


class DoorstepBackend:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self.base_url = (base_url or os.getenv("DOORSTEP_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.token = token or os.getenv("DEMO_AUTH_TOKEN") or DEFAULT_DEMO_TOKEN
        self._transport = transport  # tests pass httpx.ASGITransport(app=...)
        self._timeout = timeout

    async def _request(self, method: str, path: str, correlation_id: str, json: dict | None = None,
                       params: dict | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}", "X-Correlation-ID": correlation_id}
        async with httpx.AsyncClient(base_url=self.base_url, transport=self._transport,
                                     timeout=self._timeout) as client:
            resp = await client.request(method, path, json=json, params=params, headers=headers)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            raise BackendError(resp.status_code, body.get("error", "HTTP_ERROR"),
                               body.get("detail", resp.text[:200]), body.get("reasons"))
        return body

    @staticmethod
    def _body(correlation_id: str, **fields: Any) -> dict[str, Any]:
        return {"schema_version": "1.0", "correlation_id": correlation_id,
                **{k: v for k, v in fields.items() if v is not None}}

    # ---- reads
    async def health(self, correlation_id: str = "corr_health") -> dict[str, Any]:
        return await self._request("GET", "/health", correlation_id)

    async def get_case_status(self, case_id: str, correlation_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/cases/{case_id}", correlation_id)

    async def list_cases(self, correlation_id: str, zone_id: str | None = None,
                         resident_status: str | None = None, unresolved: bool = False) -> list[dict[str, Any]]:
        params = {k: v for k, v in {"zone_id": zone_id, "resident_status": resident_status}.items() if v}
        if unresolved:
            params["unresolved"] = "true"
        return (await self._request("GET", "/cases", correlation_id, params=params))["cases"]

    # ---- writes (contract section 3)
    async def start_demo_warning(self, zone_id: str, scenario_id: str, correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", "/demo/warnings", correlation_id, self._body(
            correlation_id, zone_id=zone_id, scenario_id=scenario_id, alert_source="SIMULATED_OFFICIAL"))

    async def submit_resident_response(self, case_id: str, text: str, sender: str, correlation_id: str,
                                       language: str | None = None, external_id: str | None = None) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/responses", correlation_id, self._body(
            correlation_id, text=text, sender=sender, language=language, external_id=external_id))

    async def evaluate_transport(self, case_id: str, request_id: str, offers: list[dict[str, Any]],
                                 correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/transport/evaluate", correlation_id, self._body(
            correlation_id, request_id=request_id, service_type="accessible_transport", candidate_offers=offers))

    async def evaluate_destination(self, case_id: str, request_id: str, offers: list[dict[str, Any]],
                                   correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/destination/evaluate", correlation_id, self._body(
            correlation_id, request_id=request_id, service_type="accessible_destination", candidate_offers=offers))

    async def propose_assignment(self, case_id: str, transport_offer_id: str, destination_offer_id: str | None,
                                 idempotency_key: str, correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/assignments", correlation_id, self._body(
            correlation_id, transport_offer_id=transport_offer_id, destination_offer_id=destination_offer_id,
            authorization="SIMULATED_PREAPPROVED", idempotency_key=idempotency_key))

    async def accept_assignment(self, assignment_id: str, provider_id: str, decision: str,
                                provider_agent_address: str | None, idempotency_key: str,
                                correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/assignments/{assignment_id}/acceptance", correlation_id, self._body(
            correlation_id, provider_id=provider_id, decision=decision,
            provider_agent_address=provider_agent_address, idempotency_key=idempotency_key))

    async def confirm_pickup(self, assignment_id: str, evidence: dict[str, Any], idempotency_key: str,
                             correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/assignments/{assignment_id}/pickup", correlation_id, self._body(
            correlation_id, evidence=evidence, idempotency_key=idempotency_key))

    async def confirm_arrival(self, assignment_id: str, evidence: dict[str, Any], idempotency_key: str,
                              correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/assignments/{assignment_id}/arrival", correlation_id, self._body(
            correlation_id, evidence=evidence, idempotency_key=idempotency_key))

    async def request_recovery_handoff(self, case_id: str, share_recovery_needs: bool, granted_by: str,
                                       idempotency_key: str, correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/recovery-referrals", correlation_id, self._body(
            correlation_id, idempotency_key=idempotency_key,
            consent={"share_recovery_needs": share_recovery_needs, "granted_by": granted_by}))

    async def escalate_case(self, case_id: str, reason: str, idempotency_key: str,
                            correlation_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/cases/{case_id}/escalations", correlation_id, self._body(
            correlation_id, reason=reason, idempotency_key=idempotency_key))


def transport_requirements(case: dict[str, Any]) -> dict[str, Any] | None:
    """Consent-scoped needs a transport provider may see. None if the resident did not consent."""
    if not case.get("consent", {}).get("share_transport_needs"):
        return None
    needs = case.get("needs", {})
    return {k: needs.get(k) for k in
            ("wheelchair_accessible_vehicle", "transfer_assistance", "portable_oxygen_equipment", "pet_count")}


def destination_requirements(case: dict[str, Any]) -> dict[str, Any] | None:
    if not case.get("consent", {}).get("share_destination_needs"):
        return None
    needs = case.get("needs", {})
    return {k: needs.get(k) for k in ("destination_accessibility", "portable_oxygen_equipment", "pet_count")}

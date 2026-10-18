"""Fetch.ai agent-to-agent messages for contract v2.0 (§6). Owner: Developer A.

uagents `Model` = pydantic v1. Payloads that mirror B's responses are carried as plain
dicts so the agents don't break when B adds fields. Every message carries
`schema_version`, `correlation_id`, `created_at`; anything that creates state carries an
`idempotency_key`. Agents only ever receive consent-scoped fields; pickup points and
phone numbers never travel back to the Doorstep agent.
"""

from typing import Any, Literal, Optional

from uagents import Model

from doorstep.integrations.fetch_adapter import utc_now  # noqa: F401  (re-export for agents)

SCHEMA_V2 = "2.0"


class _Msg(Model):
    schema_version: str = SCHEMA_V2
    correlation_id: str
    created_at: str


# --- Calamity Checker -> Doorstep
class PollNow(_Msg):
    """Demo control: ask the Calamity Checker to poll the feed immediately."""
    reason: str = "DEMO_CONTROL"


class AlertNotification(_Msg):
    ingest_id: str
    feed_freshness: str
    new_alerts: list[dict[str, Any]]
    changed_alerts: list[dict[str, Any]]
    canceled_alerts: list[dict[str, Any]]
    affected_cases: list[dict[str, Any]]
    outreach_orgs: list[dict[str, Any]]


# --- Doorstep <-> Organization agent (volunteer outreach)
class OutreachRequest(_Msg):
    alert_id: str
    calamity_type: str
    zone_id: Optional[str] = None
    idempotency_key: str


class OutreachResult(_Msg):
    org_id: str
    alert_id: str
    asked: list[str]
    skipped: list[dict[str, Any]]
    available: list[str]
    unavailable: list[str]
    awaiting_reply: list[str]
    note: str = "Volunteer answers are simulated (DEMO)."


# --- Doorstep <-> Matching agent
class MatchRequest(_Msg):
    case_id: str
    create_proposal: bool
    select_volunteer_id: Optional[str] = None
    select_site_id: Optional[str] = None
    idempotency_key: str


class MatchResult(_Msg):
    case_id: str
    ok: bool
    status_code: int
    result: dict[str, Any]  # B's /matches/propose response, or {} on error
    error: Optional[dict[str, Any]] = None


# --- Doorstep <-> Organization agent (acceptance, journey reports)
Role = Literal["VOLUNTEER", "SHELTER"]


class AcceptRequest(_Msg):
    case_id: str
    assignment_id: str
    org_id: str
    role: Role
    volunteer_id: Optional[str] = None
    site_id: Optional[str] = None
    shared_with_volunteer: dict[str, Any] = {}
    idempotency_key: str


class AcceptResponse(_Msg):
    case_id: str
    assignment_id: str
    org_id: str
    role: Role
    volunteer_id: Optional[str] = None
    site_id: Optional[str] = None
    decision: Literal["ACCEPTED", "DECLINED", "ERROR"]
    backend: dict[str, Any] = {}  # B's accept response minus pickup_details
    error: Optional[dict[str, Any]] = None


class ReportRequest(_Msg):
    """Demo hook: ask the org agent for its (simulated) pickup or arrival report."""
    kind: Literal["PICKUP", "ARRIVAL"]
    case_id: str
    assignment_id: str


class PickupReport(_Msg):
    case_id: str
    assignment_id: str
    org_id: str
    volunteer_id: str
    report_id: str
    code_verified: bool
    source: str = "SIMULATED"


class ArrivalReport(_Msg):
    case_id: str
    assignment_id: str
    shelter_org_id: str
    site_id: str
    report_id: str
    source: str = "SIMULATED"


class ReportUnavailable(_Msg):
    """The org agent cannot report this step (e.g. it never accepted the assignment)."""
    case_id: str
    assignment_id: str
    reason: str


# --- Doorstep <-> Escalation Simulator
class EscalationRequest(_Msg):
    escalation_id: str
    case_id: str
    case_summary_for_recipient: dict[str, Any]
    idempotency_key: str


class EscalationAck(_Msg):
    escalation_id: str
    case_id: str
    status: str
    assistance_confirmed: bool = False
    backend: dict[str, Any] = {}


# --- Doorstep <-> Post-Calamity agent <-> recovery org agents
class RecoveryRequest(_Msg):
    case_id: str
    help_types: list[str]
    share_recovery_needs: bool
    granted_by: str
    idempotency_key: str


class RecoveryResponse(_Msg):
    case_id: str
    ok: bool
    referrals: list[dict[str, Any]]
    unmatched_help_types: list[str] = []
    housing_secured: bool = False
    error: Optional[dict[str, Any]] = None


class ReferralRequest(_Msg):
    referral_id: str
    case_id: str
    help_type: str
    org_id: str
    shared_payload: dict[str, Any]
    idempotency_key: str


class ReferralResponse(_Msg):
    referral_id: str
    org_id: str
    decision: Literal["ACCEPTED", "DECLINED", "ERROR"]
    status: str
    backend: dict[str, Any] = {}

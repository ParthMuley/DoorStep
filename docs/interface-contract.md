# Doorstep Interface Contract — v1.0

Shared between Developer A (Fetch.ai agents + orchestration) and Developer B (domain engine + API).
Source: Section 2 of `Doorstep_Two_Developer_Execution_Plan.md` and Section 6 of `Doorstep_Implementation_Master_Spec.md`. If this file and the master spec disagree on safety, the master spec wins.

**Change rule:** a schema change bumps `schema_version` (`1.0` → `1.1`), is proposed in a small PR touching only this file, and needs the other developer's approval before merge.

**Everything here is synthetic. All resident-facing text starts with `DOORSTEP DEMO`.**

---

## 1. Conventions

- IDs: opaque synthetic strings (`case_maria_001`, `req_001`, `offer_t_001`, `assign_001`, `esc_002`, `evt_…`).
- Timestamps: UTC ISO-8601 with `Z` (`2026-10-17T18:04:00Z`).
- Every request/response/event body carries `schema_version: "1.0"`. Where relevant also `case_id`, `event_id`, `correlation_id`, `created_at`.
- Any action that can create a reservation/assignment carries `idempotency_key`. Repeating the same key returns the original result (HTTP 200), never a second assignment.
- `correlation_id` is created by the Coordinator per ASI:One conversation turn and passed to every API call (header `X-Correlation-ID`) and agent message. B echoes it in responses and event-log rows.
- Validation: Pydantic v2 on both sides. Unknown fields rejected on write endpoints.

## 2. States (exact string values)

| Dimension | Values |
|---|---|
| `resident_status` | `NEEDS_ASSISTANCE`, `PROVIDER_ACCEPTED`, `PICKUP_CONFIRMED`, `ARRIVAL_CONFIRMED`, `REQUIRES_COORDINATOR`, `UNKNOWN` |
| `communication_status` | `NOT_SENT`, `SENT`, `DELIVERED`, `DELIVERY_FAILED`, `REPLIED`, `NO_REPLY_AFTER_DEADLINE`, `UNKNOWN` |
| `service_status` | `DRAFT`, `PROPOSED`, `AWAITING_PROVIDER`, `ACCEPTED`, `DECLINED`, `CANCELED`, `COMPLETED`, `UNRESOLVED` |
| `zone_rule` | `OUTSIDE_ACTIVE_ORDER`, `INSIDE_ACTIVE_ORDER`, `UNVERIFIED` |
| `escalation.status` | `REQUESTED`, `ACKNOWLEDGED_REQUEST_ONLY`, `NO_ACKNOWLEDGMENT` |
| `referral.status` | `REQUESTED`, `ACCEPTED`, `UNRESOLVED` |

Never: infer arrival from acceptance, infer danger from silence, infer dispatch from an escalation acknowledgment.

## 3. HTTP API (B implements, A calls)

Base URL from `DOORSTEP_API_URL`. Write endpoints require header `Authorization: Bearer <DEMO_AUTH_TOKEN>`. All requests send `X-Correlation-ID`.

Errors: `{"schema_version":"1.0","error":"<CODE>","detail":"...","correlation_id":"..."}` with codes such as `CONSENT_MISSING`, `UNSAFE_ZONE`, `PROVIDER_NOT_APPROVED`, `INVALID_TRANSITION`, `NOT_FOUND`, `UNAUTHORIZED`. A safety rejection is HTTP 409 (business rule), not 500.

| Operation | Method + path |
|---|---|
| health | `GET /health` |
| reset demo | `POST /demo/reset` |
| `start_demo_warning` | `POST /demo/warnings` |
| `submit_resident_response` | `POST /cases/{case_id}/responses` |
| `find_transport` | `POST /cases/{case_id}/transport/evaluate` |
| `find_destination` | `POST /cases/{case_id}/destination/evaluate` |
| `propose_assignment` | `POST /cases/{case_id}/assignments` |
| `accept_assignment` | `POST /assignments/{assignment_id}/acceptance` |
| `confirm_pickup` | `POST /assignments/{assignment_id}/pickup` |
| `confirm_arrival` | `POST /assignments/{assignment_id}/arrival` |
| `request_recovery_handoff` | `POST /cases/{case_id}/recovery-referrals` |
| `escalate_case` | `POST /cases/{case_id}/escalations` |
| `get_case_status` | `GET /cases/{case_id}` |
| list cases (for "show residents who requested assistance") | `GET /cases?zone_id=zone_3&resident_status=NEEDS_ASSISTANCE` |

> **Design note — who finds offers?** Provider agents (A) own their own synthetic inventories and return *raw* offers over Fetch.ai messaging. The Coordinator then posts those raw offers to B's `…/evaluate` endpoint, where B's deterministic matching decides eligibility and explains rejections. Providers never read B's database; B never talks to providers directly.

### 3.1 `GET /health`
```json
{"schema_version":"1.0","status":"ok","simulation_mode":true}
```

### 3.2 `POST /demo/warnings` — `start_demo_warning`
Request:
```json
{"schema_version":"1.0","zone_id":"zone_3","scenario_id":"la_hacks_demo_v1","alert_source":"SIMULATED_OFFICIAL","correlation_id":"corr_7f3a"}
```
Response 201:
```json
{
  "schema_version":"1.0",
  "alert_id":"alert_001",
  "zone_id":"zone_3",
  "verified":true,
  "simulated":true,
  "case_ids":["case_maria_001","case_david_002"],
  "checkins":[
    {"case_id":"case_maria_001","channel":"SIMULATED_SMS","language":"es","communication_status":"SENT"},
    {"case_id":"case_david_002","channel":"SIMULATED_SMS","language":"en","communication_status":"SENT"}
  ],
  "correlation_id":"corr_7f3a",
  "created_at":"2026-10-17T18:00:00Z"
}
```
An alert with `alert_source` other than `SIMULATED_OFFICIAL` creates a report requiring verification (`verified:false`, no check-ins).

### 3.3 `POST /cases/{case_id}/responses` — `submit_resident_response`
Request:
```json
{"schema_version":"1.0","text":"1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.","language":"es","sender":"sim_phone_maria","correlation_id":"corr_7f3a"}
```
Response 200:
```json
{
  "schema_version":"1.0",
  "case_id":"case_maria_001",
  "response_id":"resp_001",
  "original_text":"1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.",
  "intent":"NEED_HELP",
  "candidate_needs":{"wheelchair_accessible_vehicle":true,"transfer_assistance":null,"pet_count":1},
  "needs_confirmed":false,
  "confirmation_question":"DOORSTEP DEMO: ¿Confirma que necesita un vehículo accesible para silla de ruedas, ayuda para subir y espacio para 1 perro? Responda SI o NO.",
  "communication_status":"REPLIED",
  "resident_status":"NEEDS_ASSISTANCE",
  "correlation_id":"corr_7f3a"
}
```
Confirming: send `{"text":"SI","language":"es",...}` → response has `"needs_confirmed":true` and the confirmed `needs` object (Section 5). Unknown `sender` → 403, case unchanged.

### 3.4 `POST /cases/{case_id}/transport/evaluate` — `find_transport`
Request (raw offers collected by the Coordinator from Transport agents):
```json
{
  "schema_version":"1.0",
  "request_id":"req_001",
  "service_type":"accessible_transport",
  "correlation_id":"corr_7f3a",
  "candidate_offers":[
    {"offer_id":"offer_t_001","provider_id":"transport_org_a","provider_agent_address":"agent1q...","vehicle_id":"van_a1","wheelchair_accessible":true,"transfer_assistance":true,"oxygen_handling":false,"pets_allowed":true,"seats_available":2,"wheelchair_spaces_available":1,"service_area_zones":["zone_2","zone_3","zone_4"],"eta_minutes":18,"valid_until":"2026-10-17T18:30:00Z"},
    {"offer_id":"offer_t_002","provider_id":"transport_org_b","provider_agent_address":"agent1q...","vehicle_id":"sedan_b1","wheelchair_accessible":false,"transfer_assistance":false,"oxygen_handling":false,"pets_allowed":true,"seats_available":3,"wheelchair_spaces_available":0,"service_area_zones":["zone_3"],"eta_minutes":6,"valid_until":"2026-10-17T18:30:00Z"}
  ]
}
```
Response 200:
```json
{
  "schema_version":"1.0",
  "case_id":"case_maria_001",
  "request_id":"req_001",
  "zone_rule":"OUTSIDE_ACTIVE_ORDER",
  "eligible":[{"offer_id":"offer_t_001","provider_id":"transport_org_a","rank":1,"match_reasons":["wheelchair_accessible","transfer_assistance","pets_allowed","in_service_area","provider_approved"]}],
  "rejected":[{"offer_id":"offer_t_002","provider_id":"transport_org_b","reasons":["NOT_WHEELCHAIR_ACCESSIBLE","NO_TRANSFER_ASSISTANCE"]}],
  "escalation_required":false,
  "correlation_id":"corr_7f3a"
}
```
For a case inside an active-order zone: `"zone_rule":"INSIDE_ACTIVE_ORDER"`, `"eligible":[]`, every offer rejected with `"ACTIVE_ORDER_ZONE"`, `"escalation_required":true`.

### 3.5 `POST /cases/{case_id}/destination/evaluate` — `find_destination`
Same shape as 3.4 with `"service_type":"accessible_destination"` and offers like:
```json
{"offer_id":"offer_d_001","provider_id":"destination_org_a","provider_agent_address":"agent1q...","destination_id":"dest_civic_center_sim","step_free_entry":true,"accessible_restroom":true,"pets_allowed":true,"service_animals_allowed":true,"beds_available":12,"oxygen_power_outlets":true,"valid_until":"2026-10-17T18:30:00Z"}
```

### 3.6 `POST /cases/{case_id}/assignments` — `propose_assignment`
Request:
```json
{"schema_version":"1.0","transport_offer_id":"offer_t_001","destination_offer_id":"offer_d_001","authorization":"SIMULATED_PREAPPROVED","idempotency_key":"case_maria_001:transport:v1","correlation_id":"corr_7f3a"}
```
Response 201 (or 200 for a repeated idempotency key):
```json
{
  "schema_version":"1.0",
  "assignment_id":"assign_001",
  "case_id":"case_maria_001",
  "provider_id":"transport_org_a",
  "destination_provider_id":"destination_org_a",
  "provider_approved":true,
  "service_area_allowed":true,
  "zone_rule":"OUTSIDE_ACTIVE_ORDER",
  "provider_response":null,
  "authorization":"SIMULATED_PREAPPROVED",
  "service_status":"AWAITING_PROVIDER",
  "resident_status":"NEEDS_ASSISTANCE",
  "shared_with_provider":{"wheelchair_accessible_vehicle":true,"transfer_assistance":true,"pet_count":1,"pickup_area":"zone_3_sector_b_synthetic"},
  "confirmed_pickup_at":null,
  "confirmed_arrival_at":null,
  "correlation_id":"corr_7f3a"
}
```
Rejections: 409 `UNSAFE_ZONE`, `CONSENT_MISSING`, `PROVIDER_NOT_APPROVED`, `OFFER_NOT_ELIGIBLE`.
Note: the exact synthetic pickup point is shared **only after** provider acceptance (returned by 3.7).

### 3.7 `POST /assignments/{assignment_id}/acceptance` — `accept_assignment`
Request (Coordinator forwards the provider agent's reply):
```json
{"schema_version":"1.0","provider_id":"transport_org_a","provider_agent_address":"agent1q...","decision":"ACCEPTED","idempotency_key":"assign_001:acceptance:transport_org_a","correlation_id":"corr_7f3a"}
```
Response 200:
```json
{"schema_version":"1.0","assignment_id":"assign_001","case_id":"case_maria_001","provider_response":"ACCEPTED","service_status":"ACCEPTED","resident_status":"PROVIDER_ACCEPTED","pickup_details":{"pickup_point":"SYNTHETIC: Zone 3 Sector B meeting point 4"},"confirmed_pickup_at":null,"confirmed_arrival_at":null,"correlation_id":"corr_7f3a"}
```
`"decision":"DECLINED"` → `service_status: "DECLINED"`, resident stays `NEEDS_ASSISTANCE`. Acceptance for a `CANCELED`/expired assignment → 409 `INVALID_TRANSITION` (delayed replies never revive it). Provider id mismatch → 403.

### 3.8 `POST /assignments/{assignment_id}/pickup` — `confirm_pickup`
Request:
```json
{"schema_version":"1.0","evidence":{"type":"PROVIDER_AND_RESIDENT_CONFIRMATION","provider_confirmed":true,"resident_confirmed":true,"code_verified":true,"source":"SIMULATED"},"idempotency_key":"assign_001:pickup","correlation_id":"corr_7f3a"}
```
Response 200: `"resident_status":"PICKUP_CONFIRMED"`, `"confirmed_pickup_at":"…"`, `"confirmed_arrival_at":null`. Pickup before acceptance → 409.

### 3.9 `POST /assignments/{assignment_id}/arrival` — `confirm_arrival`
Request:
```json
{"schema_version":"1.0","evidence":{"type":"DESTINATION_CHECKIN","destination_provider_id":"destination_org_a","provider_confirmed":true,"source":"SIMULATED"},"idempotency_key":"assign_001:arrival","correlation_id":"corr_7f3a"}
```
Response 200: `"resident_status":"ARRIVAL_CONFIRMED"`, `"service_status":"COMPLETED"`. Arrival before pickup → 409.

### 3.10 `POST /cases/{case_id}/recovery-referrals` — `request_recovery_handoff`
Request:
```json
{"schema_version":"1.0","consent":{"share_recovery_needs":true,"granted_by":"RESIDENT","granted_at":"2026-10-17T18:40:00Z"},"idempotency_key":"case_maria_001:recovery:v1","correlation_id":"corr_7f3a"}
```
Response 201:
```json
{"schema_version":"1.0","referral_id":"ref_001","case_id":"case_maria_001","status":"REQUESTED","shared_fields":["wheelchair_accessible_vehicle","pet_count","destination_accessibility","preferred_language"],"housing_secured":false,"correlation_id":"corr_7f3a"}
```
Without consent → 409 `CONSENT_MISSING`, nothing shared.

### 3.11 `POST /cases/{case_id}/escalations` — `escalate_case`
Request:
```json
{"schema_version":"1.0","reason":"ACTIVE_EVACUATION_ORDER_ZONE","idempotency_key":"case_david_002:escalation:v1","correlation_id":"corr_9b21"}
```
Response 201:
```json
{"schema_version":"1.0","escalation_id":"esc_002","case_id":"case_david_002","reason":"ACTIVE_EVACUATION_ORDER_ZONE","recipient":"SIMULATED_AUTHORIZED_RESPONSE_SERVICE","status":"ACKNOWLEDGED_REQUEST_ONLY","assistance_confirmed":false,"resident_status":"REQUIRES_COORDINATOR","service_status":"UNRESOLVED","next_step":"Coordinator follows up with simulated authorized response service; assistance not confirmed.","correlation_id":"corr_9b21"}
```
Other reasons: `NO_ELIGIBLE_PROVIDER`, `PROVIDER_TIMEOUT`, `NO_REPLY_AFTER_DEADLINE`.

### 3.12 `GET /cases/{case_id}` — `get_case_status`
```json
{
  "schema_version":"1.0",
  "case_id":"case_maria_001",
  "resident_id":"resident_001",
  "display_name":"Maria (synthetic)",
  "zone_id":"zone_3",
  "zone_rule":"OUTSIDE_ACTIVE_ORDER",
  "preferred_language":"es",
  "resident_status":"PICKUP_CONFIRMED",
  "communication_status":"REPLIED",
  "needs_confirmed":true,
  "consent":{"contact_for_checkins":true,"share_transport_needs":true,"share_destination_needs":true,"share_recovery_needs":false},
  "active_assignment":{"assignment_id":"assign_001","provider_id":"transport_org_a","service_status":"ACCEPTED","confirmed_pickup_at":"2026-10-17T18:21:00Z","confirmed_arrival_at":null},
  "escalations":[],
  "referrals":[],
  "timeline":[
    {"event_id":"evt_001","type":"ALERT_VERIFIED","created_at":"2026-10-17T18:00:00Z","evidence":"SIMULATED_OFFICIAL"},
    {"event_id":"evt_002","type":"CHECKIN_SENT","created_at":"2026-10-17T18:00:02Z"},
    {"event_id":"evt_003","type":"RESIDENT_REPLIED","created_at":"2026-10-17T18:02:10Z"},
    {"event_id":"evt_004","type":"NEEDS_CONFIRMED","created_at":"2026-10-17T18:03:00Z"},
    {"event_id":"evt_005","type":"ASSIGNMENT_PROPOSED","created_at":"2026-10-17T18:05:00Z"},
    {"event_id":"evt_006","type":"PROVIDER_ACCEPTED","created_at":"2026-10-17T18:06:00Z"},
    {"event_id":"evt_007","type":"PICKUP_CONFIRMED","created_at":"2026-10-17T18:21:00Z"}
  ],
  "correlation_id":"corr_7f3a"
}
```
Timeline events contain no free-text resident details (redacted for logs/Sentry).

## 4. Fetch.ai agent messages (A owns; B does not need to implement)

uAgents `Model` classes live in `src/doorstep/integrations/fetch_adapter.py`. Providers only ever receive consent-scoped needs.

`OfferRequest` (Coordinator → Transport/Destination agent):
```json
{"schema_version":"1.0","case_id":"case_maria_001","request_id":"req_001","correlation_id":"corr_7f3a","service_type":"accessible_transport","zone_id":"zone_3","requirements":{"wheelchair_accessible_vehicle":true,"transfer_assistance":true,"pet_count":1},"created_at":"2026-10-17T18:04:00Z"}
```
`OfferResponse` (provider → Coordinator): `{"schema_version","case_id","request_id","correlation_id","provider_id","offers":[<offer objects from 3.4/3.5>],"created_at"}`.

`AcceptRequest` (Coordinator → provider): `{"schema_version","case_id","assignment_id","offer_id","correlation_id","idempotency_key","shared_needs":{...}}`.
`AcceptResponse` (provider → Coordinator): `{"schema_version","case_id","assignment_id","offer_id","provider_id","correlation_id","idempotency_key","decision":"ACCEPTED"|"DECLINED","created_at"}`.

## 5. Synthetic fixtures both sides agree on

| Case | Resident | Zone | Needs | Expected outcome |
|---|---|---|---|---|
| `case_maria_001` | `resident_001` "Maria (synthetic)", `es` | `zone_3` sector B, `OUTSIDE_ACTIVE_ORDER` | wheelchair vehicle, transfer assistance, 1 dog, step-free destination | `transport_org_a` / `van_a1` + `destination_org_a` → accepted → pickup → arrival → recovery referral `REQUESTED`/`ACCEPTED` |
| `case_david_002` | `resident_002` "David (synthetic)", `en` | `zone_3` sector A, `INSIDE_ACTIVE_ORDER` | wheelchair vehicle | no volunteer assignment, escalation `ACKNOWLEDGED_REQUEST_ONLY`, case `UNRESOLVED` |

Provider ids: `transport_org_a` (wheelchair van, approved), `transport_org_b` (sedan, closer, not accessible — the "closer but unsuitable" demo rejection), `destination_org_a` (step-free, pets OK), `destination_org_b` (no step-free entry).

Confirmed `needs` object (master spec §6):
```json
{"wheelchair_accessible_vehicle":true,"transfer_assistance":true,"portable_oxygen_equipment":false,"pet_count":1,"preferred_language":"es","destination_accessibility":["step_free_entry"]}
```

# Doorstep Interface Contract — v2.0

Shared between Developer A (Fetch.ai agents, ASI:One, cards, LangGraph) and Developer B (backend, data, geography, matching).
**Owner: Developer B** (per `docs/DOORSTEP_V2_TEAM_PLAN.md` §6). Source: that plan §7, `Doorstep_V2_Two_Person_Claude_Code_Plan.md` §4, `Doorstep_Implementation_Master_Spec.md` §4/§6. If anything here conflicts with a safety rule in those documents, the safety rule wins.

**Status:** v2.0 **frozen once A signs off** (checkpoint C1). Until then, comments go in the PR.
**Change rule:** any change after the freeze bumps `schema_version` (`2.0` → `2.1`), goes in a small PR touching only this file, and needs both developers to approve.

**Everything is synthetic.** All resident-facing text starts with `DOORSTEP DEMO`. Every card shows SIMULATION. Real-world data (the live Cal OES feed, real news) is **display-only** and can never trigger check-ins, block roads or change a case.

---

## 1. Conventions

- **Versions:** every request and response body carries `"schema_version": "2.0"`. Agent messages (A) carry it too.
- **IDs:** opaque synthetic strings. Fixed demo IDs are in §9. B generates deterministic sequential IDs (`assign_001`, `esc_001`, `ref_001`, `evt_001`, `alert_001`, `closure_001`, `route_001`), so a reset followed by the same calls gives the same IDs.
- **Time:** UTC ISO-8601 with `Z` (`2026-10-17T20:01:00Z`). The raw Cal OES payload keeps its epoch-millisecond fields; B converts them.
- **Geometry:** GeoJSON, coordinates **`[longitude, latitude]`**, WGS84 (EPSG:4326). All demo coordinates are fictional.
- **Correlation:** the Coordinator creates a `correlation_id` per ASI:One turn and sends it as header `X-Correlation-ID` on every call (a body `correlation_id` is the fallback). B echoes it in the response body, the response header, every timeline event and every error.
- **Idempotency:** any call that creates something (`matches/propose`, `accept`, `pickup`, `arrival`, `escalate`, `ack`, `recovery`, `respond`, `alerts/ingest`, `closures/ingest`) takes an `idempotency_key`. Repeating a key returns the original result with HTTP 200 and `"duplicate": true`. Never a second record.
- **Auth:** writes (POST) need `Authorization: Bearer <DEMO_AUTH_TOKEN>`. Reads (GET) are open and return synthetic, sanitized data only (no pickup points). This is demo gating, not production auth.
- **Validation:** Pydantic v2. Unknown top-level fields on write bodies → 422. **Exception:** provider offers and feed payloads ignore unknown fields (provider claims are never trusted anyway).
- **Status words are authoritative.** A shows B's status strings verbatim. LLM text (ASI:One API) may explain them but never replace them.

## 2. Enums (exact strings)

| Name | Values |
|---|---|
| `resident_status` | `UNKNOWN`, `NEEDS_ASSISTANCE`, `PROVIDER_ACCEPTED`, `PICKUP_CONFIRMED`, `ARRIVAL_CONFIRMED`, `REQUIRES_COORDINATOR` |
| `communication_status` | `NOT_SENT`, `SENT`, `DELIVERED`, `DELIVERY_FAILED`, `REPLIED`, `NO_REPLY_AFTER_DEADLINE`, `UNKNOWN` |
| `assignment_status` | `PROPOSED`, `AWAITING_PROVIDER`, `ACCEPTED`, `DECLINED`, `CANCELED`, `COMPLETED`, `UNRESOLVED` |
| `zone_status` | `ORDER`, `WARNING`, `SHELTER_IN_PLACE`, `OUTSIDE_KNOWN_ZONES`, `UNKNOWN`, `STALE` |
| `alert.status` | `ORDER`, `WARNING`, `SHELTER_IN_PLACE`, `INACTIVE`, `UNKNOWN` |
| `alert.verification` | `OFFICIAL_SIMULATION`, `OFFICIAL_LIVE_DISPLAY_ONLY` |
| `freshness` | `FRESH`, `STALE`, `NO_DATA` |
| `escalation.status` | `REQUESTED`, `ACKNOWLEDGED_REQUEST_ONLY`, `NO_ACKNOWLEDGMENT` |
| `recovery.status` | `NOT_REQUESTED`, `REQUESTED`, `ACCEPTED`, `COMPLETED`, `UNRESOLVED` |
| `closure.state` | `OFFICIAL_CONFIRMED`, `UNVERIFIED_REPORT`, `CONFLICTING`, `EXPIRED` |
| `closure.source_type` | `OFFICIAL_SIMULATION`, `NEWS`, `REAL_WORLD_CONTEXT` |
| `route.status` | `ILLUSTRATIVE_ONLY`, `REFUSED`, `NO_ROUTE_CONFIRMED` |
| `consent purpose` | `CHECKIN`, `TRANSPORT`, `DESTINATION`, `RECOVERY` |
| `map color` | `red` NEEDS_ASSISTANCE, `yellow` PROVIDER_ACCEPTED, `blue` PICKUP_CONFIRMED, `green` ARRIVAL_CONFIRMED, `black` REQUIRES_COORDINATOR, `gray` UNKNOWN; always paired with a text `label` |

**Never:** acceptance ⇒ pickup, pickup ⇒ arrival, silence ⇒ danger or safety, failed delivery ⇒ no reply, escalation acknowledgment ⇒ dispatch, referral accepted ⇒ housing secured, no closure report ⇒ road open, missing/stale data ⇒ safe.

**Zone dominance** (a resident covered by several alerts): `ORDER` > `SHELTER_IN_PLACE` > `WARNING` > `OUTSIDE_KNOWN_ZONES`. If any relevant source is stale → `STALE`. No data or an uncertain geocode → `UNKNOWN`. A polygon covers points **on its edge**.

## 3. Errors

```json
{"schema_version":"2.0","error":"UNSAFE_ZONE","detail":"Ordinary volunteer assignment is blocked in an active order zone","correlation_id":"corr_7f3a","reasons":["ORDER_ZONE"]}
```

| HTTP | `error` | When |
|---|---|---|
| 401 | `UNAUTHORIZED` | missing/invalid Bearer token |
| 403 | `UNAUTHORIZED` | wrong provider identity, unknown SMS sender, consent not from resident/caregiver |
| 404 | `NOT_FOUND` | unknown case/assignment/offer/alert |
| 409 | `CONSENT_MISSING` | sharing without the purpose consent (nothing shared) |
| 409 | `UNSAFE_ZONE` | selected offer in/through an ORDER zone |
| 409 | `ZONE_STALE` / `ZONE_UNKNOWN` | zone data stale or unknown; assignment refused |
| 409 | `PROVIDER_NOT_APPROVED` | org or volunteer not approved in B's registry |
| 409 | `OFFER_NOT_ELIGIBLE` | selected offer fails a hard constraint (see `reasons`) |
| 409 | `NOT_AUTHORIZED` | `authorization` is not `SIMULATED_PREAPPROVED` |
| 409 | `NEEDS_NOT_CONFIRMED` | matching before the resident confirmed needs |
| 409 | `INVALID_TRANSITION` | late reply to a canceled/declined assignment, pickup before acceptance, arrival before pickup, etc. |
| 409 | `INSUFFICIENT_EVIDENCE` | pickup/arrival evidence incomplete or from the wrong party |
| 409 | `DUPLICATE_ACCEPTANCE` | a second provider tries to accept after one already did |
| 409 | `REASON_MISMATCH` | escalation reason not true for this case |
| 409 | `ROUTE_REFUSED` | route constraints refused (see `reasons`) |
| 422 | `VALIDATION_ERROR` | body failed validation (`reasons` = field paths) |
| 422 | `FEED_INVALID` | ingest payload is not a valid feed |

## 4. Reason codes

**Positive (eligible):** `PROVIDER_APPROVED`, `VOLUNTEER_APPROVED`, `IN_SERVICE_AREA`, `WHEELCHAIR_OK`, `TRANSFER_OK`, `OXYGEN_OK`, `PET_OK`, `SERVICE_ANIMAL_OK`, `STEP_FREE_OK`, `RESTROOM_OK`, `OXYGEN_POWER_OK`, `CAPACITY_OK`, `AVAILABILITY_CONFIRMED`, `OUTSIDE_ORDER_ZONE`, `ROUTE_AVOIDS_CLOSURES`.

**Rejection:** `PROVIDER_NOT_APPROVED`, `VOLUNTEER_NOT_APPROVED`, `CAPABILITY_NOT_REGISTERED` (offer claims more than B's registry), `AVAILABILITY_UNCONFIRMED` (missing or past `valid_until`), `OUTSIDE_SERVICE_AREA`, `NOT_WHEELCHAIR_ACCESSIBLE`, `NO_WHEELCHAIR_SPACE_AVAILABLE`, `NO_TRANSFER_ASSISTANCE`, `NO_OXYGEN_HANDLING`, `PETS_NOT_ALLOWED`, `SERVICE_ANIMAL_NOT_ACCOMMODATED`, `SERVICE_ANIMAL_UNCONFIRMED`, `NO_SEATS_AVAILABLE`, `NOT_STEP_FREE`, `NO_ACCESSIBLE_RESTROOM`, `NO_OXYGEN_POWER`, `NO_BEDS_AVAILABLE`, `ORDER_ZONE`, `DESTINATION_IN_ORDER_ZONE`, `ZONE_STALE`, `ZONE_UNKNOWN`, `NO_ROUTE_AVOIDING_CLOSURES`, `PROVIDER_ALREADY_DECLINED`.

## 5. HTTP API (B implements, A calls)

Base URL: `DOORSTEP_API_URL` (default `http://127.0.0.1:8000`). Responses below omit `schema_version` and `correlation_id`; **both are always present**.

### 5.1 Health and demo

**`GET /health`**
```json
{"status":"ok","version":"2.0.0","simulation_mode":true,
 "alerts":{"last_ingest_at":"2026-10-17T20:02:00Z","feed_freshness":"FRESH"},
 "closures":{"last_ingest_at":"2026-10-17T20:02:30Z"}}
```

**`POST /demo/reset`** (token): reseeds §9. → `{"status":"reset","residents":2,"organizations":9,"simulated":true}`

### 5.2 Enrollment

**`POST /residents`** → 201
```json
{"resident":{"display_name":"Rosa (synthetic)","preferred_language":"es","contact_channel":"sim_phone_rosa",
  "address_label":"SYNTHETIC: 12 Example Way","location":{"lat":34.1052,"lon":-118.0951,"geocode_confidence":"HIGH"},
  "needs":{"wheelchair_accessible_vehicle":true,"transfer_assistance":false,"portable_oxygen_equipment":false,
           "pet_count":0,"service_animal":false,"preferred_language":"es","destination_accessibility":["step_free_entry"]},
  "trusted_contact":{"display_name":"Luis (synthetic)","contact_channel":"sim_phone_luis","relationship":"son"}},
 "consents":[{"purpose":"CHECKIN","granted":true},{"purpose":"TRANSPORT","granted":true},
             {"purpose":"DESTINATION","granted":true},{"purpose":"RECOVERY","granted":false}]}
```
Response: `{"resident_id":"resident_003","consents":{"CHECKIN":true,"TRANSPORT":true,"DESTINATION":true,"RECOVERY":false},"zone_status":"OUTSIDE_KNOWN_ZONES","created_at":"…"}`.
`geocode_confidence` `LOW`/`FAILED` → `zone_status: UNKNOWN` (never an automated zone conclusion).

**`POST /organizations`** → 201
```json
{"organization":{"organization_id":"transport_org_f","display_name":"Foothill Access Vans (fictional)",
  "org_type":"TRANSPORT","approval_status":"APPROVED","service_area_zones":["zone_2","zone_3"],
  "base_location":{"lat":34.0920,"lon":-118.1150},"contact_alias":"sim_org_f",
  "vehicles":[{"vehicle_id":"van_f1","seats":2,"wheelchair_spaces":1,"transfer_assistance":true,
               "oxygen_handling_authorized":false,"pets_allowed":true,"service_animals_allowed":true}],
  "destination_sites":[]}}
```
`org_type`: `TRANSPORT | DESTINATION | RECOVERY | COMMUNITY`. `approval_status`: `APPROVED | PENDING | REVOKED`. Destination orgs list `destination_sites` (`destination_id, location, beds_total, step_free_entry, accessible_restroom, pets_allowed, service_animals_allowed, oxygen_power_outlets`).
Response: `{"organization_id":"transport_org_f","approval_status":"APPROVED","vehicles":["van_f1"],"destination_sites":[]}`.

**`POST /volunteers`** → 201
```json
{"volunteer":{"volunteer_id":"volunteer_sarah","organization_id":"transport_org_a","display_name":"Sarah (synthetic)",
  "approval_status":"APPROVED","available_opt_in":true,"vehicle_ids":["van_a1"]}}
```
Response: `{"volunteer_id":"volunteer_sarah","organization_id":"transport_org_a","approval_status":"APPROVED"}`.

**`GET /organizations`**: registry read for cards: orgs with approval, vehicles, sites, volunteers (no contact details).

### 5.3 Alerts (Calamity Checker agent ↔ B)

**`GET /demo/feeds/caloes`**: the synthetic feed in the **exact Cal OES GeoJSON shape** (what the Calamity agent fetches in the demo).
```json
{"type":"FeatureCollection","features":[{"type":"Feature","id":1,
  "geometry":{"type":"Polygon","coordinates":[[[-118.100,34.100],[-118.090,34.100],[-118.090,34.110],[-118.100,34.110],[-118.100,34.100]]]},
  "properties":{"OBJECTID":1,"COUNTY":"Los Angeles (SIMULATED)","CITY":"Demo City","ZONE_NAME":"DEMO Zone 3 Sector A",
    "ZONE_ID":"zone_3_sector_a","STATUS":"Evacuation Order","EVENT_TYPE":"Wildfire (SIMULATED)",
    "CRITICAL_INFO":"SIMULATION ONLY","PUBLIC_INFO":"SIMULATION ONLY","EDIT_DATE":1792281600000,
    "STATEWIDE_LAST_UPDATED":1792281660000,"GlobalID":"sim-0001"}}]}
```

**`POST /alerts/ingest`** (token). The Calamity agent posts what it fetched, **including failed fetches**:
```json
{"source":{"source_id":"SYNTHETIC_CALOES","source_type":"OFFICIAL_SIMULATION",
           "url":"http://127.0.0.1:8000/demo/feeds/caloes","fetched_at":"2026-10-17T20:02:00Z"},
 "fetch_ok":true,"http_status":200,"error":null,
 "payload":{"type":"FeatureCollection","features":[…]},
 "idempotency_key":"SYNTHETIC_CALOES:2026-10-17T20:02:00Z"}
```
`source_type`: `OFFICIAL_SIMULATION` (synthetic; may trigger check-ins) or `REAL_WORLD` (live Cal OES; display-only). `fetch_ok:false` with no payload marks the feed's freshness down; it never cancels alerts.

Response 200:
```json
{"ingest_id":"ingest_004","source_id":"SYNTHETIC_CALOES","source_updated_at":"2026-10-17T20:01:00Z","feed_freshness":"FRESH",
 "records_received":2,"records_rejected":[{"source_record_id":"sim-0009","reason":"UNKNOWN_STATUS:Evacuation Advisory"}],
 "new_alerts":["alert_001","alert_002"],"changed_alerts":[],"canceled_alerts":[],"pending_cancellation":[],
 "affected_cases":[{"case_id":"case_maria_001","resident_id":"resident_001","zone_status":"WARNING","alert_id":"alert_001"},
                   {"case_id":"case_david_002","resident_id":"resident_002","zone_status":"ORDER","alert_id":"alert_002"}],
 "checkins_sent":[{"case_id":"case_maria_001","message_id":"msg_001"},{"case_id":"case_david_002","message_id":"msg_002"}],
 "notify_coordinator":true,"duplicate":false}
```
B's rules:
- `STATUS` is mapped case-insensitively: `evacuation order`→ORDER, `evacuation warning`→WARNING, `shelter in place`→SHELTER_IN_PLACE, `normal`/`clear to repopulate`→INACTIVE. Anything else is rejected and listed, never guessed.
- Freshness comes from `STATEWIDE_LAST_UPDATED`/`EDIT_DATE` vs `ALERT_STALE_AFTER_SECONDS`.
- Dedupe by source record + version + zone.
- An alert is canceled only by an INACTIVE status **or** after missing from **2 consecutive successful ingests** (it's listed in `pending_cancellation` after the first miss). This covers Cal OES's rebuild gap.
- Check-ins go out only for new or changed `OFFICIAL_SIMULATION` WARNING/ORDER alerts, to residents with CHECKIN consent, keyed `alert:status:resident`. Ingesting the same feed 10× sends 1 check-in.

**`GET /alerts/active`**
```json
{"alerts":[{"alert_id":"alert_002","source_id":"SYNTHETIC_CALOES","source_record_id":"sim-0001","source_url":null,
  "event_type":"WILDFIRE_EVACUATION","status":"ORDER","raw_status":"Evacuation Order","zone_id":"zone_3_sector_a",
  "zone_name":"DEMO Zone 3 Sector A","geometry":{"type":"Polygon","coordinates":[…]},
  "issued_at":"2026-10-17T20:00:00Z","updated_at":"2026-10-17T20:01:00Z","expires_at":"2026-10-17T22:00:00Z",
  "fetched_at":"2026-10-17T20:02:00Z","freshness":"FRESH","verification":"OFFICIAL_SIMULATION",
  "can_trigger_checkins":true,"is_simulation":true,"affected_resident_count":1}],
 "feeds":[{"source_id":"SYNTHETIC_CALOES","source_type":"OFFICIAL_SIMULATION","last_ingest_at":"…",
           "source_updated_at":"…","feed_freshness":"FRESH"}],
 "generated_at":"…"}
```
Live alerts appear with `verification: OFFICIAL_LIVE_DISPLAY_ONLY`, `can_trigger_checkins: false`, `affected_resident_count: null`.

**`POST /demo/alerts/trigger`** (token): changes the synthetic feed. The Calamity agent's next poll picks it up (`poll_now:true` ingests immediately, for tests and fast demos).
```json
{"action":"ISSUE","preset":"ZONE_3_WARNING_AND_ORDER","poll_now":false}
```
`action`: `ISSUE | UPDATE | CANCEL | EXPIRE | FREEZE_FEED | UNFREEZE_FEED`. Use either `preset` (`ZONE_3_WARNING_AND_ORDER`, `ZONE_3_WARNING`, `ZONE_3_ORDER`) or explicit `zone_id` + `status` (raw Cal OES string) + optional `geometry`, `expires_in_minutes`. `FREEZE_FEED` stops `STATEWIDE_LAST_UPDATED` advancing, so the feed becomes STALE after the threshold (Scenario C).
Response: `{"action":"ISSUE","feed_version":3,"synthetic_feed_url":"/demo/feeds/caloes","poll_result":null}`.

### 5.4 Cases

**`GET /cases?zone_id=&resident_status=&zone_status=&unresolved=true`** → `{"cases":[CaseSummary]}`
CaseSummary: `case_id, display_name, zone_id, zone_status, resident_status, communication_status, map{color,label}, unresolved, next_step, updated_at`.

**`GET /cases/{case_id}`**
```json
{"case_id":"case_maria_001","resident_id":"resident_001","display_name":"Maria (synthetic)","zone_id":"zone_3",
 "zone_status":"WARNING","zone_sources":[{"alert_id":"alert_001","status":"WARNING","source_id":"SYNTHETIC_CALOES","freshness":"FRESH"}],
 "preferred_language":"es","resident_status":"PICKUP_CONFIRMED","communication_status":"REPLIED","needs_confirmed":true,
 "needs":{…},"consent":{"CHECKIN":true,"TRANSPORT":true,"DESTINATION":true,"RECOVERY":false},
 "progress_steps":[{"step":"REQUESTED","done":true,"at":"…"},{"step":"PROVIDER_ACCEPTED","done":true,"at":"…"},
                   {"step":"PICKUP_CONFIRMED","done":true,"at":"…","evidence_ref":"verif_001"},{"step":"ARRIVAL_CONFIRMED","done":false,"at":null}],
 "active_assignment":{"assignment_id":"assign_001","provider_id":"transport_org_a","volunteer_id":"volunteer_sarah",
                      "assignment_status":"ACCEPTED","confirmed_pickup_at":"…","confirmed_arrival_at":null},
 "destination_assignment":{"assignment_id":"assign_001_dest","provider_id":"destination_org_a","destination_id":"dest_center_a","assignment_status":"ACCEPTED"},
 "escalations":[],"recovery":{"status":"NOT_REQUESTED"},
 "map":{"color":"blue","label":"Pickup confirmed (not yet arrived)"},"unresolved":false,
 "next_step":"Awaiting arrival confirmation at the agreed destination.",
 "summary_text":"[SIMULATION] Maria (synthetic) | case case_maria_001 | Pickup confirmed (not yet arrived) (blue)\n…",
 "timeline":[{"event_id":"evt_001","type":"ALERT_VERIFIED","created_at":"…","evidence":"OFFICIAL_SIMULATION"}, …],
 "simulated":true}
```
The timeline never contains free-text resident details.

**`POST /cases/{case_id}/responses`** (token): resident reply via the simulator.
```json
{"text":"1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.","language":"es","sender":"sim_phone_maria","external_id":"sim_maria_reply_1"}
```
Response: `response_id, original_text, intent, candidate_needs, candidate_source` (`DETERMINISTIC | ASI_ONE_ASSISTED`), `needs_confirmed, confirmation_question, resident_status, communication_status, next_step, duplicate`. Confirming: send `"SI"`/`"YES"` → `needs_confirmed:true` plus `needs`. Unknown sender → 403, case unchanged. Repeated `external_id` → `duplicate:true`.

### 5.5 Matching and assignments

**`POST /matches/propose`** (token): evaluate raw offers from the provider agents and optionally create the proposal.
```json
{"case_id":"case_maria_001","request_id":"req_001","idempotency_key":"case_maria_001:match:v1",
 "create_proposal":true,"authorization":"SIMULATED_PREAPPROVED",
 "select":{"transport_offer_id":null,"destination_offer_id":null},
 "transport_offers":[{"offer_id":"offer_req_001_transport_org_a","provider_id":"transport_org_a","volunteer_id":"volunteer_sarah",
   "vehicle_id":"van_a1","provider_agent_address":"agent1q…","wheelchair_accessible":true,"wheelchair_spaces_available":1,
   "transfer_assistance":true,"oxygen_handling":false,"pets_allowed":true,"seats_available":2,
   "service_area_zones":["zone_2","zone_3","zone_4"],"eta_minutes":18,"valid_until":"2026-10-17T20:35:00Z"}],
 "destination_offers":[{"offer_id":"offer_req_002_destination_org_a","provider_id":"destination_org_a","destination_id":"dest_center_a",
   "provider_agent_address":"agent1q…","step_free_entry":true,"accessible_restroom":true,"pets_allowed":true,
   "service_animals_allowed":true,"beds_available":12,"oxygen_power_outlets":true,"valid_until":"2026-10-17T20:35:00Z"}]}
```
- `create_proposal:false` = "show suitable providers" (evaluation only, nothing stored except the evaluation event).
- `select` picks specific offers (e.g. an alternate after a decline). Otherwise B takes the top-ranked transport + top-ranked destination.
- Providers that already declined for this case are excluded automatically.
- Approval, base location and registered capabilities come from B's registry. Offer claims beyond the registry → `CAPABILITY_NOT_REGISTERED`.

Response (201 when a match is created; 200 for evaluation-only, no match, or a repeated key):
```json
{"case_id":"case_maria_001","request_id":"req_001","zone_status":"WARNING",
 "evaluation":{
   "transport":{"eligible":[{"offer_id":"offer_req_001_transport_org_a","provider_id":"transport_org_a","volunteer_id":"volunteer_sarah",
       "vehicle_id":"van_a1","rank":1,"eta_minutes":18,"distance_km":4.0,
       "reason_codes":["PROVIDER_APPROVED","VOLUNTEER_APPROVED","IN_SERVICE_AREA","WHEELCHAIR_OK","TRANSFER_OK","PET_OK","AVAILABILITY_CONFIRMED","OUTSIDE_ORDER_ZONE","ROUTE_AVOIDS_CLOSURES"]}],
     "rejected":[{"offer_id":"offer_req_001_transport_org_b","provider_id":"transport_org_b","reason_codes":["NOT_WHEELCHAIR_ACCESSIBLE","NO_TRANSFER_ASSISTANCE"]}]},
   "destination":{"eligible":[{"offer_id":"offer_req_002_destination_org_a","provider_id":"destination_org_a","destination_id":"dest_center_a","rank":1,
       "reason_codes":["PROVIDER_APPROVED","STEP_FREE_OK","PET_OK","CAPACITY_OK","AVAILABILITY_CONFIRMED"]}],"rejected":[]}},
 "escalation_required":false,"no_match_reason":null,
 "match":{"assignment_id":"assign_001","eligible":true,"status":"PROPOSED","provider_id":"transport_org_a","volunteer_id":"volunteer_sarah",
   "vehicle_id":"van_a1","destination_provider_id":"destination_org_a","destination_id":"dest_center_a",
   "reason_codes":["WHEELCHAIR_OK","TRANSFER_OK","PET_OK","OUTSIDE_ORDER_ZONE"],"authorization":"SIMULATED_PREAPPROVED",
   "route_status":"ILLUSTRATIVE_ONLY","shared_with_provider":{"wheelchair_accessible_vehicle":true,"transfer_assistance":true,
   "portable_oxygen_equipment":false,"pet_count":1,"service_animal":false,"pickup_area":"zone_3_sector_b_synthetic"},
   "idempotency_key":"case_maria_001:match:v1"},
 "duplicate":false}
```
No match (David, or nothing eligible): HTTP 200, `match:null`, `escalation_required:true`, `no_match_reason` ∈ `ORDER_ZONE | ZONE_STALE | ZONE_UNKNOWN | NO_ELIGIBLE_TRANSPORT | NO_ELIGIBLE_DESTINATION`. When transport is unresolvable, the case moves to `REQUIRES_COORDINATOR`.
A `select`ed offer that fails → 409 (`UNSAFE_ZONE`, `ZONE_STALE`, `PROVIDER_NOT_APPROVED`, `OFFER_NOT_ELIGIBLE`).
The exact pickup point is **never** in this response; it's released only on transport acceptance.

**`POST /assignments/{assignment_id}/accept`** (token): the Coordinator forwards a provider agent's `AcceptResponse`. The transport **or** destination provider of the match responds on the same `assignment_id`.
```json
{"provider_id":"transport_org_a","volunteer_id":"volunteer_sarah","provider_agent_address":"agent1q…",
 "decision":"ACCEPTED","reason":"SIMULATED_PROVIDER_ACCEPTED","idempotency_key":"assign_001:accept:transport_org_a"}
```
Response:
```json
{"assignment_id":"assign_001","case_id":"case_maria_001","responding_provider_id":"transport_org_a","service_type":"accessible_transport",
 "provider_response":"ACCEPTED","assignment_status":"ACCEPTED","resident_status":"PROVIDER_ACCEPTED",
 "pickup_details":{"pickup_point":"SYNTHETIC: Zone 3 Sector B meeting point 4"},
 "eta":{"minutes":18,"label":"Illustrative estimate, not a guarantee"},
 "confirmed_pickup_at":null,"confirmed_arrival_at":null,"next_alternate":null,
 "next_step":"Transport accepted; destination acceptance still needed before arrival.","duplicate":false}
```
- `DECLINED` → `assignment_status: DECLINED`. The resident stays `NEEDS_ASSISTANCE`, and `next_alternate: {"offer_id","provider_id"}` names the next eligible offer (call `matches/propose` with `select`). If none is left → `REQUIRES_COORDINATOR`.
- A reply to a `CANCELED`/`DECLINED` assignment → 409 `INVALID_TRANSITION`.
- A provider/volunteer mismatch → 403.
- The resident status changes **only** on transport acceptance. Arrival later requires the destination to have accepted too.

**`POST /assignments/{assignment_id}/pickup`** (token)
```json
{"evidence":{"type":"PROVIDER_AND_RESIDENT_CONFIRMATION","provider_confirmed":true,"resident_confirmed":true,
  "caregiver_confirmed":false,"code_verified":true,"source":"SIMULATED","provider_report_id":"pickup_rep_001",
  "confirmations":[{"party":"transport_provider","party_id":"transport_org_a"},{"party":"resident","party_id":"resident_001"}]},
 "idempotency_key":"assign_001:pickup"}
```
Required: provider **and** (resident **or** caregiver). `confirmations` is optional; when present, every `party_id` must match the case's real participants. A code helps confirm contact; it never proves safety.

**`POST /assignments/{assignment_id}/arrival`** (token)
```json
{"evidence":{"type":"DESTINATION_CHECKIN","destination_provider_id":"destination_org_a","destination_id":"dest_center_a",
  "provider_confirmed":true,"source":"SIMULATED","provider_report_id":"arrival_rep_001"},"idempotency_key":"assign_001:arrival"}
```
Required: pickup already confirmed, the destination provider **accepted**, and a check-in by that destination provider (or resident/caregiver + transport provider).
Pickup/arrival response: `assignment_id, case_id, assignment_status, resident_status, confirmed_pickup_at, confirmed_arrival_at, map, next_step, duplicate`. Green only after arrival.

### 5.6 Escalation (Escalation Simulator agent ↔ B)

**`POST /cases/{case_id}/escalate`** (token) → 201
```json
{"reason":"ACTIVE_EVACUATION_ORDER_ZONE","idempotency_key":"case_david_002:escalation:v1"}
```
`reason` ∈ `ACTIVE_EVACUATION_ORDER_ZONE` (case must be in an ORDER zone), `NO_ELIGIBLE_PROVIDER`, `PROVIDER_TIMEOUT`, `NO_REPLY_AFTER_DEADLINE` (communication status must match), `COORDINATOR_REQUESTED`.
```json
{"escalation_id":"esc_001","case_id":"case_david_002","reason":"ACTIVE_EVACUATION_ORDER_ZONE",
 "recipient":"SIMULATED_AUTHORIZED_RESPONSE_SERVICE","status":"REQUESTED","assistance_confirmed":false,
 "case_summary_for_recipient":{"case_id":"case_david_002","zone_id":"zone_3","zone_status":"ORDER","preferred_language":"en",
   "wheelchair_accessible_vehicle":true,"portable_oxygen_equipment":false,"pet_count":0},
 "resident_status":"REQUIRES_COORDINATOR","assignment_status":"UNRESOLVED",
 "next_step":"Awaiting simulated authorized service acknowledgment; assistance not confirmed."}
```
If `AUTO_ESCALATION_ACK=true` (no escalation agent running, e.g. the smoke test), B acknowledges immediately and returns `status: ACKNOWLEDGED_REQUEST_ONLY`.

**`POST /escalations/{escalation_id}/ack`** (token): the Coordinator forwards the Escalation agent's `EscalationAck`.
```json
{"status":"ACKNOWLEDGED_REQUEST_ONLY","recipient_agent_address":"agent1q…","idempotency_key":"esc_001:ack"}
```
→ `{"escalation_id":"esc_001","status":"ACKNOWLEDGED_REQUEST_ONLY","assistance_confirmed":false,"resident_status":"REQUIRES_COORDINATOR","assignment_status":"UNRESOLVED","next_step":"Coordinator follows up with simulated authorized response service; assistance not confirmed."}`
`assistance_confirmed` is **always** false.

### 5.7 Recovery (Recovery Provider agent ↔ B)

**`POST /cases/{case_id}/recovery`** (token) → 201
```json
{"consent":{"share_recovery_needs":true,"granted_by":"RESIDENT","granted_at":"2026-10-17T20:40:00Z"},
 "need_type":"TEMPORARY_ACCOMMODATION","idempotency_key":"case_maria_001:recovery:v1"}
```
```json
{"referral_id":"ref_001","case_id":"case_maria_001","status":"REQUESTED","provider_id":"recovery_org_demo",
 "shared_fields":["destination_accessibility","pet_count","preferred_language","service_animal","wheelchair_accessible_vehicle"],
 "shared_payload":{"referral_id":"ref_001","need_type":"TEMPORARY_ACCOMMODATION","preferred_language":"es",
   "wheelchair_accessible_vehicle":true,"destination_accessibility":["step_free_entry"],"pet_count":1,"service_animal":false},
 "housing_secured":false}
```
`shared_payload` is exactly what the Coordinator may forward to the Recovery agent, nothing more. `granted_by`: `RESIDENT | CAREGIVER`. `share_recovery_needs:false` → 409 `CONSENT_MISSING`, recorded as `NOT_REQUESTED`, nothing shared.

**`POST /recovery/{referral_id}/respond`** (token): forwards the Recovery agent's decision.
```json
{"provider_id":"recovery_org_demo","decision":"ACCEPTED","evidence":null,"idempotency_key":"ref_001:respond:accepted"}
```
`decision`: `ACCEPTED | DECLINED` (→ `UNRESOLVED`) `| COMPLETED`. `COMPLETED` requires `evidence: {"type":"SIMULATED_RESERVATION_CONFIRMED","reference":"res_sim_001"}`.
→ `{"referral_id":"ref_001","status":"ACCEPTED","housing_secured":false}`. `housing_secured` is true **only** for COMPLETED with that evidence (still simulated).

### 5.8 Road closures (News agent ↔ B)

**`GET /demo/feeds/news`** → `{"items":[{"item_id":"news_001","source_name":"Fictional Valley Gazette (DEMO)","url":null,"published_at":"…","headline":"Residents report Canyon Rd blocked by debris (DEMO)","body":"…"}]}`

**`GET /demo/feeds/closures`** (synthetic **official** closures)
→ `{"closures":[{"closure_id":"off_001","issuing_authority":"SIMULATED_LA_COUNTY_PUBLIC_WORKS","road_name":"Ridge Ave","segment_description":"between Zone 3 Sector B and Zone 4","status":"CLOSED","published_at":"…","updated_at":"…","expires_at":"…"}]}`

**`POST /demo/closures/trigger`** (token): `{"action":"PUBLISH_OFFICIAL","road_name":"Ridge Ave","status":"CLOSED"}`. `action` ∈ `PUBLISH_OFFICIAL | LIFT_OFFICIAL | PUBLISH_NEWS` (with `headline`, `body`).

**`POST /closures/ingest`** (token): the News agent posts extracted items.
```json
{"source":{"source_id":"SYNTHETIC_NEWS","source_type":"NEWS","url":"http://127.0.0.1:8000/demo/feeds/news","fetched_at":"…"},
 "items":[{"source_item_id":"news_001","published_at":"…","url":null,"headline":"Residents report Canyon Rd blocked by debris (DEMO)",
   "raw_text":"…","extraction_method":"ASI_ONE_EXTRACTION",
   "candidate":{"road_name":"Canyon Rd","claimed_status":"CLOSED","location_text":"near Zone 3"}}],
 "idempotency_key":"SYNTHETIC_NEWS:news_001"}
```
`extraction_method`: `STRUCTURED_FEED` (official feed fields) or `ASI_ONE_EXTRACTION` (LLM read the article).
**B sets `state` by fixed rules; the agent never sends a state:**
- `OFFICIAL_SIMULATION` + CLOSED → `OFFICIAL_CONFIRMED`; `NEWS` / `REAL_WORLD_CONTEXT` → `UNVERIFIED_REPORT`;
- contradictory active claims about the same segment from different sources → `CONFLICTING`;
- past expiry or lifted → `EXPIRED`;
- road names map to synthetic segments via B's gazetteer. Unmapped names are kept and shown, but never used for routing;
- `REAL_WORLD_CONTEXT` is display-only.

Response: `{"ingest_id":"cl_ingest_002","accepted":[{"closure_id":"closure_002","state":"UNVERIFIED_REPORT","segment_id":"seg_canyon_rd"}],"rejected":[],"new_official_closures":[],"notify_coordinator":true,"duplicate":false}`.

**`GET /closures`**
```json
{"closures":[{"closure_id":"closure_001","road_name":"Ridge Ave","segment_id":"seg_ridge_ave","state":"OFFICIAL_CONFIRMED",
  "claimed_status":"CLOSED","used_for_routing":true,
  "sources":[{"source_id":"SYNTHETIC_OFFICIAL_CLOSURES","source_type":"OFFICIAL_SIMULATION","url":null,"published_at":"…","headline":"Ridge Ave closed (SIMULATED)"}],
  "first_seen_at":"…","updated_at":"…","expires_at":"…"}],
 "note":"No report does not mean a road is open."}
```

### 5.9 Routes (Route Planner agent ↔ B ↔ HERE)

**`POST /routes/constraints`** (token)
```json
{"case_id":"case_maria_001","destination":{"destination_id":"dest_center_a"},"idempotency_key":"case_maria_001:route:v1"}
```
→ OK:
```json
{"route_request_id":"route_001","status":"OK","origin":{"lat":34.1012,"lon":-118.0964,"label":"Synthetic pickup area"},
 "destination":{"lat":34.0890,"lon":-118.0700,"label":"Civic Center (fictional)"},
 "avoid_areas":[{"kind":"ORDER_ZONE","id":"alert_002","geometry":{"type":"Polygon","coordinates":[…]}},
                {"kind":"OFFICIAL_CLOSURE","id":"closure_001","geometry":{"type":"Polygon","coordinates":[…]}}],
 "cautions":[{"closure_id":"closure_002","state":"UNVERIFIED_REPORT","road_name":"Canyon Rd","geometry":{…}}],
 "max_avoid_areas":20,"data_as_of":"…","label":"ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"}
```
→ refused (409 `ROUTE_REFUSED`, `reasons` ∈ `ORDER_ZONE` (origin or destination inside an order) `| ZONE_STALE | ZONE_UNKNOWN | TOO_MANY_AVOID_AREAS`). B refuses rather than truncate.
Closure lines are buffered into polygons by B, so HERE gets areas.

**`POST /routes/previews`** (token): the Route agent submits HERE's result for B's post-check.
```json
{"route_request_id":"route_001","provider":"HERE","polyline":{"type":"LineString","coordinates":[[-118.0964,34.1012],…]},
 "distance_m":6200,"duration_s":840,"provider_notices":[],"computed_at":"…","idempotency_key":"route_001:preview"}
```
`polyline: null` (HERE found no route) → `NO_ROUTE_CONFIRMED`.
```json
{"route_preview_id":"rprev_001","route_request_id":"route_001","status":"ILLUSTRATIVE_ONLY","refusal_reason":null,
 "crosses":[],"cautions_on_path":["closure_002"],"distance_m":6200,"duration_s":840,
 "eta_label":"Estimate only, not a guarantee","label":"ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"}
```
`REFUSED` when the polyline intersects any ORDER polygon or official closure (`crosses` lists them), or data went stale since the constraints. Recorded on the case timeline. **Never** described as safe.

### 5.10 Card data (A renders, B supplies)

**`GET /dashboard/summary`**
```json
{"generated_at":"…","simulated":true,
 "counts_by_status":[{"status":"NEEDS_ASSISTANCE","count":0,"color":"red","label":"Assistance needed"},
                     {"status":"ARRIVAL_CONFIRMED","count":1,"color":"green","label":"Arrival confirmed at agreed destination"},
                     {"status":"REQUIRES_COORDINATOR","count":1,"color":"black","label":"Coordinator attention: assistance not confirmed"}],
 "unresolved":[{"case_id":"case_david_002","display_name":"David (synthetic)","reason":"ACTIVE_EVACUATION_ORDER_ZONE","next_step":"…"}],
 "alerts":{"active_order":1,"active_warning":1,"feed_freshness":"FRESH","last_ingest_at":"…"},
 "closures":{"official_confirmed":1,"unverified":1,"conflicting":0}}
```
**`GET /dashboard/cases`** → `{"cases":[{"case_id","display_name","zone_id","zone_status","resident_status","map","coarse_location":{"lat":34.10,"lon":-118.10},"unresolved","updated_at"}]}`. Coordinates are rounded to 2 decimals; no pickup points.

### 5.11 Simulator hooks (B; tests and demo)

`POST /sim/inbound {sender, text, external_id?, language?}` (routes by sender; unknown → 403) · `POST /sim/delivery {message_id, delivered}` · `POST /sim/cases/{case_id}/no-reply-deadline` · `GET /sim/messages?case_id=`.

## 6. Fetch.ai agent messages (A owns `integrations/fetch_adapter.py`; listed so both sides align)

All carry `schema_version, correlation_id, created_at`, plus `case_id` / `idempotency_key` where relevant. Providers receive **only** consent-scoped fields (`shared_with_provider`, `shared_payload`, `case_summary_for_recipient`).

| Message | From → To | Key fields | B endpoint it feeds |
|---|---|---|---|
| `AlertNotification` | Calamity → Coordinator | `ingest_id, new_alerts, affected_cases` | (result of `/alerts/ingest`) |
| `ClosureNotification` | News → Coordinator | `ingest_id, new_official_closures, new_reports` | (result of `/closures/ingest`) |
| `OfferRequest` / `OfferResponse` | Coordinator ↔ Transport/Destination | `request_id, service_type, zone_id, requirements` / `offers[]` | `/matches/propose` |
| `AcceptRequest` / `AcceptResponse` | Coordinator ↔ provider | `assignment_id, offer_id, provider_id, shared_needs` / `decision, reason` | `/assignments/{id}/accept` |
| `PickupReport` | Transport → Coordinator | `assignment_id, provider_id, report_id, code_verified` | `/assignments/{id}/pickup` (+ resident confirmation) |
| `ArrivalReport` | Destination → Coordinator | `assignment_id, destination_provider_id, destination_id, report_id` | `/assignments/{id}/arrival` |
| `RecoveryRequest` / `RecoveryResponse` | Coordinator ↔ Recovery | `referral_id, shared_payload` / `decision, evidence` | `/recovery/{id}/respond` |
| `EscalationRequest` / `EscalationAck` | Coordinator ↔ Escalation | `escalation_id, case_summary_for_recipient` / `status` | `/escalations/{id}/ack` |
| `RouteRequest` / `RouteResponse` | Coordinator ↔ Route | `case_id, destination_id` / `route_preview` | `/routes/constraints`, `/routes/previews` |

## 7. Environment variables

| Var | Side | Default |
|---|---|---|
| `DOORSTEP_API_URL` | A | `http://127.0.0.1:8000` |
| `DEMO_AUTH_TOKEN` | both | `change-me-local-demo-token` |
| `SIMULATION_MODE` | B | `true` (backend refuses otherwise) |
| `ALERT_FEED_URL` | A (Calamity) | `${DOORSTEP_API_URL}/demo/feeds/caloes` |
| `ALERT_POLL_INTERVAL_SECONDS` | A (Calamity) | `120` |
| `ALERT_STALE_AFTER_SECONDS` | B | `900` (demo may lower it) |
| `AUTO_ESCALATION_ACK` | B | `true` locally; `false` when the Escalation agent runs |
| `USE_LLM_INTENT` | B (extraction) / A (intent) | `false` |
| `ASI_ONE_API_KEY` | A, B | — (never committed) |
| `HERE_API_KEY` | A (Route) | — (never committed) |
| `NEWS_POLL_INTERVAL_SECONDS` | A (News) | `120` |

## 8. Migration from v1.0

| v1.0 | v2.0 |
|---|---|
| `POST /demo/warnings` | `POST /demo/alerts/trigger` (+ Calamity agent → `POST /alerts/ingest`) |
| `POST /cases/{id}/transport/evaluate` + `/destination/evaluate` + `POST /cases/{id}/assignments` | `POST /matches/propose` |
| `POST /assignments/{id}/acceptance` | `POST /assignments/{id}/accept` |
| `POST /cases/{id}/escalations` | `POST /cases/{id}/escalate` (+ `POST /escalations/{id}/ack`) |
| `POST /cases/{id}/recovery-referrals` | `POST /cases/{id}/recovery` (+ `POST /recovery/{id}/respond`) |
| `zone_rule` (`OUTSIDE_ACTIVE_ORDER`…) | `zone_status` (`ORDER`, `WARNING`, …) from geofencing |
| `service_status` | `assignment_status` |
| `rejected[].reasons` / `match_reasons` | `reason_codes` (§4) |
| `schema_version: "1.0"` | `"2.0"` |

Unchanged: auth header, `X-Correlation-ID`, error shape, `/health`, `/demo/reset`, `GET /cases`, `GET /cases/{id}` (extended), `POST /cases/{id}/responses`, pickup and arrival paths, `/sim/*`, case and resident IDs. **v1 routes are removed in the same PR window as A's client switch** (plan §6.2).

## 9. Seed data (fixed IDs, all fictional)

| Kind | IDs |
|---|---|
| Residents / cases | `resident_001` / `case_maria_001` "Maria (synthetic)", es, `sim_phone_maria`, inside the zone 3 **WARNING** polygon, wheelchair + transfer help + 1 dog, step-free destination. `resident_002` / `case_david_002` "David (synthetic)", en, `sim_phone_david`, caregiver `caregiver_002` (`sim_phone_david_caregiver`), inside the zone 3 sector A **ORDER** polygon, wheelchair |
| Transport orgs | `transport_org_a` (approved, `van_a1`, `volunteer_sarah`, the match), `transport_org_b` (closer sedan `sedan_b1`, not accessible), `transport_org_c` (**not approved**), `transport_org_d` (no pets), `transport_org_e` (eligible alternate behind a closure) |
| Destination orgs | `destination_org_a` / `dest_center_a` (step-free, pets OK), `destination_org_b` / `dest_library_b` (not step-free), `destination_org_c` / `dest_hotel_c` (no pets) |
| Recovery | `recovery_org_demo` |
| Alert presets | `ZONE_3_WARNING` (covers Maria), `ZONE_3_ORDER` (covers David), `ZONE_3_WARNING_AND_ORDER` |
| Closures | official `Ridge Ave` (blocks the sector B ↔ zone 4 road), news report `Canyon Rd` (unverified) |

Coordinates and polygons are fictional points in an LA-area-like grid, defined in `src/doorstep/demo/seed.py` once implemented. Shapely tests include a point exactly on a polygon edge.

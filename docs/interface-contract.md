# Doorstep Interface Contract — v2.0 (revision 2)

Shared between Developer A (Fetch.ai agents, ASI:One, cards, LangGraph) and Developer B (backend, MongoDB, geography, matching).
**Owner: Developer B** (`docs/DOORSTEP_V2_TEAM_PLAN.md` §6). Source: that plan (revision 2) §1–§7, plus the safety rules in `Doorstep_V2_Two_Person_Claude_Code_Plan.md` and `Doorstep_Implementation_Master_Spec.md`. If anything here conflicts with a safety rule, the safety rule wins.

**Status:** proposed. Frozen once A signs off (checkpoint C1). After that, any change bumps `schema_version` to `2.1`, goes in a small PR touching only this file, and needs both developers to approve.

**Everything is synthetic.** Residents, organizations, volunteers, addresses and phone numbers are fictional. All resident- and volunteer-facing text starts with `DOORSTEP DEMO`. Every card shows SIMULATION. Real-world data (live Cal OES feed, real news) is **display-only**: it never triggers check-ins or outreach, never blocks roads, never changes a case.

---

## 1. Conventions

- **Version:** every request and response body carries `"schema_version": "2.0"`, and so do agent messages.
- **IDs:** opaque synthetic strings. Fixed demo IDs are in §10. B generates deterministic sequential IDs (`assign_001`, `esc_001`, `ref_001`, `evt_001`, `alert_001`, `closure_001`, `route_001`), so a reset followed by the same calls gives the same IDs.
- **Time:** UTC ISO-8601 with `Z`. The raw Cal OES payload keeps its epoch-millisecond fields; B converts them.
- **Geometry:** GeoJSON, coordinates **`[longitude, latitude]`**, WGS84. Addresses are stored as `{label, lat, lon}`. All coordinates are fictional.
- **Correlation:** the Doorstep agent creates a `correlation_id` per ASI:One turn and sends it as header `X-Correlation-ID` (a body `correlation_id` is the fallback). Every agent passes it on. B echoes it in the response body, the response header, every timeline event and every error.
- **Idempotency:** every create (`alerts/ingest`, `outreach`, `availability`, `matches/propose`, `accept`, `pickup`, `arrival`, `escalate`, `ack`, `recovery`, `respond`, `closures/ingest`, `routes/*`) takes an `idempotency_key`. Repeating a key returns the original result with HTTP 200 and `"duplicate": true`.
- **Auth (demo gating, not production auth):**
  - All POSTs need `Authorization: Bearer <DEMO_AUTH_TOKEN>`.
  - **Org-scoped** routes (`/orgs/{org_id}/…`) also need header `X-Org-Agent: <org_id>` equal to the path's `org_id`; otherwise 403. That way an org agent can read and write only its own org.
  - GETs are open but sanitized. They never return volunteer addresses or phones, resident addresses or phones, or pickup points, except the org-scoped volunteer read.
- **Validation:** Pydantic v2. Unknown top-level fields on write bodies → 422. **Exception:** raw feed payloads ignore unknown fields.
- **Status words are authoritative.** A shows B's status strings verbatim. ASI:One API text may explain them, never replace them.

## 2. Enums and codes

| Name | Values |
|---|---|
| `resident_status` | `UNKNOWN`, `NEEDS_ASSISTANCE`, `PROVIDER_ACCEPTED`, `PICKUP_CONFIRMED`, `ARRIVAL_CONFIRMED`, `REQUIRES_COORDINATOR` |
| `communication_status` | `NOT_SENT`, `SENT`, `DELIVERED`, `DELIVERY_FAILED`, `REPLIED`, `NO_REPLY_AFTER_DEADLINE`, `UNKNOWN` |
| `assignment_status` | `PROPOSED`, `AWAITING_PROVIDER`, `ACCEPTED`, `DECLINED`, `CANCELED`, `COMPLETED`, `UNRESOLVED` |
| `zone_status` | `ORDER`, `WARNING`, `SHELTER_IN_PLACE`, `OUTSIDE_KNOWN_ZONES`, `UNKNOWN`, `STALE` |
| `alert.status` | `ORDER`, `WARNING`, `SHELTER_IN_PLACE`, `INACTIVE`, `UNKNOWN` |
| `alert.verification` | `OFFICIAL_SIMULATION`, `OFFICIAL_LIVE_DISPLAY_ONLY` |
| `calamity_type` | `WILDFIRE`, `FLOOD`, `EARTHQUAKE`, `STORM`, `HEAT`, `OTHER`, `UNKNOWN` (feed gave none; orgs with `ANY` or all types are contacted) |
| `org services` | `TRANSPORT`, `SHELTER`, `RECOVERY_HOUSING`, `INSURANCE_GUIDANCE`, `SUPPLIES`, `MEDICAL_EQUIPMENT_REPLACEMENT`, `CASEWORK` |
| `volunteer_availability` | `UNASKED`, `ASKED`, `AVAILABLE`, `UNAVAILABLE`, `NO_REPLY` (per alert) |
| `freshness` | `FRESH`, `STALE`, `NO_DATA` |
| `escalation.status` | `REQUESTED`, `ACKNOWLEDGED_REQUEST_ONLY`, `NO_ACKNOWLEDGMENT` |
| `recovery.status` | `NOT_REQUESTED`, `REQUESTED`, `ACCEPTED`, `COMPLETED`, `UNRESOLVED` |
| `recovery help_type` | `TEMPORARY_HOUSING`, `INSURANCE_GUIDANCE`, `SUPPLIES`, `MEDICAL_EQUIPMENT_REPLACEMENT`, `CASEWORK` |
| `closure.state` | `OFFICIAL_CONFIRMED`, `UNVERIFIED_REPORT`, `CONFLICTING`, `EXPIRED` |
| `closure.source_type` | `OFFICIAL_SIMULATION`, `NEWS`, `REAL_WORLD_CONTEXT` |
| `route.status` | `ILLUSTRATIVE_ONLY`, `REFUSED`, `NO_ROUTE_CONFIRMED` |
| `consent purpose` | `CHECKIN`, `TRANSPORT`, `DESTINATION`, `RECOVERY` |
| `map color` | `red` NEEDS_ASSISTANCE, `yellow` PROVIDER_ACCEPTED, `blue` PICKUP_CONFIRMED, `green` ARRIVAL_CONFIRMED, `black` REQUIRES_COORDINATOR, `gray` UNKNOWN; always with a text `label` |

### Needs codes (shared by residents and volunteers)

A resident's `needs` and a volunteer's `needs_they_can_cater` (and a shelter site's `features`) use the **same integers**, so matching is code-to-code: *resident needs ⊆ volunteer capabilities*.

| Code | Need | Notes |
|---|---|---|
| 1 | `WHEELCHAIR` | wheelchair-accessible vehicle; also needs `wheelchair_spaces ≥ 1` |
| 2 | `TRANSFER_ASSIST` | help getting into the vehicle |
| 3 | `OXYGEN_EQUIPMENT` | oxygen equipment handling (never assumed for ordinary volunteers) |
| 4 | `PET` | also needs `pet_capacity ≥ pet_count` |
| 5 | `SERVICE_ANIMAL` | |
| 6 | `STEP_FREE_DESTINATION` | checked against the shelter site, not the vehicle |
| 7 | `SPANISH_SPEAKER` | communication support; **never** a reason to reject (preference only) |
| 8 | `MOBILITY_AID` | walker / cane space |
| 9 | `MEDICAL_EQUIPMENT_SPACE` | |
| 10 | `CAREGIVER_RIDES_ALONG` | needs `vehicle_seats ≥ 2` |

New codes may be added in a contract bump. Codes never change meaning.

**Never:** acceptance ⇒ pickup, pickup ⇒ arrival, silence ⇒ danger or safety, failed delivery ⇒ no reply, escalation acknowledgment ⇒ dispatch, referral accepted ⇒ help delivered, no closure report ⇒ road open, missing/stale data ⇒ safe, a radius ⇒ an evacuation order.

**Zones:** a resident is affected when an official zone polygon **covers** their point (the edge counts as inside). If several alerts cover the point, `ORDER` > `SHELTER_IN_PLACE` > `WARNING` > `OUTSIDE_KNOWN_ZONES`. Any relevant stale source → `STALE`; no data or an uncertain geocode → `UNKNOWN`. A radius around an incident point is **awareness only**.

## 3. Errors

```json
{"schema_version":"2.0","error":"UNSAFE_ZONE","detail":"Ordinary volunteer assignment is blocked in an active order zone","correlation_id":"corr_7f3a","reasons":["ORDER_ZONE"]}
```

| HTTP | `error` | When |
|---|---|---|
| 401 | `UNAUTHORIZED` | missing/invalid Bearer token |
| 403 | `UNAUTHORIZED` | `X-Org-Agent` ≠ path org; wrong org/volunteer on an assignment; unknown SMS sender; consent not from resident/caregiver |
| 404 | `NOT_FOUND` | unknown resident/org/volunteer/case/assignment/alert |
| 409 | `CONSENT_MISSING` | sharing without the purpose consent (nothing shared) |
| 409 | `UNSAFE_ZONE` / `ZONE_STALE` / `ZONE_UNKNOWN` | assignment or route refused by zone status |
| 409 | `NOT_ELIGIBLE` | a `select`ed volunteer/site fails a rule (see `reasons`) |
| 409 | `NOT_AUTHORIZED` | `authorization` is not `SIMULATED_PREAPPROVED` |
| 409 | `NEEDS_NOT_CONFIRMED` | matching before the resident confirmed needs |
| 409 | `ALREADY_RESERVED` | volunteer reserved for another case |
| 409 | `STALE_AVAILABILITY` | availability answer for an old alert |
| 409 | `INVALID_TRANSITION` | late reply to a canceled/declined assignment, pickup before acceptance, arrival before pickup… |
| 409 | `INSUFFICIENT_EVIDENCE` | pickup/arrival evidence incomplete or from the wrong party |
| 409 | `REASON_MISMATCH` | escalation reason not true for this case |
| 409 | `ROUTE_REFUSED` | route constraints refused (see `reasons`) |
| 422 | `VALIDATION_ERROR` / `FEED_INVALID` | body or feed payload invalid |

## 4. Reason codes (shown on cards)

**Positive:** `ORG_APPROVED`, `VOLUNTEER_APPROVED`, `CALAMITY_TYPE_SUPPORTED`, `WITHIN_SERVICE_RADIUS`, `AVAILABLE_FOR_THIS_ALERT`, `NEEDS_COVERED`, `WHEELCHAIR_OK`, `TRANSFER_OK`, `OXYGEN_OK`, `PET_OK`, `SERVICE_ANIMAL_OK`, `SEATS_OK`, `STEP_FREE_OK`, `BEDS_OK`, `OUTSIDE_ORDER_ZONE`, `ROUTE_AVOIDS_ORDER_ZONES`.

**Rejection:** `ORG_NOT_APPROVED`, `VOLUNTEER_NOT_APPROVED`, `CALAMITY_TYPE_NOT_SUPPORTED`, `OUTSIDE_SERVICE_RADIUS`, `NOT_ASKED_YET`, `AWAITING_REPLY` (asked, no answer yet), `UNAVAILABLE`, `NO_REPLY`, `AVAILABILITY_FROM_OLD_ALERT`, `ALREADY_RESERVED`, `NEEDS_NOT_COVERED` (with `missing_needs: [codes]`), `NO_WHEELCHAIR_SPACE`, `INSUFFICIENT_PET_CAPACITY`, `NO_SEATS`, `NO_BEDS`, `ORDER_ZONE`, `SHELTER_IN_ORDER_ZONE`, `ZONE_STALE`, `ZONE_UNKNOWN`, `ROUTE_THROUGH_ORDER_ZONE`, `ALREADY_DECLINED`.

## 5. HTTP API (B implements, A calls)

Base URL `DOORSTEP_API_URL` (default `http://127.0.0.1:8000`). Responses below omit `schema_version` and `correlation_id`; **both are always present**.

### 5.1 Health and demo
- **`GET /health`** → `{"status":"ok","version":"2.0.0","simulation_mode":true,"databases":{"users":"ok","orgs":"ok"},"alerts":{"last_ingest_at":"…","feed_freshness":"FRESH"},"closures":{"last_ingest_at":"…"}}`
- **`POST /demo/reset`** (token): reseed §10 into both databases. → `{"status":"reset","residents":2,"organizations":7,"volunteers":6,"simulated":true}`

### 5.2 Registration (before a calamity)

**`POST /residents`** → 201
```json
{"resident":{"name":"Rosa (synthetic)","phone":"sim_phone_rosa","language":"es",
  "address":{"label":"SYNTHETIC: 12 Example Way","lat":34.1052,"lon":-118.0951,"geocode_confidence":"HIGH"},
  "emergency_contacts":[{"name":"Luis (synthetic)","phone":"sim_phone_luis","relationship":"son"}],
  "needs":[1,6],"pet_count":0,"wants_help_contact":true,
  "consents":{"CHECKIN":true,"TRANSPORT":true,"DESTINATION":true,"RECOVERY":false}}}
```
→ `{"resident_id":"resident_003","zone_status":"OUTSIDE_KNOWN_ZONES","consents":{…},"created_at":"…"}`
- `wants_help_contact:false` means the resident is never contacted (and `CHECKIN` is forced false).
- `geocode_confidence` `LOW`/`FAILED` → `zone_status: UNKNOWN`. Before any simulated feed has been ingested, `zone_status` is also `UNKNOWN` (no data never means outside or safe).
- An emergency contact can reply on the resident's behalf, as a caregiver.

**`POST /organizations`** → 201: registers an org with its volunteers embedded (the team's document shape).
```json
{"organization":{"org_id":"red_cross_demo","name":"Red Cross (fictional demo chapter)",
  "location":{"label":"Culver City (synthetic)","lat":34.021,"lon":-118.396},
  "calamity_types":["WILDFIRE","FLOOD","EARTHQUAKE"],"services":["TRANSPORT","SHELTER","RECOVERY_HOUSING"],
  "approved":true,"service_radius_km":25,"agent_address":"agent1q…",
  "volunteers":[{"volunteer_id":"volunteer_maya","name":"Maya (synthetic)","phone":"sim_phone_maya",
    "address":{"label":"SYNTHETIC: Zone 4","lat":34.080,"lon":-118.120},
    "vehicle_type":"MINIVAN","vehicle_seats":4,"wheelchair_spaces":0,"pet_capacity":1,
    "needs_they_can_cater":[2,4,7,8],"approved":true}],
  "shelter_sites":[{"site_id":"rc_shelter_1","name":"Red Cross Shelter (fictional)","lat":34.03,"lon":-118.38,
    "beds_available":30,"features":[6,4,5]}],
  "recovery_services":["TEMPORARY_HOUSING"]}}
```
→ `{"org_id":"red_cross_demo","approved":true,"volunteers":["volunteer_maya"],"shelter_sites":["rc_shelter_1"]}`
- `vehicle_type`: free label (`WHEELCHAIR_VAN`, `MINIVAN`, `SEDAN`, `SUV`, `BUS`).
- `approved` (org and each volunteer) = simulated partner preapproval, never decided by an LLM.

**`POST /organizations/{org_id}/volunteers`** (token + `X-Org-Agent`) → 201: add a volunteer to an existing org (same volunteer shape).

**`GET /organizations`**: sanitized registry for cards: `org_id, name, location.label, calamity_types, services, approved, volunteer_count, shelter_sites (name, beds, features)`. No volunteer addresses or phones.

### 5.3 Alerts (Calamity Checker ↔ B)

**`GET /demo/feeds/caloes`**: the synthetic feed in the **exact Cal OES GeoJSON shape**.
```json
{"type":"FeatureCollection","features":[{"type":"Feature","id":1,
  "geometry":{"type":"Polygon","coordinates":[[[-118.100,34.100],[-118.090,34.100],[-118.090,34.110],[-118.100,34.110],[-118.100,34.100]]]},
  "properties":{"OBJECTID":1,"COUNTY":"Los Angeles (SIMULATED)","CITY":"Demo City","ZONE_NAME":"DEMO Zone 3 Sector A",
    "ZONE_ID":"zone_3_sector_a","STATUS":"Evacuation Order","EVENT_TYPE":"Wildfire (SIMULATED)",
    "CRITICAL_INFO":"SIMULATION ONLY","PUBLIC_INFO":"SIMULATION ONLY","EDIT_DATE":1792281600000,
    "STATEWIDE_LAST_UPDATED":1792281660000,"GlobalID":"sim-0001"}}]}
```

**`POST /alerts/ingest`** (token): the Calamity agent posts what it fetched, **including failed fetches**.
```json
{"source":{"source_id":"SYNTHETIC_CALOES","source_type":"OFFICIAL_SIMULATION",
           "url":"http://127.0.0.1:8000/demo/feeds/caloes","fetched_at":"2026-10-17T20:02:00Z"},
 "fetch_ok":true,"http_status":200,"error":null,"payload":{"type":"FeatureCollection","features":[…]},
 "idempotency_key":"SYNTHETIC_CALOES:2026-10-17T20:02:00Z"}
```
`source_type`: `OFFICIAL_SIMULATION` (can trigger check-ins and outreach) or `REAL_WORLD` (live Cal OES; display-only).

Response 200:
```json
{"ingest_id":"ingest_004","source_id":"SYNTHETIC_CALOES","source_updated_at":"…","feed_freshness":"FRESH",
 "records_received":2,"records_rejected":[{"source_record_id":"sim-0009","reason":"UNKNOWN_STATUS:Evacuation Advisory"}],
 "new_alerts":[{"alert_id":"alert_001","status":"WARNING","zone_id":"zone_3_sector_b","calamity_type":"WILDFIRE"},
               {"alert_id":"alert_002","status":"ORDER","zone_id":"zone_3_sector_a","calamity_type":"WILDFIRE"}],
 "changed_alerts":[],"canceled_alerts":[],"pending_cancellation":[],
 "affected_cases":[{"case_id":"case_maria_001","resident_id":"resident_001","zone_status":"WARNING","alert_id":"alert_001"},
                   {"case_id":"case_david_002","resident_id":"resident_002","zone_status":"ORDER","alert_id":"alert_002"}],
 "checkins_sent":[{"case_id":"case_maria_001","message_id":"msg_001"},{"case_id":"case_david_002","message_id":"msg_002"}],
 "outreach_orgs":[{"org_id":"eastside_rides_demo","name":"Eastside Accessible Rides (fictional)","agent_address":"agent1q…",
                   "distance_km":4.1,"calamity_types":["WILDFIRE"],"alert_id":"alert_001"},
                  {"org_id":"red_cross_demo","name":"Red Cross (fictional demo chapter)","agent_address":"agent1q…",
                   "distance_km":7.9,"calamity_types":["WILDFIRE","FLOOD","EARTHQUAKE"],"alert_id":"alert_001"}],
 "notify_coordinator":true,"duplicate":false}
```
B's rules:
- **Status:** mapped case-insensitively (`evacuation order`→ORDER, `evacuation warning`→WARNING, `shelter in place`→SHELTER_IN_PLACE, `normal`/`clear to repopulate`→INACTIVE). Unknown strings are rejected and listed, never guessed.
- **Calamity type:** from `EVENT_TYPE` (`wildfire`/`fire`→WILDFIRE, `flood`→FLOOD…); null → `UNKNOWN`. For an `UNKNOWN` type, every approved TRANSPORT org within its radius is eligible for outreach (it can't be filtered by type).
- **Freshness:** from `STATEWIDE_LAST_UPDATED`/`EDIT_DATE` vs `ALERT_STALE_AFTER_SECONDS`.
- **Dedupe:** by source record + version + zone.
- **Cancellation:** only on INACTIVE **or** after missing from 2 consecutive successful ingests (Cal OES rebuild gap).
- **Check-ins:** every fresh ingest offers a check-in to residents inside any active `OFFICIAL_SIMULATION` WARNING/ORDER zone (so people who registered after the alert are included), to residents with `wants_help_contact` and `CHECKIN` consent, keyed `alert:status:resident`. 10 identical ingests → 1 check-in.
- **`outreach_orgs`:** approved orgs offering `TRANSPORT` whose `calamity_types` include the alert's type (or `ANY`), within `service_radius_km` of the zone, sorted by distance, top `OUTREACH_MAX_ORGS` (default 3). Returned only for simulated alerts with affected residents. The Doorstep agent sends an `OutreachRequest` to each listed org's agent.

**`GET /alerts/active`**: normalized alerts:
```json
{"alerts":[{"alert_id":"alert_002","source_id":"SYNTHETIC_CALOES","source_record_id":"sim-0001","status":"ORDER",
  "raw_status":"Evacuation Order","calamity_type":"WILDFIRE","zone_id":"zone_3_sector_a","zone_name":"DEMO Zone 3 Sector A",
  "geometry":{…},"issued_at":"…","updated_at":"…","expires_at":"…","fetched_at":"…","freshness":"FRESH",
  "verification":"OFFICIAL_SIMULATION","can_trigger_checkins":true,"is_simulation":true,"affected_resident_count":1}],
 "awareness":[{"incident_id":"inc_001","calamity_type":"WILDFIRE","point":{"lat":34.115,"lon":-118.085},
               "radius_km":5,"residents_nearby_not_in_zone":0,"note":"Awareness only; not an evacuation zone."}],
 "feeds":[{"source_id":"SYNTHETIC_CALOES","source_type":"OFFICIAL_SIMULATION","last_ingest_at":"…","feed_freshness":"FRESH"}],
 "generated_at":"…"}
```
Live alerts show `verification: OFFICIAL_LIVE_DISPLAY_ONLY`, `can_trigger_checkins: false`.

**`POST /demo/alerts/trigger`** (token): changes the synthetic feed. The Calamity agent's next poll picks it up (`poll_now:true` ingests immediately).
`{"action":"ISSUE","preset":"ZONE_3_WILDFIRE","poll_now":false}`
- `action`: `ISSUE | UPDATE | CANCEL | EXPIRE | FREEZE_FEED | UNFREEZE_FEED`.
- `preset`: `ZONE_3_WILDFIRE` (WARNING over Maria + ORDER over David + an awareness incident point), `ZONE_3_WARNING`, `ZONE_3_ORDER`. Or explicit `zone_id`, `status` (raw Cal OES string), `event_type`, `geometry`, `expires_in_minutes`.
- `FREEZE_FEED` stops `STATEWIDE_LAST_UPDATED` advancing, so the feed goes STALE (Scenario C).
- `CANCEL` = explicit lift: the record stays in the feed with `STATUS: "Normal"`, so it's canceled on the next ingest. `EXPIRE` = the record disappears from the feed, so it's canceled only after 2 consecutive ingests without it.
- `FREEZE_FEED` accepts optional `freeze_age_minutes` to backdate the frozen timestamp, so the demo goes STALE immediately. `UNFREEZE_FEED` resumes.
- Response: `{"action","feed_version","synthetic_feed_url","frozen","poll_result"}`. `GET /demo/feeds/caloes` returns the raw FeatureCollection (no envelope).

**`GET /alerts/{alert_id}/outreach`** (card data): `{"alert_id","orgs":[{"org_id","name","distance_km","asked":3,"available":2,"unavailable":0,"no_reply":1}]}`.

### 5.4 Volunteer outreach (Organization agents ↔ B)

**`POST /orgs/{org_id}/outreach`** (token + `X-Org-Agent`): the org agent starts asking its own volunteers for this alert. B resets those volunteers' availability for this alert to `ASKED` and sends each approved volunteer a simulated SMS (`DOORSTEP DEMO: A simulated wildfire alert… Can you help with accessible transport? Reply YES or NO.`).
`{"alert_id":"alert_001","idempotency_key":"alert_001:outreach:eastside_rides_demo"}`
→ `{"org_id":"eastside_rides_demo","alert_id":"alert_001","asked":[{"volunteer_id":"volunteer_sarah","message_id":"msg_010"}],"skipped":[{"volunteer_id":"volunteer_tom","reason":"VOLUNTEER_NOT_APPROVED"}]}`

Volunteers answer through the simulator (`POST /sim/inbound` from their `phone`, `YES`/`NO`/`SI`). B records the answer against the **current** alert. **Alternatively**, an org agent that collected answers itself posts them:

**`POST /orgs/{org_id}/volunteers/{volunteer_id}/availability`** (token + `X-Org-Agent`)
`{"alert_id":"alert_001","available":true,"responded_at":"…","idempotency_key":"alert_001:avail:volunteer_sarah"}` → `{"volunteer_id":"volunteer_sarah","alert_id":"alert_001","availability":"AVAILABLE"}`. An answer for an older alert → 409 `STALE_AVAILABILITY`. The volunteer's *current* alert is the one outreach last asked about (or the first answer if never asked). Answers for any other alert are stale. Unapproved volunteers → 409 `VOLUNTEER_NOT_APPROVED`. `emergency_contacts[].contact_id` is optional on registration; B assigns `<resident_id>_contact_<n>`.

**`GET /orgs/{org_id}/volunteers?alert_id=alert_001`** (token + `X-Org-Agent`): **only this org's** volunteers, with phone, address, vehicle, capabilities and availability for that alert. The org agent uses it to build its `OutreachResult`.

**Reply deadline for volunteers:** `POST /sim/outreach/{alert_id}/deadline` marks unanswered volunteers `NO_REPLY` (never treated as available).

### 5.5 Cases

**`GET /cases?zone_id=&resident_status=&zone_status=&unresolved=true`** → `{"cases":[{case_id, display_name, zone_id, zone_status, resident_status, communication_status, map, unresolved, next_step, updated_at}]}`

**`GET /cases/{case_id}`**
```json
{"case_id":"case_maria_001","resident_id":"resident_001","display_name":"Maria (synthetic)","alert_id":"alert_001",
 "zone_id":"zone_3_sector_b","zone_status":"WARNING","zone_sources":[{"alert_id":"alert_001","status":"WARNING","freshness":"FRESH"}],
 "preferred_language":"es","resident_status":"PROVIDER_ACCEPTED","communication_status":"REPLIED","needs_confirmed":true,
 "needs":[1,2,4,6],"pet_count":1,"consent":{"CHECKIN":true,"TRANSPORT":true,"DESTINATION":true,"RECOVERY":false},
 "progress_steps":[{"step":"REQUESTED","done":true,"at":"…"},{"step":"PROVIDER_ACCEPTED","done":true,"at":"…"},
                   {"step":"PICKUP_CONFIRMED","done":false,"at":null},{"step":"ARRIVAL_CONFIRMED","done":false,"at":null}],
 "active_assignment":{"assignment_id":"assign_001","org_id":"eastside_rides_demo","volunteer_id":"volunteer_sarah",
   "vehicle_type":"WHEELCHAIR_VAN","assignment_status":"ACCEPTED","eta":{"minutes":18,"label":"Illustrative estimate, not a guarantee"},
   "confirmed_pickup_at":null,"confirmed_arrival_at":null},
 "shelter_assignment":{"org_id":"civic_shelter_demo","site_id":"dest_center_a","assignment_status":"ACCEPTED"},
 "route":{"route_preview_id":"rprev_001","status":"ILLUSTRATIVE_ONLY"},
 "escalations":[],"recovery":{"status":"NOT_REQUESTED","referrals":[]},
 "map":{"color":"yellow","label":"Volunteer accepted (not yet picked up)"},"unresolved":false,
 "next_step":"Awaiting pickup confirmation.","summary_text":"[SIMULATION] Maria (synthetic) | …",
 "timeline":[{"event_id":"evt_001","type":"ALERT_VERIFIED","created_at":"…","evidence":"OFFICIAL_SIMULATION"}, …],"simulated":true}
```
Never includes addresses, phones or free-text replies.

**`POST /cases/{case_id}/responses`** (token): resident reply (also via `/sim/inbound`).
`{"text":"1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.","language":"es","sender":"sim_phone_maria","external_id":"sim_maria_reply_1"}`
→ `response_id, original_text, intent, candidate_needs:[codes], candidate_source (DETERMINISTIC | ASI_ONE_ASSISTED), needs_confirmed, confirmation_question, resident_status, communication_status, next_step, duplicate`. Confirming: `"SI"`/`"YES"` → `needs_confirmed:true` plus `needs`. Unknown sender → 403, case unchanged.

### 5.6 Matching and assignments

**`POST /matches/propose`** (token): the Matching agent asks B to match a resident with an **available volunteer from the org DB** and a **shelter site**.
```json
{"case_id":"case_maria_001","idempotency_key":"case_maria_001:match:v1","create_proposal":true,
 "authorization":"SIMULATED_PREAPPROVED","select":{"volunteer_id":null,"site_id":null}}
```
- `create_proposal:false` = "show suitable volunteers" (evaluation only).
- `select` picks a specific volunteer/site (e.g. the next one after a decline). Otherwise B takes the top-ranked.
- Volunteers who declined this case are excluded.

Eligibility (decision 7 of the plan):
- org approved and offers TRANSPORT;
- volunteer approved and `AVAILABLE` for **this** alert, not reserved;
- resident needs ⊆ `needs_they_can_cater` (code 7 never blocks; code 6 is checked on the shelter);
- seats, wheelchair spaces and pet capacity fit;
- resident not in an ORDER/STALE/UNKNOWN zone;
- route from the volunteer's address doesn't cross an order zone.

Ranking: distance from volunteer to resident, then `volunteer_id`.
- **Availability counts per event:** a YES given for any currently active simulated alert of the same calamity type counts (one wildfire can have several zone records). Answers tied to a canceled alert don't count.
- When the resident's own zone blocks matching (ORDER/STALE/UNKNOWN), every volunteer's `reason_codes` starts with that zone code.
- More 409 codes: `MATCH_PENDING` (a match is still awaiting the volunteer), `ALREADY_ACCEPTED`. If the case was `REQUIRES_COORDINATOR` and a volunteer is later matched, it moves back to `NEEDS_ASSISTANCE`.
Shelter: needs (incl. 6) ⊆ site `features`, beds ≥ 1, site outside order zones, nearest first.

Response (201 when a match is created; 200 for evaluation-only, no match, or a repeated key):
```json
{"case_id":"case_maria_001","alert_id":"alert_001","zone_status":"WARNING",
 "evaluation":{
   "volunteers":{"eligible":[{"org_id":"eastside_rides_demo","volunteer_id":"volunteer_sarah","vehicle_type":"WHEELCHAIR_VAN",
        "distance_km":4.0,"rank":1,"reason_codes":["ORG_APPROVED","VOLUNTEER_APPROVED","AVAILABLE_FOR_THIS_ALERT","NEEDS_COVERED","WHEELCHAIR_OK","TRANSFER_OK","PET_OK","SEATS_OK","OUTSIDE_ORDER_ZONE","ROUTE_AVOIDS_ORDER_ZONES"]}],
     "rejected":[{"org_id":"neighbor_sedans_demo","volunteer_id":"volunteer_joe","vehicle_type":"SEDAN","distance_km":0.8,
        "reason_codes":["NEEDS_NOT_COVERED","NO_WHEELCHAIR_SPACE"],"missing_needs":[1,2]},
       {"org_id":"red_cross_demo","volunteer_id":"volunteer_maya","reason_codes":["NO_REPLY"]}]},
   "shelters":{"eligible":[{"org_id":"civic_shelter_demo","site_id":"dest_center_a","distance_km":6.2,"rank":1,
        "reason_codes":["ORG_APPROVED","STEP_FREE_OK","PET_OK","BEDS_OK","OUTSIDE_ORDER_ZONE"]}],"rejected":[]}},
 "escalation_required":false,"no_match_reason":null,
 "match":{"assignment_id":"assign_001","status":"PROPOSED","reserved":true,
   "org_id":"eastside_rides_demo","org_agent_address":"agent1q…","volunteer_id":"volunteer_sarah","vehicle_type":"WHEELCHAIR_VAN",
   "shelter_org_id":"civic_shelter_demo","shelter_agent_address":"agent1q…","site_id":"dest_center_a",
   "reason_codes":["NEEDS_COVERED","WHEELCHAIR_OK","TRANSFER_OK","PET_OK","OUTSIDE_ORDER_ZONE"],
   "authorization":"SIMULATED_PREAPPROVED","route_status":"ILLUSTRATIVE_ONLY",
   "shared_with_volunteer":{"needs":[1,2,4],"pet_count":1,"language":"es","pickup_area":"zone_3_sector_b (synthetic)"},
   "eta_estimate":{"minutes":18,"label":"Illustrative estimate, not a guarantee"},
   "idempotency_key":"case_maria_001:match:v1"},
 "duplicate":false}
```
- **No match:** HTTP 200, `match:null`, `escalation_required:true`, `no_match_reason` ∈ `ORDER_ZONE | ZONE_STALE | ZONE_UNKNOWN | NO_AVAILABLE_VOLUNTEER | NO_SUITABLE_VOLUNTEER | NO_SHELTER`. Unresolvable transport moves the case to `REQUIRES_COORDINATOR`.
- **Reservation:** creating the match reserves the volunteer atomically. If another case got them first, B moves on to the next eligible volunteer.
- A `select`ed volunteer or site that fails → 409 (`UNSAFE_ZONE`, `ZONE_STALE`, `ALREADY_RESERVED`, `NOT_ELIGIBLE`).
- The pickup point is never in this response.

**`POST /assignments/{assignment_id}/accept`** (token + `X-Org-Agent`): an org agent forwards its volunteer's decision (transport), or a shelter org agent confirms the bed. Both use the same `assignment_id`.
```json
{"org_id":"eastside_rides_demo","volunteer_id":"volunteer_sarah","decision":"ACCEPTED","idempotency_key":"assign_001:accept:volunteer_sarah"}
```
Shelter: `{"org_id":"civic_shelter_demo","site_id":"dest_center_a","decision":"ACCEPTED",…}`.
Response:
```json
{"assignment_id":"assign_001","case_id":"case_maria_001","responding":"volunteer","org_id":"eastside_rides_demo","volunteer_id":"volunteer_sarah",
 "decision":"ACCEPTED","assignment_status":"ACCEPTED","resident_status":"PROVIDER_ACCEPTED",
 "pickup_details":{"pickup_point":"SYNTHETIC: Zone 3 Sector B meeting point 4","resident_phone":"sim_phone_maria"},
 "help_on_the_way_sent":true,"eta":{"minutes":18,"label":"Illustrative estimate, not a guarantee"},
 "next_alternate":null,"next_step":"Shelter confirmation and route preview pending.","duplicate":false}
```
- **Volunteer `ACCEPTED`:** the resident status moves to PROVIDER_ACCEPTED. B sends the resident `DOORSTEP DEMO: A volunteer has accepted and is on the way (simulated). Estimated arrival about 18 minutes. This is an estimate, not a guarantee.` Pickup details go **only** to that org agent.
- **`DECLINED`:** the reservation is released, the resident stays `NEEDS_ASSISTANCE`, and `next_alternate: {"volunteer_id","org_id"}` names the next eligible volunteer (call `matches/propose` with `select`). If none is left → `REQUIRES_COORDINATOR`.
- **Shelter acceptance** does not change the resident status. Arrival requires it.
- A reply to a `CANCELED`/`DECLINED` assignment → 409 `INVALID_TRANSITION`. Wrong org or volunteer → 403. `X-Org-Agent` must equal the body's `org_id`.
- **Volunteer acceptance re-checks the resident's zone.** If an ORDER (or stale data) appeared after the proposal → 409 `UNSAFE_ZONE` / `ZONE_STALE`. A lost reservation → 409 `RESERVATION_LOST`. A shelter with no beds left → 409 `NO_BEDS`.
- `DECLINED` after `ACCEPTED` (volunteer cancels before pickup) → `assignment_status: CANCELED`, resident back to `NEEDS_ASSISTANCE`, `next_alternate` as above.

**`POST /assignments/{assignment_id}/pickup`** (token)
```json
{"evidence":{"type":"VOLUNTEER_AND_RESIDENT_CONFIRMATION","volunteer_confirmed":true,"resident_confirmed":true,
  "caregiver_confirmed":false,"code_verified":true,"source":"SIMULATED","report_id":"pickup_rep_001",
  "confirmations":[{"party":"volunteer","party_id":"volunteer_sarah"},{"party":"resident","party_id":"resident_001"}]},
 "idempotency_key":"assign_001:pickup"}
```
Required: volunteer **and** (resident **or** caregiver/emergency contact). If `confirmations` is given, every `party_id` must match the real participants. A code helps confirm contact; it never proves safety.

**`POST /assignments/{assignment_id}/arrival`** (token)
```json
{"evidence":{"type":"SHELTER_CHECKIN","shelter_org_id":"civic_shelter_demo","site_id":"dest_center_a","shelter_confirmed":true,
  "source":"SIMULATED","report_id":"arrival_rep_001"},"idempotency_key":"assign_001:arrival"}
```
Required: pickup already confirmed, the shelter **accepted**, and a check-in by that shelter (or resident/caregiver + volunteer). `shelter_org_id` and `site_id` must match the accepted shelter. On arrival B releases the volunteer's reservation and asks the resident (simulated SMS) whether they need further help.
Pickup/arrival response: `assignment_id, case_id, assignment_status, resident_status, confirmed_pickup_at, confirmed_arrival_at, map, next_step, duplicate`. Green only after arrival.

### 5.7 Escalation (Escalation agent ↔ B)

**`POST /cases/{case_id}/escalate`** (token) → 201
`{"reason":"ACTIVE_EVACUATION_ORDER_ZONE","idempotency_key":"case_david_002:escalation:v1"}`
`reason` ∈ `ACTIVE_EVACUATION_ORDER_ZONE` (case must be in an ORDER zone), `NO_AVAILABLE_VOLUNTEER`, `NO_SUITABLE_VOLUNTEER`, `VOLUNTEER_TIMEOUT`, `NO_REPLY_AFTER_DEADLINE`, `COORDINATOR_REQUESTED`.
```json
{"escalation_id":"esc_001","case_id":"case_david_002","reason":"ACTIVE_EVACUATION_ORDER_ZONE",
 "recipient":"SIMULATED_AUTHORIZED_RESPONSE_SERVICE","status":"REQUESTED","assistance_confirmed":false,
 "case_summary_for_recipient":{"case_id":"case_david_002","zone_id":"zone_3_sector_a","zone_status":"ORDER","language":"en","needs":[1]},
 "resident_status":"REQUIRES_COORDINATOR","assignment_status":"UNRESOLVED",
 "next_step":"Awaiting simulated authorized service acknowledgment; assistance not confirmed."}
```
`AUTO_ESCALATION_ACK=true` (no Escalation agent running) acknowledges immediately.

**`POST /escalations/{escalation_id}/ack`** (token): `{"status":"ACKNOWLEDGED_REQUEST_ONLY","recipient_agent_address":"agent1q…","idempotency_key":"esc_001:ack"}` → `{"escalation_id":"esc_001","status":"ACKNOWLEDGED_REQUEST_ONLY","assistance_confirmed":false,"resident_status":"REQUIRES_COORDINATOR","assignment_status":"UNRESOLVED","next_step":"…"}`. `assistance_confirmed` is always false.

### 5.8 Post-calamity help (Post-Calamity agent ↔ B)

**`POST /cases/{case_id}/recovery`** (token) → 201. Called after arrival, once the resident says they want further help.
```json
{"consent":{"share_recovery_needs":true,"granted_by":"RESIDENT","granted_at":"…"},
 "help_types":["TEMPORARY_HOUSING","INSURANCE_GUIDANCE"],"idempotency_key":"case_maria_001:recovery:v1"}
```
B matches approved orgs whose `recovery_services` include each help type (nearest first) and creates one referral per help type:
```json
{"case_id":"case_maria_001","referrals":[
   {"referral_id":"ref_001","help_type":"TEMPORARY_HOUSING","org_id":"recovery_housing_demo","agent_address":"agent1q…","status":"REQUESTED",
    "shared_payload":{"referral_id":"ref_001","help_type":"TEMPORARY_HOUSING","language":"es","needs":[1,6],"pet_count":1}},
   {"referral_id":"ref_002","help_type":"INSURANCE_GUIDANCE","org_id":"red_cross_demo","agent_address":"agent1q…","status":"REQUESTED",
    "shared_payload":{"referral_id":"ref_002","help_type":"INSURANCE_GUIDANCE","language":"es"}}],
 "unmatched_help_types":[],"housing_secured":false}
```
- `shared_payload` is exactly what the Post-Calamity agent may forward; it's per help type and minimal.
- `share_recovery_needs:false` → 409 `CONSENT_MISSING`, recorded as `NOT_REQUESTED`, nothing shared.
- B never files claims or applications; `INSURANCE_GUIDANCE` is a referral to a (simulated) helper org.

**`POST /recovery/{referral_id}/respond`** (token + `X-Org-Agent`): `{"org_id":"recovery_housing_demo","decision":"ACCEPTED","evidence":null,"idempotency_key":"ref_001:respond:accepted"}`
- `decision` ∈ `ACCEPTED | DECLINED (→UNRESOLVED) | COMPLETED`.
- `COMPLETED` requires `evidence: {"type":"SIMULATED_SERVICE_CONFIRMED","reference":"…"}`.
- → `{"referral_id":"ref_001","status":"ACCEPTED","housing_secured":false}`. `housing_secured` is true only for a COMPLETED `TEMPORARY_HOUSING` referral with evidence (still simulated).

### 5.9 Road closures (News agent ↔ B)
- **`GET /demo/feeds/news`** → `{"items":[{"item_id":"news_001","source_name":"Fictional Valley Gazette (DEMO)","url":null,"published_at":"…","headline":"Residents report Canyon Rd blocked by debris (DEMO)","body":"…"}]}`
- **`GET /demo/feeds/closures`** (synthetic **official**) → `{"closures":[{"closure_id":"off_001","issuing_authority":"SIMULATED_LA_COUNTY_PUBLIC_WORKS","road_name":"Ridge Ave","status":"CLOSED","published_at":"…","expires_at":"…"}]}`
- **`POST /demo/closures/trigger`** (token): `{"action":"PUBLISH_OFFICIAL"|"LIFT_OFFICIAL"|"PUBLISH_NEWS","road_name":"…","headline":"…","body":"…"}`
- **`POST /closures/ingest`** (token):
```json
{"source":{"source_id":"SYNTHETIC_NEWS","source_type":"NEWS","url":"…","fetched_at":"…"},
 "items":[{"source_item_id":"news_001","published_at":"…","headline":"…","raw_text":"…","extraction_method":"ASI_ONE_EXTRACTION",
   "candidate":{"road_name":"Canyon Rd","claimed_status":"CLOSED","location_text":"near Zone 3"}}],
 "idempotency_key":"SYNTHETIC_NEWS:news_001"}
```
  **B sets `state`; the agent never does:**
  - `OFFICIAL_SIMULATION` + CLOSED → `OFFICIAL_CONFIRMED`; `NEWS` / `REAL_WORLD_CONTEXT` → `UNVERIFIED_REPORT`;
  - contradictory active claims about one segment → `CONFLICTING`; expired or lifted → `EXPIRED`;
  - a gazetteer maps road names to segments; unmapped names are shown but never used for routing.

  → `{"accepted":[{"closure_id":"closure_002","state":"UNVERIFIED_REPORT","segment_id":"seg_canyon_rd"}],"rejected":[],"new_official_closures":[],"notify_coordinator":true}`
- **`GET /closures`** → closures with `state, claimed_status, used_for_routing, sources[{source_type, url, published_at, headline}], expires_at`, plus `"note":"No report does not mean a road is open."`

### 5.10 Routes (Route agent ↔ B ↔ HERE)

**`POST /routes/constraints`** (token): `{"assignment_id":"assign_001","idempotency_key":"assign_001:route:v1"}`
→ OK:
```json
{"route_request_id":"route_001","status":"OK",
 "stops":[{"role":"VOLUNTEER_START","lat":34.095,"lon":-118.110,"label":"Volunteer start (synthetic)"},
          {"role":"PICKUP","lat":34.1012,"lon":-118.0964,"label":"Synthetic pickup area"},
          {"role":"SHELTER","lat":34.089,"lon":-118.070,"label":"Civic Center (fictional)"}],
 "avoid_areas":[{"kind":"ORDER_ZONE","id":"alert_002","geometry":{"type":"Polygon","coordinates":[…]}},
                {"kind":"OFFICIAL_CLOSURE","id":"closure_001","geometry":{"type":"Polygon","coordinates":[…]}}],
 "cautions":[{"closure_id":"closure_002","state":"UNVERIFIED_REPORT","road_name":"Canyon Rd","geometry":{…}}],
 "max_avoid_areas":250,"data_as_of":"…","label":"ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"}
```
Refused → 409 `ROUTE_REFUSED`, `reasons` ∈ `ORDER_ZONE` (a stop is inside an order) `| ZONE_STALE | ZONE_UNKNOWN | TOO_MANY_AVOID_AREAS | ASSIGNMENT_NOT_ACCEPTED`. B refuses rather than truncate. Closure lines are buffered into polygons by B.

**`POST /routes/previews`** (token):
`{"route_request_id":"route_001","provider":"HERE","polyline":{"type":"LineString","coordinates":[…]},"distance_m":9800,"duration_s":1080,"provider_notices":[],"computed_at":"…","idempotency_key":"route_001:preview"}`
(`polyline:null` → `NO_ROUTE_CONFIRMED`)
→ `{"route_preview_id":"rprev_001","status":"ILLUSTRATIVE_ONLY","crosses":[],"cautions_on_path":["closure_002"],"eta":{"minutes":18,"label":"Illustrative estimate, not a guarantee"},"label":"ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"}`
- `REFUSED` if the polyline intersects any ORDER polygon or official closure (listed in `crosses`), or if data went stale.
- On `ILLUSTRATIVE_ONLY`, B updates the case ETA (still an estimate).
- Never described as safe. Directions go to the volunteer's org agent only.

### 5.11 Card data
- **`GET /dashboard/summary`** → `{"counts_by_status":[{"status","count","color","label"}],"unresolved":[{"case_id","display_name","reason","next_step"}],"alerts":{"active_order","active_warning","feed_freshness","last_ingest_at"},"outreach":{"orgs_contacted","volunteers_available","volunteers_no_reply"},"closures":{"official_confirmed","unverified","conflicting"},"generated_at","simulated":true}`
- **`GET /dashboard/cases`** → `{"cases":[{"case_id","display_name","zone_status","resident_status","map","coarse_location":{"lat":34.10,"lon":-118.10},"unresolved","updated_at"}]}`. Coordinates are rounded to 2 decimals.
- Plus `GET /alerts/active`, `GET /alerts/{id}/outreach`, `GET /organizations`, `GET /closures`, `GET /cases/{id}`.

### 5.12 Simulator hooks (B; tests and demo)
- `POST /sim/inbound {sender, text, external_id?, language?}`: routes by sender to a resident (case reply) **or a volunteer** (availability for the current alert). Unknown sender → 403.
- `POST /sim/delivery {message_id, delivered}`.
- `POST /sim/cases/{case_id}/no-reply-deadline`.
- `POST /sim/outreach/{alert_id}/deadline`.
- `GET /sim/messages?case_id=&volunteer_id=`.

## 6. Fetch.ai agent messages (A owns `integrations/fetch_adapter.py`; listed so both sides align)

All carry `schema_version, correlation_id, created_at`, plus `case_id` / `alert_id` / `idempotency_key` where relevant. Agents receive only consent-scoped fields (`shared_with_volunteer`, `shared_payload`, `case_summary_for_recipient`).

| Message | From → To | Key fields | B endpoint involved |
|---|---|---|---|
| `AlertNotification` | Calamity → Doorstep | `ingest_id, new_alerts, affected_cases, outreach_orgs` | `/alerts/ingest` |
| `OutreachRequest` / `OutreachResult` | Doorstep ↔ Organization agent | `alert_id, calamity_type, zone_id` / `asked, available[volunteer_id], unavailable, no_reply` | `/orgs/{id}/outreach`, `/orgs/{id}/volunteers` |
| `MatchRequest` / `MatchResult` | Doorstep ↔ Matching | `case_id, create_proposal, select` / B's match response | `/matches/propose` |
| `AcceptRequest` / `AcceptResponse` | Doorstep ↔ Organization agent (volunteer or shelter) | `assignment_id, volunteer_id or site_id, shared_with_volunteer` / `decision` | `/assignments/{id}/accept` |
| `PickupReport` | Organization agent (volunteer) → Doorstep | `assignment_id, volunteer_id, report_id, code_verified` | `/assignments/{id}/pickup` (+ resident confirmation) |
| `ArrivalReport` | Organization agent (shelter) → Doorstep | `assignment_id, shelter_org_id, site_id, report_id` | `/assignments/{id}/arrival` |
| `ClosureNotification` | News → Doorstep | `new_official_closures, new_reports` | `/closures/ingest` |
| `RouteRequest` / `RouteResponse` | Doorstep ↔ Route | `assignment_id` / `route_preview` | `/routes/constraints`, `/routes/previews` |
| `RecoveryRequest` / `RecoveryResponse` | Post-Calamity ↔ recovery org agent | `referral_id, shared_payload` / `decision, evidence` | `/cases/{id}/recovery`, `/recovery/{id}/respond` |
| `EscalationRequest` / `EscalationAck` | Doorstep ↔ Escalation | `escalation_id, case_summary_for_recipient` / `status` | `/escalations/{id}/ack` |

## 7. Environment variables

| Var | Side | Default |
|---|---|---|
| `DOORSTEP_API_URL` | A | `http://127.0.0.1:8000` |
| `DEMO_AUTH_TOKEN` | both | `change-me-local-demo-token` |
| `SIMULATION_MODE` | B | `true` (backend refuses otherwise) |
| `MONGODB_URI` | B | `mongodb://localhost:27017` |
| `MONGODB_USERS_DB` / `MONGODB_ORGS_DB` | B | `doorstep_users` / `doorstep_orgs` |
| `USE_MONGOMOCK` | B | `false` (`true` in tests and the smoke test) |
| `ALERT_FEED_URL` | A (Calamity) | `${DOORSTEP_API_URL}/demo/feeds/caloes` |
| `ALERT_POLL_INTERVAL_SECONDS` | A (Calamity) | `120` |
| `ALERT_STALE_AFTER_SECONDS` | B | `900` |
| `OUTREACH_MAX_ORGS` | B | `3` |
| `AWARENESS_RADIUS_KM` | B | `5` |
| `AUTO_ESCALATION_ACK` | B | `true` locally; `false` when the Escalation agent runs |
| `USE_LLM_INTENT` | A, B | `false` |
| `ASI_ONE_API_KEY`, `HERE_API_KEY` | A (B for extraction) | never committed |
| `NEWS_POLL_INTERVAL_SECONDS` | A (News) | `120` |

## 8. Migration from v1.0

| v1.0 | v2.0 |
|---|---|
| SQLite, one DB | MongoDB, `doorstep_users` + `doorstep_orgs` |
| Transport/Destination agents send raw offers from their own inventory | Organization agents (one per org) run volunteer outreach; **B matches against org-DB volunteers** |
| `POST /demo/warnings` | `POST /demo/alerts/trigger` + Calamity agent → `POST /alerts/ingest` |
| `/cases/{id}/transport/evaluate`, `/destination/evaluate`, `POST /cases/{id}/assignments` | `POST /matches/propose` |
| `POST /assignments/{id}/acceptance` | `POST /assignments/{id}/accept` (with `X-Org-Agent`) |
| `POST /cases/{id}/escalations` | `POST /cases/{id}/escalate` + `POST /escalations/{id}/ack` |
| `POST /cases/{id}/recovery-referrals` (housing only) | `POST /cases/{id}/recovery` (help types) + `POST /recovery/{id}/respond` |
| boolean needs fields | integer needs codes (§2) |
| `zone_rule` | `zone_status` from polygons |
| `service_status` | `assignment_status` |
| evidence `provider_confirmed` / `DESTINATION_CHECKIN` | `volunteer_confirmed` / `SHELTER_CHECKIN` |

Unchanged: Bearer auth, `X-Correlation-ID`, error shape, `/health`, `/demo/reset`, `GET /cases`, `GET /cases/{id}` (extended), `POST /cases/{id}/responses`, pickup/arrival paths, `/sim/*`, case and resident IDs. **v1 routes are removed in the same PR window as A's client switch.**

## 9. Database documents (B; for reference)

`doorstep_users`:
- `residents`: §5.2 shape, with `_id` = `resident_id`.
- `cases`, `communications`, `assignments`, `escalations`, `recovery_requests`, `alerts`, `closures`, `route_previews`.
- `events`: append-only timeline, `seq` from `counters`.

`doorstep_orgs`:
- `organizations`: §5.2 shape with embedded `volunteers[]`, which add `availability: {alert_id, state, responded_at}` and `reserved_case_id`.
- `provider_events`: reservations/decisions with unique dedupe keys.
- `counters`.

Atomic patterns:
- volunteer reservation = conditional `update_one` (`availability.state == AVAILABLE`, `reserved_case_id == null`);
- acceptance = `find_one_and_update` on the assignment's status;
- partial unique index on accepted assignments per case and service;
- compensating release if a step fails after reservation.

## 10. Seed data (fixed IDs, all fictional)

| Kind | IDs |
|---|---|
| Residents / cases | `resident_001` / `case_maria_001` "Maria (synthetic)", es, `sim_phone_maria`, emergency contact `sim_phone_ana`, Zone 3 Sector B (**WARNING**), needs `[1,2,4,6]`, 1 dog. `resident_002` / `case_david_002` "David (synthetic)", en, `sim_phone_david`, caregiver/emergency contact `sim_phone_david_caregiver`, Zone 3 Sector A (**ORDER**), needs `[1]` |
| Transport orgs | `eastside_rides_demo` (WILDFIRE; `volunteer_sarah`, wheelchair van, caters `[1,2,4,7]`, **the match**) · `neighbor_sedans_demo` (WILDFIRE; `volunteer_joe`, sedan, closer, caters `[4,7]`) · `red_cross_demo` (WILDFIRE/FLOOD/EARTHQUAKE; `volunteer_maya` minivan `[2,4,7,8]`, `volunteer_lee` wheelchair van `[1,2,4,5]`, the eligible alternate if Sarah declines) · `unlisted_vans_demo` (**org not approved**) · `flood_only_demo` (FLOOD only, never contacted for wildfire) |
| Shelter org | `civic_shelter_demo` / site `dest_center_a` (features `[6,4,5,3]`, 12 beds); `red_cross_demo` / `rc_shelter_1` |
| Recovery orgs | `recovery_housing_demo` (`TEMPORARY_HOUSING`), `red_cross_demo` (`TEMPORARY_HOUSING`, `INSURANCE_GUIDANCE`) |
| Alert presets | `ZONE_3_WILDFIRE` (WARNING over Maria, ORDER over David, awareness incident point), `ZONE_3_WARNING`, `ZONE_3_ORDER` |
| Closures | official `Ridge Ave` (blocks Sector B ↔ Zone 4), news report `Canyon Rd` (unverified) |

Coordinates and polygons are fictional, defined in `src/doorstep/demo/seed.py`. Tests include a resident point exactly on a polygon edge.

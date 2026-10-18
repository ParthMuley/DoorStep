# Doorstep Interface Contract — v2.2 (plan revisions 3–6)

Shared between Developer A (Fetch.ai agents, ASI:One, cards, LangGraph) and Developer B (backend, MongoDB, geography, matching).
**Owner: Developer B** (`docs/DOORSTEP_V2_TEAM_PLAN.md` §6). Source: that plan (revision 3) §0–§7, plus the safety rules in `Doorstep_V2_Two_Person_Claude_Code_Plan.md` and `Doorstep_Implementation_Master_Spec.md`. If anything here conflicts with a safety rule, the safety rule wins.

**Status:** v2.1 proposed for plan revision 3 (one Volunteer Network agent; location-first `regions` partner DB). Frozen once A signs off (checkpoint C1). After that, any change bumps `schema_version` (2.2…), goes in a small PR touching only this file, and needs both developers to approve. §11 answers A's review items 1–5. **What changed from v2.0 is in §8; v2.2 (ASI:One linking, self-registration, invites, approval, the 15-minute deadline, hosted maps) is §5.13 and §8c.**

**Everything is synthetic.** Residents, organizations, volunteers, addresses and phone numbers are fictional. All resident- and volunteer-facing text starts with `DOORSTEP DEMO`. Every card shows SIMULATION. Real-world data (live Cal OES feed, real news) is **display-only**: it never triggers check-ins or outreach, never blocks roads, never changes a case.

---

## 1. Conventions

- **Version:** request and response bodies carry `"schema_version": "2.0"` (the payload family; v2.1 adds endpoints and fields but no breaking renames to existing v2.0 bodies), and so do agent messages.
- **IDs:** opaque synthetic strings. Fixed demo IDs are in §10. B generates deterministic sequential IDs (`assign_001`, `esc_001`, `ref_001`, `evt_001`, `alert_001`, `closure_001`, `route_001`), so a reset followed by the same calls gives the same IDs.
- **Time:** UTC ISO-8601 with `Z`. The raw Cal OES payload keeps its epoch-millisecond fields; B converts them.
- **Geometry:** GeoJSON, coordinates **`[longitude, latitude]`**, WGS84. Addresses are stored as `{label, lat, lon}`. All coordinates are fictional.
- **Correlation:** the Doorstep agent creates a `correlation_id` per ASI:One turn and sends it as header `X-Correlation-ID` (a body `correlation_id` is the fallback). Every agent passes it on. B echoes it in the response body, the response header, every timeline event and every error.
- **Idempotency:** every create (`alerts/ingest`, `outreach`, `availability`, `matches/propose`, `accept`, `pickup`, `arrival`, `escalate`, `ack`, `recovery`, `respond`, `closures/ingest`, `routes/*`) takes an `idempotency_key`. Repeating a key returns the original result with HTTP 200 and `"duplicate": true`.
- **Auth (demo gating, not production auth):**
  - All POSTs need `Authorization: Bearer <DEMO_AUTH_TOKEN>`.
  - **Network-acting routes** (volunteer outreach, volunteer availability, assignment accept, recovery respond) also need `X-Agent-Token: <NETWORK_AGENT_TOKEN>`. Only the Volunteer Network agent holds it; a caller with only the demo token can't act for organizations. Mismatch → 403.
  - **Per-org scoping stays in B:** every network write names its `org_id`, and B checks the volunteer, site or referral belongs to that org (otherwise 403 `UNAUTHORIZED`, reason `WRONG_ORG`).
  - GETs are open but sanitized. They never return volunteer locations or phones, resident addresses or phones, or pickup points.
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
| 403 | `UNAUTHORIZED` | missing/wrong `X-Agent-Token` on a network route; volunteer/site/referral not in the named `org_id` (`WRONG_ORG`); wrong volunteer on an assignment; unknown SMS sender; consent not from resident/caregiver |
| 409 | `WRONG_REGION` | a volunteer/site location is not inside the named region's area (`reasons` names the correct region) |
| 409 | `REGION_OVERLAP` | a new region's area overlaps an existing region |
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
- An emergency contact can reply on the resident's behalf, as a caregiver. `emergency_contacts[].contact_id` is optional; B assigns `<resident_id>_contact_<n>`.

**Partner data is location-first (plan rev 3).** `doorstep_partners.regions` holds one document per area, with the orgs active there and only their volunteers and shelter sites in that area (§9). Volunteers are unique: each one belongs to exactly one org and sits in exactly one region. We only ever want the **nearest** available helpers, so an LA fire never contacts an org's SF volunteers.

**`POST /organizations`** (token) → 201 (200 on update): the org's **canonical** record. No volunteers here.
```json
{"organization":{"org_id":"red_cross_demo","name":"Red Cross (fictional demo chapter)",
  "calamity_types":["WILDFIRE","FLOOD","EARTHQUAKE"],"services":["TRANSPORT","SHELTER","RECOVERY_HOUSING","INSURANCE_GUIDANCE"],
  "approved":true,"service_radius_km":40,"recovery_services":["TEMPORARY_HOUSING","INSURANCE_GUIDANCE"]}}
```
→ `{"org_id":"red_cross_demo","approved":true,"region_ids":["la_county:east_valley","la_county:westside","sf:mission"]}`
Updating an org (e.g. approval revoked) updates its copy in every region in the same request.

**`POST /regions`** (token) → 201: define an area. Areas must not overlap (409 `REGION_OVERLAP`).
```json
{"region":{"region_id":"la_county:east_valley","label":"East Valley (synthetic)",
  "center":{"type":"Point","coordinates":[-118.095,34.098]},
  "area":{"type":"Polygon","coordinates":[[[-118.130,34.075],[-118.060,34.075],[-118.060,34.120],[-118.130,34.120],[-118.130,34.075]]]}}}
```

**`POST /regions/{region_id}/orgs/{org_id}/volunteers`** (token) → 201: register a volunteer where they are.
```json
{"volunteer":{"volunteer_id":"volunteer_maya","name":"Maya (synthetic)","phone":"sim_phone_maya",
  "location":{"type":"Point","coordinates":[-118.120,34.080]},"vehicle_type":"MINIVAN","vehicle_seats":4,
  "wheelchair_spaces":0,"pet_capacity":1,"needs_they_can_cater":[2,4,7,8],"approved":true}}
```
→ `{"region_id":"la_county:east_valley","org_id":"red_cross_demo","volunteer_id":"volunteer_maya","approved":true}`
- The org must exist (`POST /organizations`). If it has no entry in this region yet, B adds one, copying the canonical org facts.
- The location must lie inside the region's area. Otherwise → 409 `WRONG_REGION`, with `reasons: ["CORRECT_REGION:<region_id>"]` (or `NO_REGION` if no area covers it).
- `volunteer_id` is unique across all regions (409 `ALREADY_REGISTERED`).
- Availability and reservations are never set at registration.

**`POST /regions/{region_id}/orgs/{org_id}/shelter_sites`** (token) → 201: `{"site":{"site_id":"dest_center_a","name":"Civic Center (fictional)","location":{"type":"Point","coordinates":[-118.070,34.089]},"beds_available":12,"features":[3,4,5,6]}}`. Same location rules as volunteers.

**`POST /regions/{region_id}/orgs/{org_id}`** (token) → 201: declare an org present in a region without volunteers (e.g. a recovery org's local office).

**`GET /organizations`**: sanitized canonical records for cards: `org_id, name, calamity_types, services, approved, recovery_services, region_ids, volunteer_count, shelter_sites (name, beds, features)`. No phones or locations.

**`GET /regions/near`**: areas near an alert, zone or point, nearest first (card data and outreach preview).
Query params: `alert_id=` | `zone_id=` | `lat=&lon=&radius_km=`, plus optional `calamity_type=`, `service=TRANSPORT`.
```json
{"origin":{"alert_id":"alert_001","zone_id":"zone_3_sector_b"},
 "regions":[{"region_id":"la_county:east_valley","label":"East Valley (synthetic)","distance_km":0.0,
   "orgs":[{"org_id":"eastside_rides_demo","name":"Eastside Accessible Rides (fictional)","approved":true,
            "calamity_types":["WILDFIRE"],"services":["TRANSPORT"],"within_service_radius":true,
            "volunteer_count":1,"approved_volunteers":1,"available_for_alert":0}]},
   {"region_id":"la_county:south_valley","distance_km":2.6,"orgs":[…]}]}
```
`distance_km` is from the zone polygon (or point) to the region's area (0 if they touch). Regions beyond the largest service radius of their orgs aren't listed. On real MongoDB this is a `2dsphere` query; tests and mongomock use B's Shapely fallback over the same documents, with identical results.

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
 "outreach_orgs":[{"org_id":"neighbor_sedans_demo","name":"Neighborhood Sedan Volunteers (fictional)",
                   "region_ids":["la_county:east_valley"],"distance_km":0.0,"calamity_types":["WILDFIRE"],"alert_id":"alert_001"},
                  {"org_id":"eastside_rides_demo","name":"Eastside Accessible Rides (fictional)",
                   "region_ids":["la_county:east_valley"],"distance_km":0.0,"calamity_types":["WILDFIRE"],"alert_id":"alert_001"},
                  {"org_id":"red_cross_demo","name":"Red Cross (fictional demo chapter)",
                   "region_ids":["la_county:east_valley","la_county:south_valley"],"distance_km":0.0,
                   "calamity_types":["WILDFIRE","FLOOD","EARTHQUAKE"],"alert_id":"alert_001"}],
 "network_agent_address":"agent1q…",
 "notify_coordinator":true,"duplicate":false}
```
B's rules:
- **Status:** mapped case-insensitively (`evacuation order`→ORDER, `evacuation warning`→WARNING, `shelter in place`→SHELTER_IN_PLACE, `normal`/`clear to repopulate`→INACTIVE). Unknown strings are rejected and listed, never guessed.
- **Calamity type:** from `EVENT_TYPE` (`wildfire`/`fire`→WILDFIRE, `flood`→FLOOD…); null → `UNKNOWN`. For an `UNKNOWN` type, every approved TRANSPORT org within its radius is eligible for outreach (it can't be filtered by type).
- **Freshness:** from `STATEWIDE_LAST_UPDATED`/`EDIT_DATE` vs `ALERT_STALE_AFTER_SECONDS`.
- **Dedupe:** by source record + version + zone.
- **Cancellation:** only on INACTIVE **or** after missing from 2 consecutive successful ingests (Cal OES rebuild gap).
- **Check-ins:** every fresh ingest offers a check-in to residents inside any active `OFFICIAL_SIMULATION` WARNING/ORDER zone (so people who registered after the alert are included), to residents with `wants_help_contact` and `CHECKIN` consent, keyed `alert:status:resident`. 10 identical ingests → 1 check-in.
- **`outreach_orgs`** (plan decision 6):
  1. Geo query from the zone polygon to `regions`, nearest first.
  2. In those regions, keep approved orgs offering `TRANSPORT` whose `calamity_types` include the alert's type (or `ANY`), where the region is within the org's `service_radius_km` of the zone.
  3. Take the closest `OUTREACH_MAX_ORGS` orgs (default 3). `region_ids` lists only that org's regions within its radius: its far-away regions (e.g. SF for an LA fire) are never contacted.

  Returned only for simulated alerts with affected residents. The Doorstep agent sends one `OutreachRequest` for the alert to the **Volunteer Network agent** (`network_agent_address`).

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

### 5.4 Volunteer outreach (Volunteer Network agent ↔ B)

**`POST /alerts/{alert_id}/outreach`** (token + `X-Agent-Token`): start outreach for an alert.
`{"idempotency_key":"alert_001:outreach","max_orgs":3}`
- B picks the regions and orgs as in `outreach_orgs` (§5.3).
- It sets those orgs' approved volunteers **in the selected regions only** to `ASKED` for this alert, replacing older answers.
- It sends each one a simulated SMS on the org's behalf (`DOORSTEP DEMO: A simulated wildfire alert affects … <org> is asking: can you help with accessible transport? Reply YES or NO.`).

Response:
```json
{"alert_id":"alert_001","orgs":[
  {"org_id":"eastside_rides_demo","region_ids":["la_county:east_valley"],"distance_km":0.0,
   "asked":[{"volunteer_id":"volunteer_sarah","message_id":"msg_010"}],"skipped":[]},
  {"org_id":"red_cross_demo","region_ids":["la_county:east_valley","la_county:south_valley"],"distance_km":0.0,
   "asked":[{"volunteer_id":"volunteer_maya","message_id":"msg_011"},{"volunteer_id":"volunteer_lee","message_id":"msg_012"}],
   "skipped":[]}],
 "duplicate":false}
```
- Only simulated, active alerts → else 409 `NOT_SIMULATED` / `ALERT_NOT_ACTIVE`.
- Unapproved volunteers are listed in `skipped` (`VOLUNTEER_NOT_APPROVED`).
- Repeating the idempotency key returns the original.

**Answers.** Volunteers answer through the simulator (`POST /sim/inbound` from their phone, `YES`/`SI`/`NO`), or the network agent posts an answer it collected:

**`POST /alerts/{alert_id}/volunteers/{volunteer_id}/availability`** (token + `X-Agent-Token`)
`{"org_id":"red_cross_demo","available":true,"responded_at":"…","idempotency_key":"alert_001:avail:volunteer_lee"}`
→ `{"volunteer_id":"volunteer_lee","org_id":"red_cross_demo","alert_id":"alert_001","availability":"AVAILABLE","duplicate":false}`
- The volunteer must belong to `org_id` (else 403, `WRONG_ORG`) and be approved (409 `VOLUNTEER_NOT_APPROVED`).
- The volunteer's *current* alert is the one outreach last asked about; answers for any other alert → 409 `STALE_AVAILABILITY` (checked before idempotency).

**`GET /alerts/{alert_id}/outreach`** (open, card data, **updates live** as answers arrive): `{"alert_id","calamity_type","orgs":[{"org_id","name","region_ids","distance_km","asked","awaiting","available","unavailable","no_reply"}]}`. `no_reply` is only non-zero after the deadline below.

**`POST /sim/outreach/{alert_id}/deadline`** (token): unanswered volunteers become `NO_REPLY` (never treated as available).

**`PUT /agents/{role}`** (token) → 200: an agent registers its address at startup, so its seed stays private to A. `{"agent_address":"agent1q…"}`. `role` ∈ `doorstep, calamity_checker, matching, volunteer_network, escalation, post_calamity, news, route`. **`GET /agents`** lists them. B returns `network_agent_address` (and other agents' addresses where relevant) from this registry.

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

**`POST /matches/propose`** (token): the Matching agent asks B to match a resident with an **available volunteer from the nearby regions** and a **shelter site**.
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
   "org_id":"eastside_rides_demo","region_id":"la_county:east_valley","volunteer_id":"volunteer_sarah","vehicle_type":"WHEELCHAIR_VAN",
   "shelter_org_id":"civic_shelter_demo","site_id":"dest_center_a","network_agent_address":"agent1q…",
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

**`POST /assignments/{assignment_id}/accept`** (token + `X-Agent-Token`): the Volunteer Network agent forwards the volunteer's decision (transport) or the shelter's bed confirmation, naming the `org_id`. Both use the same `assignment_id`. B checks the volunteer/site belongs to that org and to this assignment.
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
- **Volunteer `ACCEPTED`:** the resident status moves to PROVIDER_ACCEPTED. B sends the resident `DOORSTEP DEMO: A volunteer has accepted and is on the way (simulated). Estimated arrival about 18 minutes. This is an estimate, not a guarantee.` Pickup details go **only** to the Volunteer Network agent (for the volunteer), never back to Doorstep.
- **`DECLINED`:** the reservation is released, the resident stays `NEEDS_ASSISTANCE`, and `next_alternate: {"volunteer_id","org_id"}` names the next eligible volunteer (call `matches/propose` with `select`). If none is left → `REQUIRES_COORDINATOR`.
- **Shelter acceptance** does not change the resident status. Arrival requires it.
- A reply to a `CANCELED`/`DECLINED` assignment → 409 `INVALID_TRANSITION`. Wrong org or volunteer → 403.
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
B matches approved orgs whose `recovery_services` include each help type, nearest region first and creates one referral per help type:
```json
{"case_id":"case_maria_001","referrals":[
   {"referral_id":"ref_001","help_type":"TEMPORARY_HOUSING","org_id":"recovery_housing_demo","status":"REQUESTED",
    "shared_payload":{"referral_id":"ref_001","help_type":"TEMPORARY_HOUSING","language":"es","needs":[1,6],"pet_count":1}},
   {"referral_id":"ref_002","help_type":"INSURANCE_GUIDANCE","org_id":"red_cross_demo","status":"REQUESTED",
    "shared_payload":{"referral_id":"ref_002","help_type":"INSURANCE_GUIDANCE","language":"es"}}],
 "unmatched_help_types":[],"housing_secured":false}
```
- `shared_payload` is exactly what the Post-Calamity agent may forward; it's per help type and minimal.
- `share_recovery_needs:false` → 409 `CONSENT_MISSING`, recorded as `NOT_REQUESTED`, nothing shared.
- B never files claims or applications; `INSURANCE_GUIDANCE` is a referral to a (simulated) helper org.
- **When:** only after confirmed arrival, or for residents who self-reported `ALREADY_LEFT` / `HAS_PLAN`. Otherwise 409 `INVALID_TRANSITION` (`NOT_YET_EVACUATED`).
- **Consent by SMS:** the arrival message asks whether to share the resident's needs for further help. A `SI`/`YES` reply (resident or caregiver) records RECOVERY consent; `NO` records a decline. The Post-Calamity agent still sends the `consent` object on this call.
- **Which org:** the nearest region first. In it, an approved org whose `recovery_services` include the help type, within that org's `service_radius_km` (ties broken by `org_id`). Each referral shows `org_id`, `org_name`, `region_id` and `distance_km`.
- **Shared fields per help type:** `TEMPORARY_HOUSING` → language, needs ∩ {1,3,4,5,6,8}, `pet_count`; `MEDICAL_EQUIPMENT_REPLACEMENT` → needs ∩ {3,8,9}; `SUPPLIES` → needs ∩ {3,4,5}, `pet_count`; `INSURANCE_GUIDANCE` / `CASEWORK` → language only. Never a name, phone, address or contacts.
- **Asking again** (new idempotency key) reuses open referrals (REQUESTED/ACCEPTED/COMPLETED) for those help types, so there are no duplicates. It skips orgs that already declined that help type. Help types nobody offers nearby are listed in `unmatched_help_types` (HTTP 200 if nothing was created).
- The response also has `recovery_status` (case level: ACCEPTED if any accepted, else REQUESTED, else COMPLETED, else UNRESOLVED).

**`POST /recovery/{referral_id}/respond`** (token + `X-Agent-Token`; the Volunteer Network agent answers for recovery orgs, and `org_id` must be the referral's org): `{"org_id":"recovery_housing_demo","decision":"ACCEPTED","evidence":null,"idempotency_key":"ref_001:respond:accepted"}`
- `decision` ∈ `ACCEPTED | DECLINED (→UNRESOLVED) | COMPLETED`.
- `COMPLETED` requires `evidence: {"type":"SIMULATED_SERVICE_CONFIRMED","reference":"…"}`.
- → `{"referral_id":"ref_001","case_id","help_type","org_id","status":"ACCEPTED","housing_secured":false,"recovery_status","next_alternate":null}`. `housing_secured` is true only for a COMPLETED `TEMPORARY_HOUSING` referral with evidence (still simulated).
- **Transitions:** REQUESTED → ACCEPTED / UNRESOLVED / COMPLETED; ACCEPTED → COMPLETED / UNRESOLVED. Repeating the current decision is idempotent (`duplicate: true`); anything else is 409 `INVALID_TRANSITION`. A wrong `org_id` → 403 `WRONG_ORG`. Missing evidence for COMPLETED → 409 `INSUFFICIENT_EVIDENCE`.
- **DECLINED** → `UNRESOLVED`, with `next_alternate: {"org_id","region_id"}` (the next nearest org for that help type, or null). Request again to refer there.
- The resident gets DEMO messages when a referral is requested, accepted or completed (never "secured" before evidence).

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
  - `extraction_method`: `STRUCTURED_FEED` | `ASI_ONE_EXTRACTION` | `KEYWORD_EXTRACTION` (the agent's offline fallback). It's only a label, and it never changes the state.
  - `claimed_status`: `CLOSED` | `OPEN` | `RESTRICTED` | `UNKNOWN` (`UNCLEAR` is accepted as `UNKNOWN`). An unknown value lands in `rejected` with `UNKNOWN_STATUS:<value>`, and the rest of the batch is still processed.
  - Response: `{"accepted":[{"closure_id","road_name","claimed_status","state","segment_id","display_only"}],"rejected":[{"source_item_id","reason"}],"new_official_closures","notify_coordinator"}`.

  **B sets `state`; the agent never does:**
  - `OFFICIAL_SIMULATION` + CLOSED → `OFFICIAL_CONFIRMED`; `NEWS` / `REAL_WORLD_CONTEXT` → `UNVERIFIED_REPORT`;
  - contradictory active claims about one segment → `CONFLICTING`; expired or lifted → `EXPIRED`;
  - a gazetteer maps road names (and aliases, e.g. "Ridge Avenue") to segments; unmapped names are shown but never used for routing.

  **Exact state rules** (over a road's unexpired claims; one closure record per road, merging all sources):

  | Claims | State | Blocks routes? |
  |---|---|---|
  | any official CLOSED/RESTRICTED | `OFFICIAL_CONFIRMED` (news saying OPEN is counted in `conflicting_reports`) | yes (if the road is mapped) |
  | official OPEN (lifted) + news CLOSED | `CONFLICTING` | no, caution |
  | only news, all CLOSED/RESTRICTED | `UNVERIFIED_REPORT` | no, caution |
  | only news, disagreeing | `CONFLICTING` | no, caution |
  | only news, all OPEN | `UNVERIFIED_REPORT` (claimed OPEN, never "safe") | no |
  | nothing active, or only an official OPEN | `EXPIRED` | no |

  `REAL_WORLD_CONTEXT` items get their own `display_only` records: never mapped, never a block, never a caution. Repeating the same `source_id` + `source_item_id` replaces that claim.

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
Refused → 409 `ROUTE_REFUSED`, `reasons` ∈ `ORDER_ZONE` (a stop is inside an order) `| ZONE_STALE | ZONE_UNKNOWN | TOO_MANY_AVOID_AREAS | ASSIGNMENT_NOT_ACCEPTED`. B refuses rather than truncate (`ROUTE_MAX_AVOID_AREAS`, default 250, HERE's limit). Closure lines are buffered into polygons by B (~30 m each side). The refusal is recorded on the case timeline. The stops are the volunteer's location, the resident's pickup point and the accepted (or proposed) shelter site.

**`POST /routes/previews`** (token):
`{"route_request_id":"route_001","provider":"HERE","polyline":{"type":"LineString","coordinates":[…]},"distance_m":9800,"duration_s":1080,"provider_notices":[],"computed_at":"…","idempotency_key":"route_001:preview"}`
(`polyline:null` → `NO_ROUTE_CONFIRMED`)
→ `{"route_preview_id":"rprev_001","status":"ILLUSTRATIVE_ONLY","crosses":[],"cautions_on_path":["closure_002"],"eta":{"minutes":18,"label":"Illustrative estimate, not a guarantee"},"label":"ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION"}`
- `REFUSED` if the polyline intersects any ORDER polygon or official closure (listed in `crosses`), or if data went stale.
- On `ILLUSTRATIVE_ONLY`, B updates the case ETA (still an estimate).
- **Re-checked against current data:** an order zone or official closure that appeared after the constraints were issued still refuses the line. A stale zone → `REFUSED` (`ZONE_STALE`). HERE notices mentioning a violated avoid area → `REFUSED`. A preview on a refused route request → 409 `ROUTE_REFUSED`.
- `GET /cases/{id}` shows the latest `route: {route_preview_id, status, refusal_reason}`.
- Never described as safe. Directions go to the volunteer's org agent only.

### 5.11 Card data
- **`GET /dashboard/summary`** →
```json
{"counts_by_status":[{"status":"NEEDS_ASSISTANCE","count":1,"color":"red","label":"Assistance needed"}, …all 6 statuses…],
 "unresolved":[{"case_id","display_name","reason","zone_status","next_step"}],
 "alerts":{"active_order","active_warning","active_shelter_in_place","feed_freshness","last_ingest_at"},
 "outreach":{"orgs_contacted","volunteers_asked","volunteers_available","volunteers_awaiting","volunteers_no_reply"},
 "closures":{"official_confirmed","unverified","conflicting","display_only"},
 "recovery":{"requested","accepted","completed","unresolved"},"generated_at","simulated":true}
```
  `unresolved[].reason` is the latest escalation reason, or the case status if it was never escalated.
- **`GET /dashboard/cases`** → `{"cases":[{"case_id","display_name","zone_status","resident_status","map","coarse_location":{"lat":34.10,"lon":-118.10},"unresolved","progress_steps","updated_at"}]}`. Coordinates are rounded to 2 decimals (none for an uncertain geocode); never pickup points, phones or addresses.
- **`progress_steps`** (also on `GET /cases/{id}`): `REQUESTED → PROVIDER_ACCEPTED → PICKUP_CONFIRMED → ARRIVAL_CONFIRMED`, each `{step, done, at, evidence_ref?}`. A step is done only if a timeline event recorded it, the case's current status is at or past it (a canceled volunteer un-does "accepted"), and every earlier step is done. Green is never shown early.
- **`GET /health`** → `{"status","version":"2.1.0","simulation_mode","databases":{"users","partners"},"alerts":{"feed_freshness","last_ingest_at"}}`.
- Plus `GET /alerts/active`, `GET /alerts/{id}/outreach`, `GET /regions/near`, `GET /organizations`, `GET /closures`, `GET /cases/{id}`.

### 5.12 Simulator hooks (B; tests and demo)
- `POST /sim/inbound {sender, text, external_id?, language?}`: routes by sender to a resident (case reply) **or a volunteer** (availability for the current alert). Unknown sender → 403.
- **Resident pickup confirmation (A's item 5):** a resident (or caregiver) texting `PICKED UP` / `RECOGIDO` / `YA ME RECOGIERON` via `/sim/inbound` while a volunteer is ACCEPTED records the resident side of pickup (`RESIDENT_PICKUP_CONFIRMED` on the timeline). After that, `/pickup` only needs the volunteer side (`volunteer_confirmed: true`, from the `PickupReport`). Sending `resident_confirmed: true` in the evidence is still accepted, for demos.
- `POST /sim/delivery {message_id, delivered}`.
- `POST /sim/cases/{case_id}/no-reply-deadline`.
- `POST /sim/outreach/{alert_id}/deadline`.
- `GET /sim/messages?case_id=&volunteer_id=`.

### 5.13 v2.2: ASI:One accounts, deadlines and maps (plan rev 4 §0.4–0.5, rev 5 §00, rev 6 §000)

**Agent tokens** (`X-Agent-Token`, one per role; defaults are placeholders, real values only in `.env` / Render): `DOORSTEP_AGENT_TOKEN`, `ROUTE_AGENT_TOKEN`, `CALAMITY_AGENT_TOKEN`, `NETWORK_AGENT_TOKEN`. A missing or wrong token gets **401**. Routes under the demo token still also need `Authorization: Bearer`.

| Path | Auth | Body → response |
|---|---|---|
| `POST /link` | Bearer + Doorstep token | `{code, asi_one_address}` → `{role, display_name, asi_one_address, linked_at}` + `resident_id, case_id` / `volunteer_id, org_id` / `coordinator_id`. 409 `UNKNOWN_CODE`, `CODE_SPENT` (works once, even from the same address), `ADDRESS_ALREADY_LINKED`, `PERSON_ALREADY_LINKED`. |
| `POST /unlink` | Bearer + Doorstep token | `{asi_one_address}` → `{unlinked: true, role}`; 404 if not linked. The code stays spent (`/demo/reset` reissues demo codes). |
| `POST /register` | Bearer + Doorstep token | `{role: RESIDENT\|VOLUNTEER, asi_one_address, profile, org_id?}` → 201, same shape as `/link`. Resident: `ResidentProfile` fields (`phone` optional), stored with address label `SELF-REGISTERED (demo)` (coordinates only), plus `zone_status`. Volunteer: `Volunteer` fields with `location` (GeoJSON Point); the region is found from the location (409 `NO_REGION`); always `approved: false` until the org approves; returns `region_id`. |
| `POST /organizations/{org_id}/invites` | Bearer | `{volunteer_id, display_name?}` → 201 `{code, role: VOLUNTEER, volunteer_id, org_id, display_name}` (e.g. `NEIGHBOR-4821`), one-time, accepted by `/link`. 409 `WRONG_ORG`. |
| `POST /orgs/{org_id}/volunteers/{volunteer_id}/approve` | Bearer (coordinator) | `{approved: true}` (optional body) → `{approved, changed}`. 409 `WRONG_ORG`. |
| `GET /volunteers/pending?org_id=` | none | volunteers with `approved: false` (`linked` flag, no contact details). |
| `POST /deadlines/sweep` | Bearer + Doorstep or Calamity token | → `{checked_at, deadline_minutes, cases_no_reply, volunteers_no_reply, notify:[{role: COORDINATOR, channel: ASI_ONE, template_id: deadline_summary, text, case_ids}]}`. |
| `PUT /maps/{map_id}` | Route token (no Bearer needed) | raw `image/png` body ≤ 300 KB, `map_id` 24–64 url-safe chars, optional `?assignment_id=` → 201 `{url, expires_at, bytes}`. 415 wrong Content-Type; 409 `IMAGE_TOO_LARGE` / `VALIDATION_ERROR`. |
| `GET /maps/{map_id}.png` | **public** | the PNG, `Cache-Control: private, max-age=3600`, `X-Robots-Tag: noindex`. 404 after `MAP_TTL_HOURS` (24) or once the linked assignment is completed, canceled, declined or unresolved. No listing endpoint. |

**Sender check (plan §0.5.1):**
- `POST /cases/{id}/responses` with the Doorstep token accepts `sender` = the resident's **linked ASI:One address** and treats it as the resident's own contact. A linked address of anyone else → 403 `UNKNOWN_SENDER`. A linked address **without** the Doorstep token → 401 `DOORSTEP_AGENT_TOKEN_REQUIRED`. Senders that aren't ASI:One links (sim phones) keep the v1 contact check.
- `POST /alerts/{id}/volunteers/{vid}/availability` takes an optional `sender`; if present it must be that volunteer's linked address (403 otherwise).

**15-minute reply deadline (plan §0.5.3, `REPLY_DEADLINE_MINUTES`):**
- `GET /cases/{id}` gains `reply_by`; volunteer availability gains `asked_at`, `reply_by`.
- After `reply_by`: a resident still `SENT`/`DELIVERED` → `NO_REPLY_AFTER_DEADLINE`, `unresolved: true`, dashboard reason `NO_REPLY_AFTER_DEADLINE` (never safe, never "no help needed"); a volunteer still `ASKED` → `NO_REPLY` (matching reason code `NO_REPLY`, i.e. not available).
- Applied on reads (`GET /cases/{id}`, `GET /alerts/{id}/outreach`, `/matches/propose`, `/dashboard/*`) and by `/deadlines/sweep`. Late answers still count. No automatic SMS fallback.

**Contact on case views:** `contact: {channel: ASI_ONE|SIM, linked, linked_at}` and `reachability: LINKED_ASI_ONE | SIM_ONLY | NOT_REACHABLE`. GET views never return the ASI:One address.

**Known limitation (plan §0.5.2):** the seeded demo codes (`MARIA-4821`, `DAVID-5932`, `SARAH-7310`, `LEE-6624`, `COORD-1150`) are public because they are in the repo. That's acceptable only because every person is synthetic. A real deployment would issue codes through the partner org and expire them.

## 6. Fetch.ai agent messages (A owns `integrations/fetch_messages.py`; listed so both sides align)

All carry `schema_version, correlation_id, created_at`, plus `case_id` / `alert_id` / `idempotency_key` where relevant. Agents receive only consent-scoped fields (`shared_with_volunteer`, `shared_payload`, `case_summary_for_recipient`).

| Message | From → To | Key fields | B endpoint involved |
|---|---|---|---|
| `AlertNotification`, `PollNow` | Calamity → Doorstep | `ingest_id, new_alerts, affected_cases, outreach_orgs` | `/alerts/ingest` |
| `OutreachRequest` / `OutreachResult` | Doorstep ↔ Volunteer Network | `alert_id` / per org: `asked, awaiting, available, unavailable` | `/alerts/{id}/outreach`, `/alerts/{id}/volunteers/{vid}/availability`, `GET /alerts/{id}/outreach` |
| `MatchRequest` / `MatchResult` | Doorstep ↔ Matching | `case_id, create_proposal, select` / B's match response | `/matches/propose` |
| `AcceptRequest` / `AcceptResponse` | Doorstep ↔ Volunteer Network | `assignment_id, role (VOLUNTEER/SHELTER), org_id, volunteer_id or site_id, shared_with_volunteer` / `decision` | `/assignments/{id}/accept` |
| `ReportRequest` → `PickupReport` / `ArrivalReport` / `ReportUnavailable` | Doorstep ↔ Volunteer Network | `assignment_id, volunteer_id or site_id, report_id` | `/assignments/{id}/pickup`, `/arrival` |
| `ClosureNotification` | News → Doorstep | `new_official_closures, new_reports` | `/closures/ingest` |
| `RouteRequest` / `RouteResponse` | Doorstep ↔ Route | `assignment_id` / `route_preview` | `/routes/constraints`, `/routes/previews` |
| `RecoveryRequest` / `RecoveryResponse` | Doorstep ↔ Post-Calamity | `case_id, help_types, consent` / referrals | `/cases/{id}/recovery` |
| `ReferralRequest` / `ReferralResponse` | Post-Calamity ↔ Volunteer Network (for recovery orgs) | `referral_id, org_id, shared_payload` / `decision, evidence` | `/recovery/{id}/respond` |
| `EscalationRequest` / `EscalationAck` | Doorstep ↔ Escalation | `escalation_id, case_summary_for_recipient` / `status` | `/escalations/{id}/ack` |

## 7. Environment variables

| Var | Side | Default |
|---|---|---|
| `DOORSTEP_API_URL` | A | `http://127.0.0.1:8000` |
| `DEMO_AUTH_TOKEN` | both | `change-me-local-demo-token` |
| `SIMULATION_MODE` | B | `true` (backend refuses otherwise) |
| `MONGODB_URI` | B | `mongodb://localhost:27017` |
| `MONGODB_USERS_DB` / `MONGODB_PARTNERS_DB` | B | `doorstep_users` / `doorstep_partners` |
| `NETWORK_AGENT_TOKEN` | A (Volunteer Network), B | `change-me-network-agent-token` (never committed with a real value) |
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
| `DOORSTEP_AGENT_TOKEN` | A (Doorstep), B | `change-me-doorstep-agent-token` |
| `ROUTE_AGENT_TOKEN` | A (Route), B | `change-me-route-agent-token` |
| `CALAMITY_AGENT_TOKEN` | A (Calamity), B | `change-me-calamity-agent-token` |
| `REPLY_DEADLINE_MINUTES` | B | `15` |
| `MAP_TTL_HOURS` | B | `24` |
| `PUBLIC_BASE_URL` | B | unset; falls back to Render's `RENDER_EXTERNAL_URL`, then the request URL |
| `ROUTE_MAX_AVOID_AREAS` | B | `20` (HERE v8's polygon limit; was 250) |

## 8. Changes from v2.0 to v2.1 (plan revision 3)

| v2.0 | v2.1 |
|---|---|
| `doorstep_orgs.organizations` with embedded volunteers | `doorstep_partners.regions` (area → orgs → their local volunteers and sites) plus canonical `doorstep_partners.organizations` (no volunteers) |
| one Organization agent per org, `X-Org-Agent` header | one Volunteer Network agent; `X-Agent-Token` on network routes; B checks `org_id` membership |
| `POST /organizations` with `volunteers[]`, `POST /organizations/{org_id}/volunteers` | `POST /organizations` (canonical), `POST /regions`, `POST /regions/{region_id}/orgs/{org_id}/volunteers` · `/shelter_sites` · presence |
| `POST /orgs/{org_id}/outreach` | `POST /alerts/{alert_id}/outreach` (B picks regions and orgs) |
| `POST /orgs/{org_id}/volunteers/{vid}/availability` | `POST /alerts/{alert_id}/volunteers/{vid}/availability` with `org_id` in the body |
| `GET /orgs/{org_id}/volunteers` | removed (outreach returns the asked volunteer IDs; counts in `GET /alerts/{id}/outreach`) |
| `outreach_orgs[].agent_address`, `match.org_agent_address`, `shelter_agent_address` | `network_agent_address` + `region_ids` / `region_id` |
| volunteer `address {label,lat,lon}` | volunteer `location` GeoJSON Point (`2dsphere`) |
| — | `GET /regions/near`, `PUT /agents/{role}`, `GET /agents`, resident pickup SMS |

## 8c. Changes from v2.1 to v2.2 (plan revisions 4–6)
- New: `/link`, `/unlink`, `/register`, org invites, volunteer approval, `/volunteers/pending`, `/deadlines/sweep`, `/maps` (§5.13).
- Case view: `contact`, `reachability`, `reply_by`. Availability: `asked_at`, `reply_by`, optional `sender`.
- `/closures/ingest` accepts `KEYWORD_EXTRACTION` and `UNCLEAR` (§5.9).
- `ROUTE_MAX_AVOID_AREAS` default 250 → 20.
- Not built: B-side `notify` lists for check-ins and outreach. A's Doorstep agent composes its own role cards, so only the sweep returns a `notify` list. Add more if A needs them.

## 8b. Migration from v1.0

| v1.0 | v2.0 |
|---|---|
| SQLite, one DB | MongoDB, `doorstep_users` + `doorstep_partners` |
| Transport/Destination agents send raw offers from their own inventory | the Volunteer Network agent runs outreach; **B matches against volunteers in nearby regions** |
| `POST /demo/warnings` | `POST /demo/alerts/trigger` + Calamity agent → `POST /alerts/ingest` |
| `/cases/{id}/transport/evaluate`, `/destination/evaluate`, `POST /cases/{id}/assignments` | `POST /matches/propose` |
| `POST /assignments/{id}/acceptance` | `POST /assignments/{id}/accept` (with `X-Agent-Token`) |
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

`doorstep_partners`:
- `organizations`: canonical org records (`_id` = `org_id`), no volunteers.
- `regions`: one document per area:
```json
{"_id":"la_county:east_valley","label":"East Valley (synthetic)",
 "center":{"type":"Point","coordinates":[-118.095,34.098]},
 "area":{"type":"Polygon","coordinates":[[[-118.130,34.075],[-118.060,34.075],[-118.060,34.120],[-118.130,34.120],[-118.130,34.075]]]},
 "orgs":[{"org_id":"eastside_rides_demo","name":"Eastside Accessible Rides (fictional)","calamity_types":["WILDFIRE"],
   "services":["TRANSPORT"],"approved":true,"service_radius_km":20,"recovery_services":[],
   "volunteers":[{"volunteer_id":"volunteer_sarah","name":"Sarah (synthetic)","phone":"sim_phone_sarah",
     "location":{"type":"Point","coordinates":[-118.110,34.095]},"vehicle_type":"WHEELCHAIR_VAN","vehicle_seats":2,
     "wheelchair_spaces":1,"pet_capacity":1,"needs_they_can_cater":[1,2,4,7],"approved":true,
     "availability":{"alert_id":null,"state":"UNASKED","responded_at":null},"reserved_case_id":null}],
   "shelter_sites":[]}]}
```
- `provider_events`: decisions and reservations with unique dedupe keys. Also `agents` (address registry) and `counters`.

Indexes:
- `2dsphere` on `regions.center` and `regions.area`;
- `regions.orgs.org_id`;
- unique `regions.orgs.volunteers.volunteer_id`.

Atomic patterns (single region document):
- volunteer reservation = conditional `update_one` with `arrayFilters` on `org_id` + `volunteer_id` (`availability.state == AVAILABLE` for the event, `reserved_case_id == null`);
- bed = conditional `$inc` on the site;
- acceptance = `find_one_and_update` on the assignment's status;
- partial unique index on accepted assignments per case and service;
- compensating release if a step fails after reservation.

## 10. Seed data (fixed IDs, all fictional)

| Kind | IDs |
|---|---|
| Residents / cases | `resident_001` / `case_maria_001` "Maria (synthetic)", es, `sim_phone_maria`, emergency contact `sim_phone_ana`, Zone 3 Sector B (**WARNING**), needs `[1,2,4,6]`, 1 dog. `resident_002` / `case_david_002` "David (synthetic)", en, `sim_phone_david`, caregiver `sim_phone_david_caregiver`, Zone 3 Sector A (**ORDER**), needs `[1]` |
| Regions | `la_county:east_valley` (around the demo fire), `la_county:south_valley`, `la_county:westside`, `sf:mission` (San Francisco: far from the LA fire, never contacted for it) |
| East Valley | `eastside_rides_demo` → `volunteer_sarah` (wheelchair van, caters `[1,2,4,7]`, **the match**) · `neighbor_sedans_demo` → `volunteer_joe` (sedan, closest, `[4,7]`) · `red_cross_demo` → `volunteer_maya` (minivan `[2,4,7,8]`) · `unlisted_vans_demo` (**not approved**) → `volunteer_tom` · `flood_only_demo` (FLOOD only) → `volunteer_rina` · `civic_shelter_demo` → site `dest_center_a` (features `[3,4,5,6]`, 12 beds) |
| South Valley | `red_cross_demo` → `volunteer_lee` (wheelchair van `[1,2,4,5]`, eligible alternate if Sarah declines) · `recovery_housing_demo` (presence; `TEMPORARY_HOUSING`) |
| Westside | `red_cross_demo` → site `rc_shelter_1` (features `[4,5,6]`, 30 beds) |
| SF Mission | `red_cross_demo` → `volunteer_sam` (wheelchair van `[1,2,4]`), present to prove a far region is never contacted |
| Alert presets | `ZONE_3_WILDFIRE` (WARNING over Maria, ORDER over David, awareness incident point), `ZONE_3_WARNING`, `ZONE_3_ORDER` |
| Closures | synthetic feeds at reset: official `Ridge Ave` CLOSED (6 h), news report about `Canyon Rd`. Nothing is ingested until the News agent posts them. Fictional roads: `seg_ridge_ave`, `seg_canyon_rd`, `seg_valley_blvd`, `seg_civic_way` (`src/doorstep/demo/roads.py`) |

Coordinates and polygons are fictional, defined in `src/doorstep/demo/seed.py`. Tests include a resident point exactly on a polygon edge.

## 11. Answers to A's contract review (items 1–5, `dev-a-notes.md`)

1. **`X-Org-Agent` was spoofable.** It's replaced. Network routes need `X-Agent-Token` (`NETWORK_AGENT_TOKEN`, held only by the Volunteer Network agent), and B still checks that every volunteer, site or referral belongs to the named `org_id`. With one network agent, per-org tokens aren't needed.
2. **Agent addresses.** `PUT /agents/{role} {"agent_address"}` at agent startup (token); seeds stay private to A. B returns `network_agent_address` in `outreach_orgs` and matches.
3. **Outreach timing.** Confirmed: `GET /alerts/{id}/outreach` is computed live on every call, and `NO_REPLY` appears only after `POST /sim/outreach/{alert_id}/deadline`. Sending `OutreachResult` immediately with `asked` and then polling is the intended pattern.
4. **Demo inputs from ASI:One.** Confirmed: `/sim/inbound` accepts resident, caregiver **and** volunteer phones (volunteers answer YES/SI/NO), and every `/sim/*` hook works with the demo token.
5. **Pickup evidence.** The resident side arrives either by SMS (`PICKED UP` / `RECOGIDO` via `/sim/inbound`, recorded as `RESIDENT_PICKUP_CONFIRMED`, see §5.12) or as `resident_confirmed: true` on `/pickup`. The volunteer side comes from the `PickupReport` (`volunteer_confirmed: true`).

Notes 6–10: agreed. Cards are documented (the A0 blocker is closed). The 8-agent cap is the reason for one network agent. Endpoints land in A's preferred order. The live demo uses local MongoDB in Docker (`scripts/start_mongo.sh`, `MONGODB_URI=mongodb://127.0.0.1:27017`) or Atlas. The timeouts were fixed on A's side.

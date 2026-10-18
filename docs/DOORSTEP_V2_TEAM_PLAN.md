# DOORSTEP V2 — Two-Person Plan (Fetch.ai track) — revision 3

*Shared plan for Developer A and Developer B. Both Claude Code sessions read this file. Change only by PR, agreed by both. Revision 2 (2026-10-17) re-aligned the plan with the team's original idea and switched to MongoDB. **Revision 3 (2026-10-17, proposed by A, pending B's agreement):**
- no agent per organization: one Volunteer Network agent serves all partner orgs;
- the partner database becomes location-first (`region → orgs → volunteers`), so finding the closest help to an evacuation zone is one geo query.

See §0.*

## 0. What changed in revision 3 (and why)

| Change | Why |
|---|---|
| **No Organization agent per org.** One **Volunteer Network agent** handles outreach and acceptance for every partner org in the affected area. | Real deployments have many orgs in many places, and one process plus one Agentverse slot per org doesn't scale. We already hit the 8-agent account cap with 5 orgs. Agents now represent **services**, not tenants. |
| **The partner DB is location-first.** Each `regions` document is keyed by a location ID and holds the orgs active in that region, each with only its volunteers there. GeoJSON fields carry `2dsphere` indexes. | The system's real question is "who can help **near this evacuation zone**?" With location as the document key, that's one indexed `$near` / `$geoIntersects` query instead of a scan of every org. Location IDs are document `_id`s, not dynamic keys inside one document, because MongoDB can't index dynamic keys. |
| The agent count is **8**: Doorstep, Calamity Checker, Matching, Volunteer Network, Escalation, Post-Calamity, News, Route. | Fits the Agentverse account cap, so every agent gets a profile page. |
| The contract moves from v2.0 to **v2.1** for the region and network endpoints (§7). | B owns the contract. A's review items 1–5 in `dev-a-notes.md` still apply where relevant. |

**For:** Developer A (Fetch.ai agents, ASI:One, cards, LangGraph) and Developer B (backend, MongoDB, geography, matching).
**Base documents:** `Doorstep_V2_Two_Person_Claude_Code_Plan.md` + `Doorstep_Implementation_Master_Spec.md`. This plan overrides both on scope, tech stack and next steps; their safety rules still apply.
**Status:** synthetic-data simulation. No real alerts to people, no 911, no real volunteers, never a "safe route". Everything says **SIMULATION / DEMO**.

---

## 1. The idea (end-to-end flow)

**Before a calamity**
1. **Residents register:** address, phone, emergency contacts, needs, and whether they want to be contacted for help.
2. **Organizations register** themselves and their **volunteers per location**. Each registration lands in the **region** where those volunteers are, with the volunteer's location, vehicle type and size, which needs they can handle, and whether they're available to help. An org active in several places appears in each of those regions, with only its local volunteers.

**During a calamity**
3. **Calamity Checker** polls the government feed **every 2 minutes** (Cal OES evacuation zones, which include LA County). It finds the affected **zone polygons** and the calamity type (e.g. wildfire).
4. **Doorstep Help** asks every registered resident **inside the affected zone** (who agreed to be contacted) whether they need help. Same message in their language, simulated SMS.
5. **At the same time**, Doorstep finds the **regions closest to the evacuation zone** with one geo query, and the organizations inside them that handle this calamity type. The **Volunteer Network agent** asks those organizations' volunteers whether they're available (simulated SMS, sent on each org's behalf). Their yes/no answers are saved per alert in the partner (regions) DB.
6. **Matching agent** matches each resident who asked for help to an available volunteer whose capability codes cover all the resident's needs and whose vehicle fits. It also matches a shelter. Closest first, never ranking people.
7. **News agent** reports which roads are blocked or areas inaccessible: **official** closures vs **unverified** news reports.
8. **Route agent** (HERE, adapted from our route-agent code) gives the volunteer an illustrative route: volunteer → resident → shelter, avoiding order zones and official closures.
9. The **volunteer confirms**. The resident is told **"help is on the way" with an estimated arrival time** (marked as an estimate, not a guarantee). This is only said after the volunteer has accepted.
10. **Pickup** and **arrival** are confirmed separately. Green only at arrival.

**After evacuation**
11. Doorstep asks if they need further help. **Post-Calamity agent** takes over: temporary housing, insurance guidance, supplies, etc. It matches recovery organizations and refers with consent. It never files claims or promises housing.

**Safety case (David):** a resident inside an active **evacuation-order** zone never gets an ordinary volunteer. The case is escalated to a simulated authorized service and stays **unresolved**.
**Data-failure case (C):** if the feed goes stale, the zone becomes STALE/UNKNOWN, and matching and routing refuse. Nobody is called safe.

**Radius rule:** check-ins are based on the official **zone polygon**. Nearby help is found by a geo query from the zone polygon (or an incident point's awareness radius) to the **regions** collection. A radius alone never triggers the evacuation flow.

## 2. Tech stack

| Component | Technology | Owner |
|---|---|---|
| AI agents | Fetch.ai uAgents (§4) | A |
| Agent discovery | Fetch.ai Agentverse (mailboxes + profile READMEs for every agent) | A |
| User interaction | ASI:One via Chat Protocol (Doorstep agent is the entry point) | A |
| AI reasoning | ASI:One API (`https://api.asi1.ai/v1`, OpenAI-compatible, tool calling, structured output): intent → tools (A), free-text needs extraction and news extraction (B / News agent), plain summaries (A). **Never** decides eligibility, zones, consent or status | A + B |
| Agent communication | Fetch.ai agent messaging, correlation ID on every hop | A |
| Workflow | LangGraph (durable per-case graph) | A |
| Databases | **MongoDB**: `doorstep_users` + `doorstep_partners`, which holds the location-first `regions` with `2dsphere` indexes. Runs on local MongoDB or Atlas. Tests use `mongomock`, which needs a Shapely fallback for geo queries (see §5). | B |
| Backend | Python + FastAPI (contract v2.0) | B |
| Disaster detection | Cal OES evacuation layer (includes LA County Genasys zones) + synthetic feed in the same format | Calamity agent fetches, B normalizes |
| Zone detection | Shapely (`covers`: a point on the edge counts as inside; ORDER dominates) | B |
| Road closures | News agent + ASI:One extraction; only official closures block roads | A gathers, B classifies |
| Route planning | HERE Routing v8 (adapted from the team's route-agent code) | A agent, B gates and post-checks |
| Notifications | Fetch.ai agent messages + ASI:One; residents and volunteers via B's SMS simulator | A + B |
| Dashboard | ASI:One Interactive Cards (text fallback) | A renders, B supplies data |

**Cut:** Sentry, Photon, Base44, web dashboard, Google Maps, scraping real news sites.

## 3. Where we are now (integrated branch `feat/fetch-orchestration` @ `9ef2738`; plan + contract draft on `feat/backend-geodata`)

| | Done | Changes with revision 2 |
|---|---|---|
| A | Done on `feat/fetch-agents` @ 4f20ddf:<br>• the Doorstep agent drives the full V2 journey live through Agentverse (alert push, outreach, match, approve, accept, pickup, arrival, recovery, David escalation), with cards and ASI:One tool calling<br>• Calamity, Matching, Escalation and Post-Calamity agents built<br>• per-org agents built, then **replaced in rev 3** by one Volunteer Network agent | Still to do: the Volunteer Network agent, the News and Route agents, and the switch to the v2.1 endpoints |
| B | v1.0 API on SQLite: consent, matching, safety gate, evidence states, events, idempotency, simulator, recovery, escalation, Maria/David, 85 tests | Port storage to **MongoDB** (2 DBs). Needs codes. Org/volunteer documents. Volunteer outreach. Alerts + polygons. Matching against org DB volunteers. Closures, routes, card data. Contract v2.0 revision |
| Open issue | 4 of A's agent tests time out on B's machine | check together first |

## 4. Agents (all uAgents on Agentverse, owned by A)

| Agent | Does | Never does |
|---|---|---|
| **Doorstep** (Coordinator + Doorstep Help) | ASI:One entry point (Chat Protocol), ASI:One API tool-calling, LangGraph; triggers resident check-ins (B sends the simulated SMS); renders cards; tells the resident "help is on the way" + ETA only after the volunteer accepts | decide eligibility or safety; claim dispatch |
| **Calamity Checker** | `on_interval(120s)`: fetch feed → `POST /alerts/ingest` → `AlertNotification` (zones, calamity type, affected residents) to Doorstep | interpret status itself; use a radius as an order |
| **Volunteer Network** (one agent for all partner orgs) | **Outreach:** on an `OutreachRequest` for an alert, has B pick the regions near the zone and the matching orgs in them, sends each of their volunteers a simulated "available?" message on the org's behalf, records the answers per alert, and replies with counts per org.<br>**Assignments:** forwards a volunteer's accept/decline and a shelter's bed confirmation.<br>**Journey:** reports pickup (volunteer) and arrival (shelter check-in).<br>**Recovery:** answers referrals for recovery orgs. | rank people; read the residents DB; forward pickup points or phones back to Doorstep |
| **Matching** | calls B's deterministic `matches/propose` and returns the explained result (wrapper; B's code decides) | match with an LLM |
| **News / Road-closure** | polls synthetic news + official-closure feeds; ASI:One extracts candidate `{road, claimed_status}`; posts to `/closures/ingest` with an honest source type | label anything official; treat "no reports" as "open" |
| **Route** (HERE) | gets avoid-areas from B → calls HERE → submits the polyline to B's post-check → returns the illustrative route + ETA or a refusal | say "safe"; use unverified closures as blocks |
| **Post-Calamity** | after arrival + consent: matches recovery orgs by help type (housing, insurance guidance, supplies…), sends a consent-scoped referral, reports accepted/completed | file claims; promise housing |
| **Escalation Simulator** | `ACKNOWLEDGED_REQUEST_ONLY` receipts for order-zone cases | imply responders were dispatched |

Messages (A, `integrations/fetch_messages.py`):
- `AlertNotification`, `PollNow`
- `OutreachRequest/OutreachResult` (per alert; the result lists orgs with asked/available/awaiting)
- `MatchRequest/MatchResult`
- `AcceptRequest/AcceptResponse` (role `VOLUNTEER` or `SHELTER`; carries `org_id`)
- `ReportRequest` → `PickupReport` / `ArrivalReport` / `ReportUnavailable`
- `ClosureNotification`, `RouteRequest/RouteResponse`
- `RecoveryRequest/RecoveryResponse`, `ReferralRequest/ReferralResponse`
- `EscalationRequest/Ack`

All 8 agents are on Agentverse with profiles. All carry `schema_version: "2.0"`, `correlation_id`, `case_id`, and an `idempotency_key` when they create something. Agents receive only consent-scoped fields.

## 5. The two MongoDB databases (B)

**Shared needs codes** (`models/needs.py`, also in the contract). Residents' `needs` and volunteers' `needs_they_can_cater` use the **same integer codes**, so matching is code-to-code:

| Code | Need | Code | Need |
|---|---|---|---|
| 1 | WHEELCHAIR (wheelchair-accessible vehicle) | 6 | STEP_FREE_DESTINATION |
| 2 | TRANSFER_ASSIST (help getting in) | 7 | SPANISH_SPEAKER (communication support, **never** a reason to deny) |
| 3 | OXYGEN_EQUIPMENT | 8 | MOBILITY_AID (walker, cane) |
| 4 | PET | 9 | MEDICAL_EQUIPMENT_SPACE |
| 5 | SERVICE_ANIMAL | 10 | CAREGIVER_RIDES_ALONG |

New codes may be added with a contract bump; codes never change meaning.

**`doorstep_users`** (residents + operational data)
```json
// residents
{"_id":"resident_001","name":"Maria (synthetic)","phone":"sim_phone_maria","language":"es",
 "address":{"label":"SYNTHETIC: Zone 3 Sector B","lat":34.1012,"lon":-118.0964,"geocode_confidence":"HIGH"},
 "emergency_contacts":[{"name":"Ana (synthetic)","phone":"sim_phone_ana","relationship":"daughter"}],
 "needs":[1,2,4,6],"pet_count":1,"wants_help_contact":true,
 "consents":{"CHECKIN":true,"TRANSPORT":true,"DESTINATION":true,"RECOVERY":false},"registered_at":"…"}
```
Other collections: `cases`, `communications`, `assignments`, `escalations`, `recovery_requests`, `alerts`, `closures`, `route_previews`, `events` (append-only timeline, monotonic `seq` from a `counters` collection).

**`doorstep_partners.regions`** (rev 3, location-first: `region → orgs → volunteers`). There is one document per **location** (`_id` = region ID, e.g. a county zone or a fixed geo cell). It holds the orgs active there, each with **only its volunteers in that region**:
```json
{"_id":"la_county:zone_2","label":"Zone 2 (synthetic)",
 "center":{"type":"Point","coordinates":[-118.110,34.095]},
 "area":{"type":"Polygon","coordinates":[[[-118.13,34.08],[-118.09,34.08],[-118.09,34.11],[-118.13,34.11],[-118.13,34.08]]]},
 "orgs":[{"org_id":"eastside_rides_demo","name":"Eastside Accessible Rides (fictional)",
   "calamity_types":["WILDFIRE"],"services":["TRANSPORT"],"approved":true,"service_radius_km":25,
   "volunteers":[{"volunteer_id":"volunteer_sarah","name":"Sarah (synthetic)","phone":"sim_phone_sarah",
     "location":{"type":"Point","coordinates":[-118.110,34.095]},
     "vehicle_type":"WHEELCHAIR_VAN","vehicle_seats":2,"wheelchair_spaces":1,"pet_capacity":1,
     "needs_they_can_cater":[1,2,4,7],"approved":true,
     "availability":{"alert_id":null,"state":"UNASKED","responded_at":null},"reserved_case_id":null}],
   "shelter_sites":[],"recovery_services":[]}]}
```
- **Indexes:** `2dsphere` on `center` and `area`; `orgs.org_id`; `orgs.volunteers.volunteer_id` (unique across regions, so each volunteer is in exactly one region).
- **Find help near an alert:**
  1. Query `regions` whose `area` intersects the zone polygon buffered by `service_radius_km` (or `$near` the zone centroid), nearest first.
  2. Keep the approved orgs with the alert's calamity type and the needed service.
  3. Take their volunteers. Volunteer-to-resident distance comes from each volunteer's `location`.
- **Orgs in several places** appear in several region documents, each with only that region's volunteers. Org-level facts (name, approval) are copied along with the `org_id`. A small `organizations` collection keeps the canonical org record for registration and approval changes.
- **`mongomock`** doesn't support geo operators, so tests use B's Shapely fallback over the same documents, which gives the same results. The live demo uses a real MongoDB (local or Atlas).

Also `provider_events` (reservations, with a dedupe key) and `counters`.

**Atomicity without multi-DB transactions:**
- **Reserve a volunteer:** one conditional `update_one` on the **region** document, using `arrayFilters` on `org_id` + `volunteer_id`. It succeeds only if the volunteer's availability is `AVAILABLE` for this alert and `reserved_case_id == null`, and it sets `reserved_case_id`. Re-running it for the same case is safe.
- **Accept:** a `find_one_and_update` on the assignment, allowed only while its status is still PROPOSED or AWAITING_PROVIDER. A partial unique index stops a second accepted assignment for the same case and service.
- **If acceptance fails after the reservation:** a compensating release frees the volunteer.
- **Counters:** `find_one_and_update($inc)`.
- `mongomock` runs all of these in offline tests.

**Volunteer availability is per alert:** `available_to_help` is reset when a new calamity alert starts outreach. Answers from an older alert are ignored.

## 6. Decisions (both agree before coding)

1. **Contract v2.0 → v2.1** (B owns `docs/interface-contract.md`; v2.0 is still unsigned; revision 3 needs the v2.1 changes in §7 and A's review items in `dev-a-notes.md`). Kept from v1: case/resident IDs, Bearer `DEMO_AUTH_TOKEN` on writes, `X-Correlation-ID` echo, error shape, 409 for rule refusals. After A signs off, any change needs a 2.1 bump and both of you agreeing.
2. **Switch-over in one PR window:** B ships v2, A switches the client, both merge together, and the v1 routes are deleted then.
3. **One code path for real and synthetic alerts:** B serves a synthetic feed in **Cal OES's exact GeoJSON format**. The Calamity agent fetches whichever URL is configured. **Real alerts are display-only**; only simulated alerts start check-ins and outreach.
4. **Deterministic core:** zones, eligibility, consent, states and route acceptance are B's tested code. The LLM proposes text; code decides.
5. **Volunteers live in the location-first partner DB** (rev 3): `region → orgs → volunteers`. There is **no agent per org**; the Volunteer Network agent acts on the orgs' behalf through B's API. Per-org data scoping stays in B: every write names its `org_id`, and B checks the volunteer belongs to that org. For Fetch.ai, independence is shown by the 8 separate service agents.
6. **Which orgs get contacted:**
   1. Geo query from the alert's zone polygon to `regions`, nearest first.
   2. In those regions, keep approved orgs whose `calamity_types` include the alert's type (or `ANY`), whose `services` include TRANSPORT, and that are within their own `service_radius_km`.
   3. Contact the closest `OUTREACH_MAX_ORGS` (default 3).
7. **Matching rule:** volunteer and org approved, `available_to_help == true` for **this** alert, not reserved, the resident's needs ⊆ `needs_they_can_cater` (code 7 never blocks), seats ≥ 1 + companions, wheelchair spaces ≥ 1 if code 1, pet capacity ≥ pet count, the resident outside any ORDER/STALE/UNKNOWN zone, and the route from the volunteer's address doesn't pass through an order zone. Rank by distance, then volunteer ID. Shelter: needs ⊆ site `features`, beds ≥ 1, outside order zones.
8. **Branches:** A `feat/fetch-agents`, B `feat/backend-geodata`. Small PRs into `feat/fetch-orchestration`, merged to `main` at freeze.
9. **Ownership:** A owns `agents/`, `workflows/`, `integrations/{fetch_adapter,agentverse_setup,asi_cards,asi_one_client,here_client}.py`, `tests/integration/`, `pyproject.toml`, `.env.example`, `docs/dev-a-notes.md`, `docs/integration-decisions.md`, agent scripts. B owns `models/`, `services/`, `api/`, `demo/`, `integrations/message_simulator.py`, `tests/unit/`, backend scripts, `docs/interface-contract.md`, `docs/dev-b-notes.md`, `docs/decisions.md`, `README.md`. Dependencies go through A: B needs `pymongo`, `mongomock` (dev), `shapely>=2`, `openai`.

## 7. Contract v2.0 summary (full detail in `docs/interface-contract.md`)

| Path | Purpose |
|---|---|
| `GET /health`, `POST /demo/reset` | health (+ DB, last ingest); reseed (token) |
| `POST /residents` | register a resident (§5 shape) |
| `POST /organizations` | register or update an org's canonical record (approval, services, calamity types) |
| `POST /regions/{region_id}/orgs/{org_id}/volunteers` | *(rev 3)* register volunteers where they are; B places each one in a region by its location |
| `GET /regions/near?zone_id=` or `?lat=&lon=&radius_km=` | *(rev 3)* regions near a zone or point, nearest first, with matching orgs and volunteer counts (card data) |
| `POST /alerts/{alert_id}/outreach` | *(rev 3)* the Volunteer Network agent starts outreach for an alert. B picks the regions and orgs (decision 6), marks their approved volunteers `ASKED`, sends the simulated SMS, and returns asked/skipped per org |
| `POST /alerts/{alert_id}/volunteers/{volunteer_id}/availability` | *(rev 3)* records a volunteer's yes/no for that alert (`org_id`, `available`, `responded_at`). An answer for an older alert → 409 `STALE_AVAILABILITY` |
| `GET /demo/feeds/caloes` | synthetic feed in Cal OES shape |
| `POST /alerts/ingest` | Calamity agent posts the raw feed (and failed fetches) → B normalizes, geofences, sends resident check-ins → returns affected cases + **`outreach_orgs`** (closest matching orgs to contact) |
| `GET /alerts/active`, `POST /demo/alerts/trigger` | normalized alerts (+ awareness radius for incident points); demo control incl. `FREEZE_FEED` |
| `GET /cases`, `GET /cases/{id}` | state, `zone_status`, `progress_steps`, `map`, `summary_text`, timeline |
| `POST /cases/{id}/responses` | resident reply (sender check, dedupe, needs confirmation SI/YES) |
| `POST /matches/propose` | `{case_id, idempotency_key, create_proposal}` → B matches against **available volunteers in the org DB** + a shelter site; returns explained eligible/rejected volunteers and, if possible, a `PROPOSED` match with a volunteer reservation |
| `POST /assignments/{id}/accept` | the Volunteer Network agent forwards the volunteer's or shelter's decision (`org_id` plus `volunteer_id` or `site_id`; B checks they belong to this assignment). The pickup point is released only on volunteer acceptance and never returned to Doorstep |
| `POST /assignments/{id}/pickup`, `/arrival` | evidence (PickupReport + resident confirmation; shelter check-in) |
| `POST /cases/{id}/escalate` → `POST /escalations/{id}/ack` | order-zone escalation; `assistance_confirmed:false` always |
| `POST /cases/{id}/recovery` → `POST /recovery/{id}/respond` | after arrival: consent + help types (`TEMPORARY_HOUSING`, `INSURANCE_GUIDANCE`, `SUPPLIES`, `MEDICAL_EQUIPMENT_REPLACEMENT`…) → matched recovery orgs → referral accepted/completed (completed needs evidence) |
| `GET /demo/feeds/news`, `GET /demo/feeds/closures`, `POST /closures/ingest`, `GET /closures` | news + official closures; B sets OFFICIAL_CONFIRMED / UNVERIFIED_REPORT / CONFLICTING / EXPIRED |
| `POST /routes/constraints`, `POST /routes/previews` | avoid areas (order zones + official closures) and cautions for volunteer → resident → shelter; HERE polyline post-check → ILLUSTRATIVE_ONLY / REFUSED / NO_ROUTE_CONFIRMED + ETA label |
| `GET /dashboard/summary`, `GET /dashboard/cases` | card data |
| `/sim/*` | simulated SMS for residents **and volunteers** (inbound, delivery, deadline) |

States: Assistance `UNKNOWN, NEEDS_ASSISTANCE, PROVIDER_ACCEPTED, PICKUP_CONFIRMED, ARRIVAL_CONFIRMED, REQUIRES_COORDINATOR`; Assignment `PROPOSED, AWAITING_PROVIDER, ACCEPTED, DECLINED, CANCELED, COMPLETED, UNRESOLVED`; Zone `ORDER, WARNING, SHELTER_IN_PLACE, OUTSIDE_KNOWN_ZONES, UNKNOWN, STALE`; Recovery `NOT_REQUESTED, REQUESTED, ACCEPTED, COMPLETED, UNRESOLVED`; Volunteer availability `UNASKED, ASKED, AVAILABLE, UNAVAILABLE, NO_REPLY`.

## 8. ASI:One Interactive Cards (the dashboard)

**A0 blocker:** cards aren't in the public ASI:One docs, and `uagents-core` chat content has only text / resource / metadata / session / stream. Verify the Card Playground spec (hackpack, Fetch.ai mentors) before building. Until then, render the deck as structured text.

Deck (each card has a SIMULATION banner, color + text label, a "data as of / source" footer, and a text fallback):
1. **Alert**: zone polygon status, calamity type, source/time, freshness, residents in zone, nearby (awareness radius).
2. **Operations board**: counts by status, unresolved queue, last poll.
3. **Volunteer outreach**: orgs contacted (calamity type, distance), volunteers asked / available / unavailable / no reply.
4. **Resident case**: progress *Requested → Volunteer accepted → Pickup → Arrival* with evidence times.
5. **Match**: chosen volunteer (vehicle, needs covered as chips) + shelter; rejected volunteers with reasons; *Approve*.
6. **Help on the way**: volunteer accepted, illustrative route summary, ETA "estimate, not a guarantee".
7. **Escalation (David)**: unresolved, receipt-only acknowledgment.
8. **Road conditions**: official closures vs unverified reports vs conflicting.
9. **Route**: illustrative route or refusal reason.
10. **Post-calamity help**: help types requested → orgs matched → referral accepted/completed.
11. **Data health (C)**: STALE feed, refusals.

## 9. Research already done (2026-10-17)

- **Cal OES evacuation layer** (includes LA County Genasys): `https://services.arcgis.com/BLN4oKB0N1YSgvY8/ArcGIS/rest/services/CA_EVACUATIONS_CalOESHosted_view/FeatureServer/0/query?where=1=1&outFields=*&outSR=4326&f=geojson`. Fields `COUNTY, CITY, ZONE_NAME, ZONE_ID, STATUS, EVENT_TYPE, EDIT_DATE, STATEWIDE_LAST_UPDATED`.
  - `STATUS` is free text; the live value seen was "Evacuation Order" while the docs say "EVACUATION ORDER", so normalize case and flag unknown values.
  - Refresh is documented as both 5 and 10 min; features vanish for 15 s–1 min during rebuilds. So cancel only on an explicit NORMAL **or** after 2 consecutive polls missing the record.
  - `EVENT_TYPE` was null live, so the calamity type may need a fallback: `UNKNOWN` type → contact orgs supporting `ANY`/all types.
- **ASI:One API:** OpenAI-compatible, `asi1-mini`, tool calling, structured output.
- **HERE (team route code):** reuse geocode, avoid-polygon buffering and the tool loop. Fix:
  - closures come from B (official only), not user input;
  - **refuse instead of truncating** above the avoid-area limit;
  - secret seed from env;
  - ambiguous geocode → refuse;
  - durable state (`ctx.storage`, not a global dict);
  - wording never "safe" or "clean".
- **Cards:** see §8.

## 10. Developer A — tasks in order

- **A0 — unblock:** verify the cards spec; check the hackpack judging criteria; investigate the 4 timing-out tests with B; add deps (`pymongo`, `mongomock`, `shapely`, `openai`) and env vars (`MONGODB_URI`, `ASI_ONE_API_KEY`, `HERE_API_KEY`, `ALERT_FEED_URL`, poll intervals, agent seeds/ports).
- **A1 — contract v2.0:** switch `backend_client.py` / `coordinator_actions.py` once B's revised contract lands.
- **A2 — agents (8 total, rev 3):**
  - Calamity Checker (done).
  - **Volunteer Network agent** (rev 3): replaces the per-org agents. Runs outreach for all orgs near an alert, forwards acceptances, reports pickup/arrival, and answers recovery referrals.
  - Matching (done).
  - News.
  - Route (adapt the team's HERE code per §9).
  - Post-Calamity (done).
  - Escalation (done).
  - All 8 on Agentverse with profiles, which fits the account's 8-agent cap.
- **A3 — Doorstep flow (LangGraph):** alert → check-ins + parallel volunteer outreach → wait for replies (no busy-waiting; explicit status queries) → match → Volunteer Network agent forwards acceptance → route → "help on the way + ETA" → pickup → arrival → post-calamity offer. Branches: decline → next volunteer; no volunteers → unresolved; order zone → escalation; stale → refusal.
- **A4 — ASI:One:** ASI:One API tool-calling intent with keyword fallback. Commands: start check, operations board, case status, outreach status, approve, confirm pickup/arrival, road conditions, route, recovery, freeze feed.
- **A5 — cards** (§8) on the verified schema.
- **A6 — delivery:** Agentverse URLs, shared ASI:One chat (Maria, David, route, C), video, README Fetch.ai section.

## 11. Developer B — tasks in order

- **B0 — contract:** revise `docs/interface-contract.md` v2.0 for revision 2 and send A the hash.
- **B1 — MongoDB port:**
  - `services/db.py` → Mongo client with two DBs (`MONGODB_URI`, `mongomock` in tests).
  - `services/store.py` keeps its typed-repository interface but over collections.
  - `event_log.py` uses a counters collection.
  - Indexes (partial unique on accepted assignments; unique dedupe keys) and the atomic patterns in §5.
  - Existing services (consent, transitions, verification, intake, templates) are reused unchanged.
- **B2 — registration + needs codes:**
  - `models/needs.py`.
  - Resident documents, plus the **location-first `regions` documents** (§5, rev 3) with `2dsphere` indexes and a Shapely fallback for mongomock.
  - Endpoints: `POST /residents`, `POST /organizations`, `POST /regions/{region_id}/orgs/{org_id}/volunteers`, `GET /regions/near`.
  - Seed (same IDs as rev 2, now placed in regions): Maria (WARNING zone, needs `[1,2,4,6]`), David (ORDER zone, needs `[1]`), and orgs `red_cross_demo` (in two regions), `eastside_rides_demo` (the match: `volunteer_sarah`), `neighbor_sedans_demo` (closer, no wheelchair), `unlisted_vans_demo` (not approved), `flood_only_demo` (wrong calamity type), `civic_shelter_demo`, `recovery_housing_demo`.
- **B3 — alerts + geofencing + outreach list:** synthetic Cal OES feed, `/alerts/ingest` (case-insensitive status, freshness, dedupe, 2-poll cancellation, Shapely `covers`, ORDER dominance, STALE/UNKNOWN), resident check-ins (idempotent per alert and resident), the **region geo query** and `outreach_orgs` selection (decision 6), `POST /alerts/{id}/outreach` and per-alert availability (rev 3), awareness radius for incident points, per-alert availability reset.
- **B4 — matching + states:** decision 7, explained reason codes, volunteer reservation, accept/decline, next volunteer on decline, escalation + ack, Scenario C.
- **B5 — post-calamity:** help types, consent-scoped referral payload, recovery-org matching by `recovery_services`, accepted/completed with evidence.
- **B6 — closures + routes:** feeds, `/closures/ingest` with deterministic states and a road gazetteer; `/routes/constraints` (volunteer → resident → shelter, avoid order zones + official closures, cautions for unverified, refuse if stale or too many areas) and `/routes/previews` post-check.
- **B7 — card data, API, scripts, docs:**
  - `/dashboard/*`, `progress_steps`, `summary_text`.
  - Scenarios A, B, C + outreach + route refusal in `demo/scenarios.py`.
  - `smoke_test.sh` with mongomock or a local Mongo; no Fetch/HERE/ASI:One keys.
  - Update `dev-b-notes.md`, `decisions.md`, README.
  - Spanish templates reviewed by a fluent speaker.

## 12. Checkpoints

| # | A | B | Joint check |
|---|---|---|---|
| C1 | cards spec, hackpack criteria, deps/env, timeouts | contract v2.0 (rev 2) committed | **sign off on the contract** |
| C2 | client on v2.1, Calamity agent, Volunteer Network agent | Mongo port, location-first regions + geo query, registration, ingest + geofence, outreach | alert → check-ins + volunteer outreach near the zone, end to end |
| C3 | Matching, accept via the Volunteer Network agent, cards for match/case | matching, reservation, evidence | **Maria matched, accepted, picked up, arrived in ASI:One** |
| C4 | Escalation + Post-Calamity agents | escalation ack, recovery referrals | **David unresolved; Maria post-calamity referral** |
| C5 | News + Route (HERE) agents, road/route cards | closures, route constraints + post-check, FREEZE_FEED | **route avoids official closure, cautions on unverified, refusal; Scenario C** |
| C6 | all agents on Agentverse, shared chat, video | README, smoke, reset, Spanish review | **freeze → merge to `main` → rehearse from reset** |

**No-wait rule:** A tests against B's real app in-process (mongomock-backed); B tests API-only with a fake agent caller. HERE and ASI:One are mocked on both sides.

## 13. Tests

- **B (offline, mongomock):**
  - polygon inside / outside / **edge**; overlapping zones; feed canceled/expired/stale/malformed/empty/unavailable;
  - 10 identical ingests → 1 check-in and 1 outreach per volunteer;
  - rebuild gap; fire incident or radius ≠ order;
  - regions found by geo query, nearest first (including a point on the zone polygon's edge, and radius limits); only approved orgs with the matching calamity type are selected; an org in two regions contributes only that region's volunteers; a volunteer can't be recorded under the wrong org;
  - stale availability from an old alert ignored; needs ⊆ capabilities (code 7 never blocks); wheelchair, pet, seat and oxygen limits;
  - volunteer reserved once (concurrent accepts → one wins); decline → next volunteer;
  - news never official; official closure avoided; route crossing an order zone refused;
  - recovery without consent shares nothing; completed needs evidence;
  - plus all existing invariants (acceptance ≠ pickup ≠ arrival, silence ≠ danger, failed delivery ≠ no reply, ack ≠ assistance, unknown sender).
- **A (integration):** each agent pair over Bureau; Volunteer Network outreach for an alert; decline → next volunteer; restart mid-workflow without duplicates; correlation ID across hops; cards + text fallback; LLM never changes a status string.
- **Together:** Maria, David, route, Scenario C from ASI:One.

## 14. Demo (3 min)

0:00 problem → 0:15 Calamity agent detects simulated wildfire zones (Alert card) → 0:30 check-ins + Volunteer Network outreach to the closest fire-capable orgs, found by location (Outreach card); volunteers answer → 0:50 Maria replies in Spanish; needs confirmed → 1:05 Matching agent: Sarah's wheelchair van matched, closer sedan rejected (Match card) → 1:15 News agent: official closure + unverified report → Route agent: HERE route avoiding the order zone and the closure (Route card) → 1:30 "help is on the way, ETA ~18 min (estimate)" → pickup → arrival (green) → 1:50 Post-Calamity: housing + insurance guidance referral → 2:05 David: order zone, escalation receipt only, unresolved → 2:20 freeze feed: STALE, refusals → 2:35 Agentverse agents + shared chat → 2:50 limits: simulation, partner-led future.

## 15. Fetch.ai submission checklist

- [ ] Doorstep agent chattable in ASI:One; Agentverse URLs + profiles for every agent
- [ ] Real agent messages: alerts, outreach, matching, acceptance, pickup/arrival, closures, routes, recovery, escalation
- [ ] ASI:One API for intent and extraction (never safety), documented
- [ ] Interactive Cards on the verified schema (or a documented fallback)
- [ ] Public ASI:One shared chat: Maria, David, route, Scenario C
- [ ] README (setup incl. MongoDB, architecture, agent list, simulation/safety statement); demo video + backup
- [ ] Synthetic people, orgs, volunteers and addresses only; real feed display-only; every card says SIMULATION

## 16. Prompts for each Claude Code session

**Developer A:**
> You are Developer A on Doorstep V2 (Fetch.ai track; Fetch-first everywhere). Read `docs/DOORSTEP_V2_TEAM_PLAN.md` (this plan, revision 3), `docs/interface-contract.md` (v2.1 once B commits it), and the two spec documents; this plan wins on scope. Work on `feat/fetch-agents` in A-owned files only (§6.9). Do A0 first (verify the ASI:One Interactive Cards spec from official sources before building cards). Then switch the backend client to contract v2.0 and build the agents in §4: Doorstep, Calamity Checker, one Volunteer Network agent for all partner orgs (no agent per org), Matching, News, Route (adapt the team's HERE code with the §9 fixes), Post-Calamity, Escalation. Add the LangGraph flow (§10 A3), ASI:One API tool-calling intent with keyword fallback, and the card deck (§8) with text fallback. The LLM never decides eligibility, zones, consent or status. Never invent endpoints, MCP commands or card schemas. Everything simulated and DEMO-labeled. Report commit hashes, payloads, agent URLs and test results at each checkpoint (§12).

**Developer B:**
> You are Developer B on Doorstep V2 (Fetch.ai track). Read `docs/DOORSTEP_V2_TEAM_PLAN.md` (revision 3), `docs/interface-contract.md`, and the two spec documents. Work on `feat/backend-geodata` in B-owned files only (§6.9). First revise the contract to v2.1 for revision 3 (location-first regions, `/regions/near`, `/alerts/{id}/outreach`, network accept) and send A the hash. Then finish MongoDB storage (two DBs, location-first `regions` documents with 2dsphere indexes + Shapely fallback, §5 shapes, atomic conditional updates, mongomock tests), add needs codes and registration, the Cal-OES-shaped synthetic feed with `/alerts/ingest` + Shapely geofencing + STALE/UNKNOWN + outreach-org selection, volunteer availability per alert, matching against volunteers found by region geo query, with reservation, escalation, post-calamity referrals, closures with deterministic states, route constraints + HERE polyline post-check, card data, and Scenarios A/B/C in API-only tests and the smoke test (no Fetch/HERE/ASI:One keys). Real feed data is display-only. Missing or stale data never means safe.

# DOORSTEP V2 — Two-Person Plan (Fetch.ai track, Fetch-first everywhere)

*Shared plan for Developer A and Developer B. Both Claude Code sessions read this file. Change it only by PR, agreed by both. Last updated 2026-10-17.*

**For:** Developer A (Fetch.ai agents, ASI:One, cards, LangGraph) and Developer B (backend, data, geography, matching).
**Base documents:** `Doorstep_V2_Two_Person_Claude_Code_Plan.md` + `Doorstep_Implementation_Master_Spec.md`. **This plan overrides both on sponsor scope, tech stack and next steps.** All safety rules from both still apply.
**Status:** synthetic-data simulation. No real alerts to people, no 911, no real volunteers, never a "safe route". Every screen and card says **SIMULATION / DEMO**.

---

## 1. Goal

**Win the Fetch.ai ASI:One Agent Challenge by making Fetch.ai the whole product surface.** Every independent party is a uAgent on Agentverse. Every step happens inside ASI:One. ASI:One Interactive Cards **are** the dashboard. ASI:One API does the language work, under deterministic safety rules.

A fresh user, entirely inside ASI:One, can:
1. see the Calamity Checker agent detect a (simulated) official evacuation polygon,
2. see affected residents from geofencing,
3. watch independent provider agents send offers, with reasons shown on cards,
4. approve on a card → provider agent accepts → pickup → arrival (green only on arrival) → recovery agent accepts the referral,
5. see David blocked in an order zone, the escalation agent acknowledging receipt only, and the case **unresolved**,
6. see the News agent report road closures, each labeled **official-confirmed** or **unverified** with source and time,
7. ask the Route agent for an illustrative HERE route that avoids order zones and **official** closures, shows a caution for unverified reports, or refuses,
8. freeze the feed and see `STALE`, with the system refusing to call anything safe.

**Cut:** Sentry, Photon, Base44, the web dashboard (replaced by cards), misinformation scoring, scraping real news sites.

## 2. Tech stack (agreed)

| Component | Technology | Owner | Note |
|---|---|---|---|
| AI agents | Fetch.ai uAgents | A | 8 agents (§4) |
| Agent discovery | Fetch.ai Agentverse | A | mailboxes + profile READMEs for every agent |
| User interaction | ASI:One (Chat Protocol) | A | Coordinator is the entry point |
| AI reasoning | ASI:One API (`https://api.asi1.ai/v1`, OpenAI-compatible, tool calling, structured output) | A + B | intent → tool calls (A); Spanish free text → candidate needs (B); plain-language summaries (A). **Never** eligibility, zone, consent or state |
| Agent communication | Fetch.ai agent messaging | A | typed `Model` messages, correlation IDs on every hop |
| Workflow | LangGraph | A | durable per-case graph |
| Databases | SQLite (2 files; Postgres-ready schema) | B | residents/cases + organizations/volunteers |
| Backend | Python + FastAPI | B | contract 2.0 |
| Disaster detection | Cal OES aggregation layer (includes LA County Genasys zones) + synthetic feed in the same format | A agent fetches, B normalizes | §8 |
| Evacuation-zone detection | Shapely | B | `covers` (edge = inside), ORDER dominance |
| Road closures / news | News uAgent: synthetic news + official-closure feeds; ASI:One API extraction (+ optional ASI:One web search, display-only) | A agent gathers, B classifies + maps to roads | only official-confirmed closures block roads |
| Route planning | HERE Routing v8 | A agent calls HERE, B gates + post-checks | illustrative only, refusal rules |
| Notifications | Fetch.ai agent messages + ASI:One | A | ASI:One can't push, so the user polls with status queries/cards; residents are simulated |
| Dashboard | ASI:One Interactive Cards | A renders, B supplies view data | text fallback always |

## 3. Where we are now (integrated branch `feat/fetch-orchestration` @ `9ef2738`)

| | Done | Not done |
|---|---|---|
| A | Coordinator on Chat Protocol in ASI:One; Transport + Destination agents with their own inventory; all three auto-registered as Agentverse mailboxes (live); `DoorstepBackend` client; "start check / status / show suitable providers" against B's real backend | propose → arrival → recovery, escalation, LangGraph, 4 new agents, ASI:One API, cards |
| B | Contract v1.0 API, consent, deterministic matching vs partner registry, safety gate, evidence state machine, event timeline, idempotency, SMS simulator, recovery, escalation, Maria/David, scripts, 85 tests | V2: two DBs, enrollment, alert ingest + geofence, stale/unknown, route gating, card view data, V2 paths |
| Issue | 4 of A's agent tests time out on B's machine (`test_no_case_before_warning`, `test_status_uses_backend_summary`, `test_provider_can_decline`, +1) | check together first |

## 4. Agents (8 uAgents on Agentverse, all owned by A)

| Agent | Talks to | Does | Never does |
|---|---|---|---|
| **Coordinator** | ASI:One user, all agents, B | Chat Protocol, ASI:One API intent/tool-calling, LangGraph, renders cards | decide eligibility or safety; claim dispatch |
| **Calamity Checker** | Cal OES / B's synthetic feed, B, Coordinator | `on_interval(120s)`: fetch feed → `POST /alerts/ingest` → on new/changed verified alerts send `AlertNotification` to Coordinator | interpret status itself; treat a fire perimeter as an order |
| **Transport Provider** | Coordinator | own vehicle inventory, offers, accept/decline, `PickupReport` | read B's DB |
| **Destination Provider** | Coordinator | own site inventory, offers, accept/decline, `ArrivalReport` (check-in) | claim a bed without accepting |
| **Recovery Provider** | Coordinator | own caseworker capacity; consent-scoped referral; accept / complete | eligibility or medical decisions |
| **Escalation Simulator** | Coordinator | `ACKNOWLEDGED_REQUEST_ONLY` receipts | imply responders were dispatched |
| **News / Road-closure** | synthetic news + official-closure feeds, ASI:One API, B, Coordinator | `on_interval`: fetch items → ASI:One API structured output extracts *candidate* `{road, claimed_status, location_text, published_at}` from article text → `POST /closures/ingest` with source type → `ClosureNotification` to Coordinator. Optional ASI:One web search for real-world context, sent as `REAL_WORLD_CONTEXT` (display only) | decide a report is true; mark anything official; treat "no reports" as "road open" |
| **Route Planner** | Coordinator, B, HERE | gets avoid-areas (order zones + official closures) and cautions (unverified reports) from B → calls HERE → B post-checks → returns illustrative preview or refusal | ever say "safe" |
| *(P1)* **Resident Phone Simulator** | Coordinator | simulated resident phones as an agent (Maria replies in Spanish) | message real people |

Messages (A, `integrations/fetch_adapter.py`): existing Offer/Accept messages plus `AlertNotification`, `ClosureNotification`, `PickupReport`, `ArrivalReport`, `RecoveryRequest/Response`, `EscalationRequest/Ack`, `RouteRequest/RouteResponse`. All carry `schema_version: "2.0"`, `correlation_id`, `case_id`, `idempotency_key` where they create anything. Providers receive only consent-scoped fields.

## 5. ASI:One Interactive Cards — the dashboard

**Status:** cards are **not in the public ASI:One docs** (docs.asi1.ai), and the installed `uagents-core` chat protocol has only `text`, `resource` (URI + mime metadata), `metadata` (string dict), session and stream content. **A0 blocker:** find the Card Playground / hackpack card spec (Fetch.ai hackpack, ASI:One developer platform, Fetch.ai mentors at the event) and confirm (a) the payload format, (b) how it's carried (likely `metadata`/`resource` content), (c) whether buttons send a follow-up chat message. Build only to the verified schema; until then, render the same deck as structured markdown text.

**Card deck** (every card has a SIMULATION banner, color **and** text label, and a "data as of <time>, source <x>" footer, plus a plain-text fallback):
1. **Alert card**: zone, status (ORDER / WARNING), source + updated time, freshness badge (FRESH/STALE), affected-resident count. Action: *Show affected residents*.
2. **Operations board** (the "dashboard"): counts per status (red/yellow/blue/green/black/gray + labels), unresolved queue, last poll time. Actions: *Open Maria*, *Open David*.
3. **Resident case card**: status chip, progress stepper *Requested → Provider accepted → Pickup → Arrival*, each with an evidence timestamp, communication status, next step. Actions depend on state.
4. **Match proposal card**: ranked eligible providers with reason chips (`WHEELCHAIR_OK`, `PET_OK`…), rejected providers with reasons (the closer sedan: `NOT_WHEELCHAIR_ACCESSIBLE`), destination. Action: *Approve simulated arrangement*.
5. **Journey update card**: provider accepted (illustrative ETA, "not a guarantee") → pickup (blue) → arrival (green).
6. **Escalation card (David)**: black, "UNRESOLVED — assistance not confirmed", receipt-only acknowledgment, coordinator owns follow-up.
7. **Recovery card**: consent asked → referral requested → accepted ("housing not secured") → completed (only with evidence).
8. **Road-conditions card**: closure reports grouped as **Official confirmed** (blocks routes) / **Unverified reports** (caution only) / **Conflicting** / **Expired**, each with source, published time and raw headline. Footer: "No report ≠ road open."
9. **Route preview card**: HERE distance/time, avoided zones and official closures, cautions for unverified reports on the path, "ILLUSTRATIVE ROUTE ONLY — NOT FOR LIVE EVACUATION", or a refusal with the reason (`ORDER_ZONE`, `STALE_DATA`, `NO_ROUTE_CONFIRMED`).
10. **Data-health card (Scenario C)**: feed frozen → `STALE`, matching and routing refused, nobody marked safe.

B supplies card-ready data so A only does layout: `GET /dashboard/summary`, `GET /cases/{id}` (adds `progress_steps`, `map{color,label}`, `summary_text`), `GET /alerts/active`, `matches/propose` results, route results.

## 6. Decisions (both agree before coding)

1. **Contract 2.0 = V2 endpoint names** (§7). Kept from v1: IDs `case_maria_001`/`case_david_002`/`resident_001`/`resident_002`, `Authorization: Bearer $DEMO_AUTH_TOKEN` on writes, `X-Correlation-ID` echo, error shape `{schema_version, error, detail, correlation_id, reasons}`, 409 for rule refusals. **B owns `docs/interface-contract.md` v2.0**; later changes require a 2.1 bump and both of you agreeing.
2. **Switch-over in one PR window:** B ships v2, A switches the client, both merge together, and the v1 routes are deleted then.
3. **One code path for real and synthetic alerts:** B serves the synthetic feed **in Cal OES's exact GeoJSON format** (`GET /demo/feeds/caloes`). The Calamity agent fetches either URL (`ALERT_FEED_URL`). B's `/alerts/ingest` normalizes both identically. **Real alerts are display-only**: only `OFFICIAL_SIMULATION` alerts start check-ins.
4. **Deterministic core:** zone status, eligibility, consent, state transitions and route acceptance are B's tested code. The ASI:One API proposes (intent, candidate needs, summaries); code decides.
5. **Inventory vs registry:** provider agents own live availability. B's organizations DB is the partner approval registry (orgs, volunteers, registered capabilities). An offer may never exceed what's registered.
6. **Branches:** A `feat/fetch-agents`, B `feat/backend-geodata`, both from `9ef2738`. Small PRs into `feat/fetch-orchestration`, merged to `main` at freeze.
7. **Ownership:** A owns `agents/`, `workflows/`, `integrations/{fetch_adapter,agentverse_setup,asi_cards,asi_one_client,here_client}.py`, `tests/integration/`, `pyproject.toml`, `.env.example`, `docs/dev-a-notes.md`, `docs/integration-decisions.md`, agent scripts. B owns `models/`, `services/`, `api/`, `demo/`, `integrations/message_simulator.py`, `tests/unit/`, backend scripts, `docs/interface-contract.md`, `docs/dev-b-notes.md`, `docs/decisions.md`, `README.md`. Never edit the other's files. Dependencies go through A (B needs `shapely>=2` and `openai` (client for ASI:One API) now).

## 7. Contract 2.0 (B implements, A calls)

| Path | Purpose |
|---|---|
| `GET /health` | + version, last ingest time, feed freshness |
| `POST /demo/reset` | reseed (token) |
| `POST /residents`, `POST /organizations`, `POST /volunteers` | enrollment (synthetic address + lat/lon, needs, per-purpose consents; org approval, service areas, nested vehicles/sites) |
| `GET /demo/feeds/caloes` | *(addition)* synthetic feed in Cal OES GeoJSON shape (what the Calamity agent fetches in demo) |
| `POST /alerts/ingest` | *(addition)* Calamity agent posts the raw feed payload + source + fetched_at → B validates, normalizes, dedupes, geofences → returns new/changed/canceled alerts + affected cases + check-ins sent |
| `GET /alerts/active` | normalized alerts, provenance, `FRESH/STALE`, zone status |
| `POST /demo/alerts/trigger` | demo control on the synthetic feed: `ISSUE/UPDATE/CANCEL/EXPIRE/FREEZE_FEED` (the next agent poll picks it up; `poll_now` option for tests) |
| `GET /cases`, `GET /cases/{id}` | state + `zone_status`, alert provenance, `progress_steps`, `map`, `summary_text` |
| `POST /cases/{id}/responses` | resident reply; deterministic + optional ASI:One extraction; needs require SI/YES confirmation |
| `POST /matches/propose` | `case_id, transport_offers, destination_offers, idempotency_key, create_proposal` → per-offer `reason_codes` + match result (`assignment_id, provider_id, volunteer_id, status: PROPOSED, authorization, route_status`) |
| `POST /assignments/{id}/accept` | provider decision (transport or destination provider, same id); pickup point released only on transport acceptance |
| `POST /assignments/{id}/pickup`, `/arrival` | evidence (forwarded `PickupReport`/`ArrivalReport` + resident confirmation) |
| `POST /cases/{id}/escalate` → `POST /escalations/{id}/ack` | request, then the escalation agent's receipt; `assistance_confirmed:false` always |
| `POST /cases/{id}/recovery` → `POST /recovery/{id}/respond` | consented referral, then the recovery agent's `ACCEPTED/UNRESOLVED/COMPLETED` |
| `GET /demo/feeds/news`, `GET /demo/feeds/closures` | *(addition)* synthetic news articles and a synthetic **official** closure feed (driven by `/demo/closures/trigger`) |
| `POST /closures/ingest` | *(addition)* News agent posts items `{source_id, source_type: OFFICIAL_SIMULATION / NEWS / REAL_WORLD_CONTEXT, url, published_at, raw_text, extracted candidate}` → B maps road names to synthetic road segments, sets the state deterministically, dedupes, expires |
| `GET /closures` | closure records with provenance and state `OFFICIAL_CONFIRMED / UNVERIFIED_REPORT / CONFLICTING / EXPIRED` (card data) |
| `POST /routes/constraints` | *(addition)* origin/destination case IDs → avoid polygons (active orders + **official-confirmed** closures), cautions (unverified/conflicting reports), freshness, or refusal (`ORDER_ZONE`, `STALE_DATA`, `UNKNOWN_ZONE`) |
| `POST /routes/previews` | *(addition)* Route agent submits the HERE polyline → B Shapely post-check (no order-zone crossing, data still fresh) → `ILLUSTRATIVE_ONLY` or `REFUSED`; recorded on the timeline |
| `GET /dashboard/summary`, `GET /dashboard/cases` | card data: counts, unresolved queue, sanitized locations (no pickup points) |
| `/sim/*` | B test hooks: inbound SMS, delivery, reply deadline |

States (V2 §4): Assistance `UNKNOWN, NEEDS_ASSISTANCE, PROVIDER_ACCEPTED, PICKUP_CONFIRMED, ARRIVAL_CONFIRMED, REQUIRES_COORDINATOR`; Communication as before; Assignment `PROPOSED, AWAITING_PROVIDER, ACCEPTED, DECLINED, CANCELED, COMPLETED, UNRESOLVED`; Zone `ORDER, WARNING, SHELTER_IN_PLACE, OUTSIDE_KNOWN_ZONES, UNKNOWN, STALE`; Recovery `NOT_REQUESTED, REQUESTED, ACCEPTED, COMPLETED, UNRESOLVED`; Route `ILLUSTRATIVE_ONLY, REFUSED, NO_ROUTE_CONFIRMED`.

## 8. Research already done (2026-10-17, read-only)

- **Cal OES California Evacuation Aggregation Layer** (includes LA County Genasys zones):
  `https://services.arcgis.com/BLN4oKB0N1YSgvY8/ArcGIS/rest/services/CA_EVACUATIONS_CalOESHosted_view/FeatureServer/0/query?where=1=1&outFields=*&outSR=4326&f=geojson`
  - Fields: `COUNTY, CITY, ZONE_NAME, ZONE_ID, STATUS, EVENT_TYPE, CRITICAL_INFO, PUBLIC_INFO, EDIT_DATE, STATEWIDE_LAST_UPDATED`. Max 2000 records.
  - `STATUS` is free text. The docs list NORMAL / EVACUATION WARNING / EVACUATION ORDER / SHELTER IN PLACE, but the live value seen was `"Evacuation Order"`, so normalize case-insensitively and flag unknown strings.
  - Refresh is documented as both 5 and 10 min, and features vanish for 15 s–1 min during rebuilds. So cancellation requires an explicit NORMAL **or** 2 consecutive polls missing the record. No license stated.
- No public LA County status layer (only planning grids). NWS / CAL FIRE are context only and never activate the order flow.
- **ASI:One API:** OpenAI-compatible base URL `https://api.asi1.ai/v1`, `asi1-mini` (docs disagree on other models; check the dashboard), tool calling, structured data (JSON schema), `x-session-id` header.
- **Cards:** not in the public docs; see §5 A0 blocker.
- **HERE:** V2's sample HERE uAgent is a reference for mechanics only. Known issues to fix: user-supplied closures are unverified; avoid-areas silently truncated above the max; no wildfire knowledge; the seed must be secret; ambiguous geocodes need refusal.

## 9. Developer A — tasks in order

**A0 — unblock (now)**
- **Cards spec:** find and verify the Card Playground schema and transport (§5). Log it in `integration-decisions.md` with links/screenshots.
- Check the current Fetch.ai hackpack judging criteria (Chat Protocol, Agentverse listing/README, MCP registration, shared chat).
- Investigate the 4 timing-out tests with B.
- Add deps: `shapely>=2`, `openai` (ASI:One client), HERE via `httpx` (already present). Add env vars `ASI_ONE_API_KEY`, `HERE_API_KEY`, `ALERT_FEED_URL`, `ALERT_POLL_INTERVAL_SECONDS=120`, seeds/ports for the new agents.

**A1 — switch to contract 2.0** once B's contract commit lands: update `backend_client.py` and `coordinator_actions.py`; `matches/propose` replaces evaluate + assignments.

**A2 — full ASI:One journey (core)**
- **Coordinator intent via ASI:One API tool calling:** each backend action is a tool (start check, list cases, case status, find providers, approve, confirm pickup/arrival, recovery, escalate, route preview, freeze feed). The LLM only picks the tool and arguments; the result text and status come from B. A keyword-matching fallback works when the API is down.
- Commands: start Zone 3 check → affected residents (Alert card); operations board; show suitable providers for Maria (Offer fan-out → `matches/propose create_proposal:false` → Proposal card); approve (propose → `AcceptRequest` → `/accept`, next provider on decline); pickup (`PickupReport` + resident confirmation) and arrival (`ArrivalReport`) as separate steps; recovery (consent → `/recovery` → Recovery agent → `/respond`); David (`UNSAFE_ZONE` → `/escalate` → Escalation agent → `/ack`); route preview; freeze feed (Data-health card).
- Plain-language summaries via ASI:One API, **built only from B's returned fields**. The status words are always copied verbatim from B.

**A3 — new agents:** Calamity Checker (`on_interval` 120 s, backoff, posts to `/alerts/ingest`, `AlertNotification` to Coordinator), **News / Road-closure** (polls B's synthetic news + official closure feeds; ASI:One API structured output extracts candidates from article text; posts to `/closures/ingest` with the honest `source_type`; optional ASI:One web search tagged `REAL_WORLD_CONTEXT`; never labels anything official), Recovery Provider, Escalation Simulator, Route Planner (HERE client; constraints and previews round-trip with B; refuses on any B refusal). All registered on Agentverse with profiles.

**A4 — LangGraph:** V2 graph and branches, durable per-case state, no busy-waiting, query state before retrying anything that creates.

**A5 — Interactive Cards:** the §5 deck on the verified schema; buttons send the follow-up commands; text fallback tested.

**A6 — delivery:** reliable mailbox agents, Agentverse URLs for all agents, public ASI:One shared chat (Maria, David, route, C), demo video, Fetch.ai section for the README.

## 10. Developer B — tasks in order

**B0 — unblock (now):** branch `feat/backend-geodata`. Commit `docs/interface-contract.md` **v2.0** (§7, with example JSON for every endpoint, including card view data and route constraints) and send A the hash **before implementing**.

**B1 — two databases + enrollment:** `var/residents.db` + `var/organizations.db` (one connection, `ATTACH`, rollback journal, so accept + capacity reservation are atomic). Models: Organization, Volunteer, Vehicle, DestinationSite, Availability, per-purpose consents, resident lat/lon + geocode confidence. Enrollment endpoints. Seed: fictional LA-area points for Maria (WARNING polygon) and David (ORDER polygon); orgs `transport_org_a..e` (IDs match A's fixtures), `destination_org_a..c`, `recovery_org_demo`, with volunteers and vehicles. Keep the roles: closer-unsuitable, farther-suitable, declines, unapproved.

**B2 — alerts + geofencing:** `GET /demo/feeds/caloes` (synthetic, Cal OES shape, driven by `/demo/alerts/trigger`). `POST /alerts/ingest`:
- validate fields and timestamps; normalize `STATUS` case-insensitively (unknown → flagged `UNKNOWN`, never guessed);
- freshness from `STATEWIDE_LAST_UPDATED`/`EDIT_DATE` vs `ALERT_STALE_AFTER_SECONDS`;
- dedupe by source ID + version + zone; 2-poll cancellation rule;
- Shapely `covers` geofence with ORDER dominance; stale → `STALE`, no data or bad geocode → `UNKNOWN`;
- check-ins only for new/changed **simulated** WARNING/ORDER with consent; idempotency key `alert:status:resident`;
- record `last_ingest_at`.

**B3 — matching + states:** approval = organization **and** volunteer approved; new codes `CAPABILITY_NOT_REGISTERED`, `AVAILABILITY_UNCONFIRMED` (missing/past `valid_until`); the zone gate blocks ORDER/UNKNOWN/STALE; ETA → distance ranking; V2-style positive codes. `matches/propose` with idempotency; capacity reserved once in `provider_events`. Escalation `REQUESTED → ack`. Recovery `NOT_REQUESTED/COMPLETED`. Scenario C.

**B4 — ASI:One API extraction (behind `USE_LLM_INTENT`):** Spanish/English free text → candidate needs via structured output, merged with the deterministic keyword extractor. Candidates still need SI/YES confirmation; the original text is kept; falls back to keywords on any error.

**B5 — closures + routes:**
- **Closures:** synthetic news and official-closure feeds, `/demo/closures/trigger`, and `/closures/ingest`, which keeps source, URL, published/updated time, raw text and the extracted candidate. **State is set by deterministic rules, not the LLM:** `OFFICIAL_SIMULATION` source → `OFFICIAL_CONFIRMED`; news / real-world → `UNVERIFIED_REPORT`; contradictory claims about the same segment → `CONFLICTING`; past expiry → `EXPIRED`. A small gazetteer maps road names to synthetic road segments; unmatched names stay unmapped (shown, never used for routing). Real-world items are display-only. `GET /closures`.
- **Routes:** `/routes/constraints` (order polygons + official-confirmed closures as avoid areas; unverified/conflicting as cautions; refuse if origin/destination is in an order zone or data is stale/unknown) and `/routes/previews` (polyline must not intersect order polygons and data must still be fresh, else `REFUSED`; recorded on the timeline). The synthetic graph remains as the offline fallback.

**B6 — card data + API + scripts + docs:** `/dashboard/summary`, `progress_steps`, `map` and `summary_text` on cases. Routes and schemas on §7 paths (keep the auth/correlation/error middleware). Scenarios A, B, C + route refusal in `demo/scenarios.py`; `smoke_test.sh` / `reset_demo.sh` need no Fetch credentials (HERE/ASI:One mocked). Update `dev-b-notes.md`, `decisions.md`; README (setup, architecture, simulation/safety statement). Spanish templates reviewed by a fluent speaker.

## 11. Checkpoints (in order)

| # | A | B | Joint check |
|---|---|---|---|
| C1 | **card spec verified (or fallback decided)**, hackpack criteria, deps/env, timeouts investigated | contract v2.0 committed | sign off on the contract |
| C2 | client on v2, Calamity agent → `/alerts/ingest` | DBs, enrollment, ingest + geofence, `matches/propose` | **one PR window: merge, delete v1, all green**; alert detected end to end |
| C3 | ASI:One API intent, Proposal + Case cards, accept / pickup / arrival | evidence, card data, LLM extraction | **Maria full journey in ASI:One with cards** |
| C4 | Escalation + Recovery agents | ack / respond endpoints | **David unresolved + Maria recovery in ASI:One** |
| C5 | News agent, Route agent (HERE), Road-conditions + Data-health cards | closures ingest/states, route constraints + post-check, `FREEZE_FEED` | **closures labeled, route avoids official closure + cautions on unverified, refusal, Scenario C in ASI:One** |
| C6 | all 8 agents on Agentverse, shared chat, video | README, smoke, reset, Spanish review | **freeze → merge to `main` → rehearse from reset** |

**No-wait rule:** A tests against B's real app in-process (`httpx.ASGITransport`); B tests API-only with a fake agent caller. HERE and ASI:One are mocked in tests on both sides.

## 12. Tests

- **B (offline unit):** V2 §6 + §13. Polygon inside/outside/**edge**; overlapping order + warning; canceled/expired/stale/malformed/empty/unavailable feed; **10 identical ingests → 1 check-in**; rebuild gap; fire incident ≠ order; uncertain geocode → UNKNOWN; mixed-case Cal OES fixture; route crossing an order polygon → REFUSED; news report never becomes `OFFICIAL_CONFIRMED` or a blocked edge; official closure is avoided; contradictory reports → `CONFLICTING`; unmapped road name never affects routing; "no reports" never yields "open"; stale data → route + match refused; LLM extraction can't bypass confirmation; plus all existing invariants (accessibility, unapproved, order zone, capacity, consent, unknown sender, duplicates, late replies, acceptance ≠ pickup ≠ arrival, silence ≠ danger, failed delivery ≠ no reply, ack ≠ assistance).
- **A (integration):** each agent pair over Bureau; Calamity → ingest → `AlertNotification`; decline → next provider; restart mid-workflow without duplicates; correlation ID across all hops; cards render + text fallback; LLM tool choice never changes a status string.
- **Together (end to end):** Maria, David, route, Scenario C, from ASI:One.

## 13. Demo (3 min)

0:00 problem → 0:15 Calamity agent detects the simulated order/warning polygons (**Alert card**, 120 s poll, source + time) → 0:35 **Operations board** → 0:45 Maria replies in Spanish; ASI:One API extracts candidate needs; she confirms → 1:05 Transport + Destination agents respond; **Proposal card** shows the closer sedan rejected → 1:20 *Approve* → provider agent accepts → pickup → arrival (**Journey cards**, green last) → **Recovery card** → 1:55 David: **Escalation card**, receipt only, unresolved → 2:05 **Road-conditions card**: News agent shows an official closure and an unverified news report → 2:15 **Route card**: HERE illustrative route avoiding the order zone and the official closure, with a caution for the unverified report, then a refusal → 2:28 freeze feed: **Data-health card** STALE → 2:40 Agentverse: 8 agents, shared chat → 2:50 limits: simulation, partner-led future.

## 14. Fetch.ai submission checklist

- [ ] Coordinator discoverable and chattable in ASI:One; Agentverse URLs for all 8 agents with profile READMEs
- [ ] Real agent-to-agent messages for alerts, closures, offers, acceptance, pickup/arrival reports, recovery, escalation, routes
- [ ] ASI:One API used for intent and extraction (never safety); documented
- [ ] Interactive Cards on the verified schema (or documented fallback), text fallback working
- [ ] Public ASI:One shared chat: Maria, David, route, Scenario C
- [ ] README: setup, architecture, agent list, simulation/safety statement; demo video + offline backup
- [ ] No real people, addresses, alerts or dispatch; real feed display-only; every card says SIMULATION

## 15. Prompts for each Claude Code session

**Developer A:**
> You are Developer A on Doorstep V2 (Fetch.ai track; Fetch-first everywhere). Read this plan, `Doorstep_V2_Two_Person_Claude_Code_Plan.md`, and `Doorstep_Implementation_Master_Spec.md`; this plan wins on scope and tech stack. Work on `feat/fetch-agents` in A-owned files only (§6.7). Start with A0: verify the ASI:One Interactive Cards schema/transport from official sources before building any card, and log it. Switch the backend client to contract v2.0 once B's commit lands, then build the 8 agents (§4, including the News / Road-closure agent that never labels reports official), ASI:One API tool-calling intent with keyword fallback, the LangGraph workflow, the card deck (§5) with text fallback, and the full ASI:One journey (§9 A2). The LLM picks tools and writes prose only from B's fields; it never decides eligibility, zones, consent or status. Never invent endpoints, MCP commands or card schemas. Everything simulated and DEMO-labeled. Report commit hashes, payloads, agent URLs and test results at each checkpoint (§11).

**Developer B:**
> You are Developer B on Doorstep V2 (Fetch.ai track). Read this plan, `Doorstep_V2_Two_Person_Claude_Code_Plan.md`, and `Doorstep_Implementation_Master_Spec.md`; this plan wins on scope. Work on `feat/backend-geodata` in B-owned files only (§6.7). First commit `docs/interface-contract.md` v2.0 (§7) and send A the hash. Then build the two databases + enrollment, the Cal-OES-shaped synthetic feed and `/alerts/ingest` with Shapely geofencing and STALE/UNKNOWN, matching against the org registry and `matches/propose`, escalation ack and recovery respond, ASI:One API extraction behind a flag (confirmation still required), synthetic news + official closure feeds and `/closures/ingest` with deterministic OFFICIAL_CONFIRMED / UNVERIFIED_REPORT / CONFLICTING / EXPIRED states (only official closures block roads), route constraints + polyline post-check, card view data, and Scenarios A/B/C + closures + route refusal in API-only tests and the smoke test (no Fetch/HERE/ASI:One credentials needed). Real feed data is display-only. Missing or stale data never means safe. Report commit hash, examples and test results at each checkpoint.

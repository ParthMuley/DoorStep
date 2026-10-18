# Developer A notes (Fetch.ai + orchestration)

Branch: `feat/fetch-orchestration`. Owns `src/doorstep/agents/`, `src/doorstep/workflows/`, `src/doorstep/integrations/fetch_adapter.py`, `src/doorstep/integrations/sentry_setup.py`, `tests/integration/fetch_*`, `docs/integration-decisions.md`, `pyproject.toml`, `.env.example`.

## Handoff log

Each entry: commit hash, sample JSON, how to run, tests run, known limitations.

### H0 — bootstrap
- Commit: _(fill after commit)_
- Contents: package skeleton, `pyproject.toml`, `.env.example`, `.gitignore`, `docs/interface-contract.md` v1.0, copies of both spec docs.
- For B: start `feat/domain-backend` from this commit. Implement the HTTP API in `docs/interface-contract.md` §3. Note the design decision there: provider agents return raw offers; B's `…/evaluate` endpoints decide eligibility.
- Known limitations: no agent code yet.

## Contract v2.0 revision 2 — Developer A review (2026-10-17)

Reviewed `docs/interface-contract.md` v2.0 rev 2 and `docs/DOORSTEP_V2_TEAM_PLAN.md` rev 2 (f869ff9). The overall design works for A. **Sign-off is pending B's answers to items 1–5.** Items 6–10 are notes and need no contract change.

**Needs a decision before sign-off**
1. **`X-Org-Agent` is spoofable.** It is a plain header, so any caller holding `DEMO_AUTH_TOKEN` can claim any org, and cross-org isolation would only be cosmetic. Proposal: per-org secrets, e.g. `ORG_AGENT_TOKENS={"eastside_rides_demo":"…",…}` in `.env`, sent as `X-Org-Token` alongside `X-Org-Agent`; B rejects a mismatch with 403. Tests can use fixed test tokens.
2. **Org agent addresses.** `outreach_orgs[].agent_address` and `match.org_agent_address` must equal the running agents' addresses, which A derives from seeds. Proposal: `PUT /orgs/{org_id}/agent {"agent_address":"agent1q…"}` (token + org token), called by each org agent at startup, which keeps the seed private to A. Same for Doorstep, Matching, Escalation and Post-Calamity if B needs their addresses.
3. **Outreach timing.** Volunteer answers arrive asynchronously, through `/sim/inbound` or the org agent. A plans to send `OutreachResult` **immediately** with `asked` / `skipped`, after which the Doorstep agent reads progress from `GET /alerts/{id}/outreach`, with nothing blocking inside a handler. Please confirm that endpoint updates live as answers come in, and that `NO_REPLY` appears only after `/sim/outreach/{alert_id}/deadline`.
4. **Demo inputs from ASI:One.** Every demo step must be doable from chat. A will add "simulate …" commands that call B's `/sim/*` hooks: Maria's Spanish reply and SI, volunteer YES/NO, and the resident's pickup confirmation. Please confirm `/sim/inbound` accepts volunteer phones as well as resident phones, and that these hooks are allowed with the demo token.
5. **Pickup evidence.** `PickupReport` comes from the org agent (the volunteer), but the resident's confirmation is also required. Please confirm the resident side arrives through `/sim/inbound` ("1 PICKED UP"?) or via a field on `/pickup`, so A knows which call carries `resident_confirmed:true`.

**Notes (no contract change needed)**
6. **Cards are documented.** Plan §8 can drop the A0 blocker; see `docs/integration-decisions.md`. Card payloads are ≤64 KB, so B's card data is fine as specified.
7. **Agent count.** A will run org agents only for demo-relevant orgs: `eastside_rides_demo`, `neighbor_sedans_demo`, `red_cross_demo`, `civic_shelter_demo`, `recovery_housing_demo`. `unlisted_vans_demo` and `flood_only_demo` are filtered out by B, so they need no agent.
8. **Incremental delivery helps A most.** A consumes endpoints in this order: `/alerts/ingest` + `/alerts/active` + `/demo/alerts/trigger` → `/orgs/{id}/outreach` + volunteers + availability → `/matches/propose` + `/accept` → pickup/arrival → escalate/ack → recovery → closures → routes → dashboard. Small PRs in that order let A switch without waiting for the whole Mongo port.
9. **Live demo DB.** Will a local MongoDB or Atlas run the live demo? A needs `MONGODB_URI` to start B's backend for live agent runs.
10. **The 4 agent tests timing out on B's machine** come from network calls at Bureau startup (Almanac/ledger registration). A is fixing this in `tests/integration/conftest.py`, so no change is needed on B's side.

### V2 agents built against contract v2.0 (2026-10-17, branch `feat/fetch-agents`)
- **New agents** (`src/doorstep/agents/`):
  - `organization.py`: one generic agent, run per org (`python -m doorstep.agents.organization <org_id>`).
  - `calamity_checker.py`, `matching.py`, `escalation.py`, `post_calamity.py`.
  - Messages: `integrations/fetch_messages.py` (schema 2.0). Client: `workflows/backend_v2.py`.
- **Against B's real code:** the Organization agent uses B's real `GET /orgs/{id}/volunteers` and `POST /orgs/{id}/volunteers/{vid}/availability` (merged from `feat/backend-geodata` d377125), and the `X-Org-Agent` scoping is enforced by B.
- **Test double for the rest:** `tests/integration/fake_v2_backend.py`. It is B's real app with contract-shaped stand-ins inserted in front for routes B hasn't built yet:
  - `/demo/feeds/caloes`, `/demo/alerts/trigger`, `/alerts/ingest`;
  - `/orgs/{id}/outreach`;
  - `/matches/propose`, `/assignments/{id}/accept|pickup|arrival`;
  - `/cases/{id}/escalate`, `/escalations/{id}/ack`;
  - `/cases/{id}/recovery`, `/recovery/{id}/respond`.

  **B: delete each stand-in when your real route lands; A's tests must then pass against your code.**
- **Demo personas:** volunteer and shelter answers are simulated from `agents/fixtures/volunteer_personas.json` (Sarah YES, Joe YES, Maya no reply, Lee YES). `DECLINE_VOLUNTEERS=volunteer_sarah` forces the decline → next-alternate path.
- **Tests:** `tests/integration/test_fetch_v2_agents.py`, 7 agent-pair tests, offline. They cover outreach, the 3 identical polls → 1 notification rule, failed-fetch backoff, Maria's match → accept → pickup → arrival, decline → Lee, David's receipt-only escalation, and the recovery referrals plus the no-consent case.
- **Not yet:** the Doorstep coordinator doesn't drive the V2 flow yet (the next step; it needs B's real endpoints or the double in a dev server); News and Route agents; LangGraph.

### Doorstep agent drives the V2 journey (2026-10-17)
- `agents/journey.py` holds the V2 flow state and steps. The coordinator routes card clicks, ASI:One tool calls and keywords into it, and pushes alert and outreach cards to the users talking to it.
- **Removed:** the v1 Transport/Destination agents, `provider_client.py`, the v1 offer messages and the v1 coordinator actions. The Organization agents replace them.
- **Dev run before B's v2 routes land:** `.venv/Scripts/python scripts/dev_backend_v2.py` (B's app + test double, DEV ONLY), then `scripts/run_agents.ps1`, then `scripts/journey_probe.py`, or chat in ASI:One.
- **Tests:** `tests/integration/test_fetch_v2_journey.py`, an end-to-end ASI:One-user conversation over all agents (offline).
- **Known gaps:**
  - Pickup evidence marks the resident confirmation as simulated until B answers review item 5.
  - The journey state is in memory; the thin LangGraph step will make it durable.
  - `GET /cases` doesn't reflect v2 assignments until B's v2 lands, so status after acceptance uses the journey card.

### Rev 3: Volunteer Network agent replaces per-org agents (2026-10-17)
- `agents/volunteer_network.py` is one agent for all partner orgs. Messages name the `org_id`; `OutreachResult` now lists orgs per alert.
- Removed `agents/organization.py` and the `ORG_SEED_*` settings; added `NETWORK_SEED` and `NETWORK_PORT` (8110).
- **Test double** (`tests/integration/fake_v2_backend.py`) is on the rev 3 shapes:
  - `POST /alerts/{id}/outreach`
  - `POST /alerts/{id}/volunteers/{vid}/availability`
  - `GET /alerts/{id}/outreach`
  - `GET /regions/near`
  - accept and recovery-respond checked by `org_id` in the body; no `X-Org-Agent`, no per-org agent addresses.
  - The region list is a stand-in until B's geo query lands.
- **B: contract v2.1 should match these shapes** (or tell A what differs; A adjusts the client in one place, `workflows/backend_v2.py`).

### News / Road-closure agent (2026-10-17)
- `agents/news.py`:
  - polls B's simulated official closure feed (posted as `OFFICIAL_SIMULATION`, `STRUCTURED_FEED`);
  - polls synthetic news; `integrations/closure_extraction.py` extracts the article's *claim* with an ASI:One forced tool call (`asi1-mini`, ~1–2 s). The keyword fallback is used when the API is off or errors; enum-validated.
  - Posts to `/closures/ingest`, then sends `ClosureNotification` → the Doorstep agent pushes a **Road conditions** card. Also on request: "road conditions".
- **The double now has** `/demo/feeds/news`, `/demo/feeds/closures`, `/demo/closures/trigger`, `/closures/ingest` and `GET /closures`, with B's state rules:
  - an official CLOSED claim → `OFFICIAL_CONFIRMED`;
  - news → `UNVERIFIED_REPORT`;
  - a contradiction → `CONFLICTING`;
  - a gazetteer maps road names; unmapped names never route.
- **Tests run offline:** the shared fixture now forces `USE_LLM_INTENT=false` and `USE_LLM_EXTRACTION=false`, because `.env` enabled the real ASI:One API.
- **Live (7 agents on mailboxes, 61 s):** Ridge Ave `OFFICIAL_CONFIRMED` (`STRUCTURED_FEED`); Canyon Rd `UNVERIFIED_REPORT` (`ASI_ONE_EXTRACTION`); the bake-sale article was ignored.

### Note for B (2026-10-18): unit tests aren't hermetic for NETWORK_AGENT_TOKEN
B's app loads `.env` at import. `tests/unit/conftest.py` clears `DEMO_AUTH_TOKEN` but not `NETWORK_AGENT_TOKEN`, so a custom network token in a developer's `.env` makes 5 unit tests fail with 403 (test_alerts x3, test_matching_v2 network-token test, test_recovery_v2 network-token test). Suggested fix (B's file): also `monkeypatch.delenv("NETWORK_AGENT_TOKEN", raising=False)`. A's integration tests already clear it.


### Switched to B's real contract v2.1 routes (2026-10-18)
- **Agents now use B's real routes:**
  - alerts ingest, network outreach and availability;
  - `/regions/near`, matching, v2 accept/pickup/arrival;
  - escalate/ack, recovery and respond;
  - cases, plus `PUT /agents/{role}` (every agent registers its address at startup).
- **Network token:** only the Volunteer Network agent's client holds `X-Agent-Token` (`NETWORK_AGENT_TOKEN`).
- **Test double** (`tests/integration/fake_v2_backend.py`) now covers **only** closures; routes and dashboard come later.
- **Real-backend behavior adopted:**
  - matching refuses unconfirmed needs (David's reply comes first in the demo);
  - recovery only after arrival;
  - pickup/arrival responses carry no `map`, so the color comes from `GET /cases/{id}`;
  - outreach uses `region_ids` and `awaiting`.
- **Bugs found against B's real backend:**
  1. The Calamity ingest idempotency key was time-based; two polls in one second collided, and B correctly replayed the empty first result. It is now content-hashed.
  2. The News agent's startup poll notified nobody, and the on-demand poll then stayed silent. On-demand polls now always return a snapshot, and the first scheduled tick is skipped.
- **Tests:** 210 passed (B's unit tests included). **Live:** 7/7 mailboxes, 7/7 registered with B, full journey in 70 s.

### Route agent (2026-10-18)
- **Files:**
  - `agents/route.py` (service agent; no LLM);
  - `integrations/here_client.py`;
  - `RouteRequest`/`RouteResponse` messages;
  - `route_constraints` and `route_preview` client calls.
- **Flow:** the journey asks the Route agent after the volunteer accepts. The approve reply is now [Help on the way, **Route card**]: distance, ETA to pickup, what was avoided, cautions for unverified reports on the path, the first directions, and the ILLUSTRATIVE banner, or a refusal with reasons.
- **Test double:** `/routes/constraints` and `/routes/previews` stand-ins with a real Shapely post-check. The geometry mirrors B's seed; B: replace these with your real routes (contract §5.10).
- **Tests:**
  - `tests/integration/test_route.py` (7): enlarge-only, latitude-first syntax, refuse when there are over 20 polygons, violation notice, illustrative route with a caution, a route through the order zone refused by the post-check, no route, cache, daily cap;
  - the end-to-end journey includes the route.
  - **217 tests passed.**
- **Live:** the Route agent runs and registers with B, and without `HERE_API_KEY` it returns `NO_ROUTE_CONFIRMED` (`HERE_NOT_CONFIGURED`) with no HERE call.
- **Agentverse:** the account cap is hit again (8/8), so the Route agent currently runs local-only (`LOCAL_ONLY_AGENTS=doorstep_route`). One non-Doorstep agent occupies a slot.

### Merged B6 (closures + routes) and B7 (dashboard); test double removed (2026-10-18)
- All stand-ins are deleted. `tests/integration/fake_v2_backend.py` is now just B's real app plus the network-token client. **239 tests pass.**
- **Asks for B:**
  1. **`ClosureItem.extraction_method`:** please add `KEYWORD_EXTRACTION`. When ASI:One is down, the News agent falls back to deterministic keyword extraction. Today B rejects that label (422), and A won't mislabel it as ASI:One, so those items are skipped and retried later. The skip is safe, since news reports are caution-only, but we lose information.
  2. **`ROUTE_MAX_AVOID_AREAS` (250) vs HERE:** HERE v8 accepts **at most 20 polygons** per request (250 is the bounding-box figure). The Route agent refuses above 20 (`TOO_MANY_AVOID_AREAS`). Please align B's default to 20 so the two refusals agree.
  3. **Unit tests and `NETWORK_AGENT_TOKEN`:** please also clear it in `tests/unit/conftest.py` (see the earlier note).
- **Rev 4 amendments §0.5:** A agrees with all three (Doorstep-only sender with `DOORSTEP_AGENT_TOKEN`, public demo link codes, 15-minute reply deadline plus `/deadlines/sweep` from the Calamity Checker). They will be implemented in A's rev 4 linking work.

### Rev 4: ASI:One account linking + role cards (2026-10-18)
- **Linking:** `LINK <code>` (or the link form card) → `POST /link` with the **envelope sender**, never typed text, plus `X-Agent-Token: DOORSTEP_AGENT_TOKEN`. Links live in `agents/links.py` and persist in the Doorstep agent's storage. With `REQUIRE_LINK=true` (default), an unlinked chat only gets the link card. Tests use open mode, except `test_rev4_linking.py`.
- **Resident cards:** check-in (1–4) → needs confirmation (yes/no) → help on the way + "confirm pickup" → arrival + **consent card (only the resident can consent; a coordinator's request is forwarded to them)** → referrals.
- **Volunteer cards:**
  - availability (yes/no), relayed to the Volunteer Network as `VolunteerAnswer`; linked volunteers are never auto-answered (`live_volunteers`);
  - assignment card (accept/decline; pickup point withheld);
  - route card + "confirm pickup".
- **Pickup** needs the volunteer **and** the resident. A linked person confirms in their own chat (`source: ASI_ONE`, both party IDs). An unlinked person is simulated and labeled.
- **Test:** `tests/integration/test_rev4_linking.py`: three linked people plus a stranger. It covers the link card, a spent code (409), the resident, volunteer and coordinator cards, a two-party pickup, and that a coordinator can't consent. **241 tests pass.**
- **Live:** 8/8 agents on Agentverse mailboxes (the old sample "ASI uAgent" was unregistered at the user's request); journey complete with the coordinator linked.
- **Asks for B (contract v2.2, still missing; A uses a stand-in `POST /link` in `tests/integration/fake_v2_backend.py`, with codes MARIA-4821, DAVID-5932, SARAH-7310, LEE-6624, COORD-1150):**
  1. `POST /link {code, asi_one_address}` with `X-Agent-Token: DOORSTEP_AGENT_TOKEN`. It should return `role`, `display_name` and `resident_id`+`case_id` / `volunteer_id`+`org_id` / `coordinator_id`. 409 for an unknown or spent code.
  2. `POST /cases/{id}/responses`: accept `sender` = the linked ASI:One address when the Doorstep token is present. Until then, the stand-in returns `sender_for_backend` (the seeded sim contact), and Doorstep sends that.
  3. `POST /deadlines/sweep`: the client method exists (`deadline_sweep`), but the Calamity Checker doesn't call it yet, and B hasn't built the route.

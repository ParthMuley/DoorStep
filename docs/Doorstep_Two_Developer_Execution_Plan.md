# DOORSTEP | Two-Developer Parallel Execution Plan

**Companion to:** `Doorstep_Implementation_Master_Spec.md` (v1.0). Both developers must read the master spec first. This document allocates work, defines shared interfaces, and prevents one developer from waiting for the other. If the documents disagree, the master spec's safety and scope rules win.

**Team:** Developer A and Developer B, each using Claude Code in a separate worktree or clone of the same repository.

**Goal:** Complete the two synthetic scenarios in ASI:One, with genuine Fetch.ai agent communication, reliable state tracking, and safe simulated escalation. The map, Photon, cards, and other sponsor polish are secondary.

## 1. Ownership: no shared-file editing

| Developer A: Fetch.ai + orchestration | Developer B: domain engine + API + demo experience |
|---|---|
| Owns Agentverse/ASI:One integration, agent messaging, coordinator and provider-agent wrappers, LangGraph orchestration, agent integration tests, deployment, shared ASI:One chat evidence | Owns typed data contracts, SQLite state, deterministic matching, safety and consent rules, synthetic fixtures, simulation endpoints, event history, messaging simulator, dashboard, unit tests |
| Owns `src/doorstep/agents/`, `src/doorstep/workflows/coordination_graph.py`, `src/doorstep/integrations/fetch_adapter.py`, `tests/integration/fetch_*`, `docs/integration-decisions.md` | Owns `src/doorstep/models/`, `src/doorstep/services/`, `src/doorstep/api/`, `src/doorstep/demo/`, `src/doorstep/integrations/message_simulator.py`, `tests/unit/`, `dashboard/` |
| Owns Fetch-related environment variables and agent startup scripts | Owns schema migrations, seed/reset scripts and backend startup scripts |
| Sentry agent spans and cross-agent correlation | Sentry API logs, dashboard monitoring if built |
| Photon integration **only after** B's messaging interface is ready; build in `integrations/photon_adapter.py` | Base44/dashboard **only after** both scenarios work in ASI:One |

**One person owns each file.** Neither Claude session may edit the other's directories without agreeing in chat and opening a small PR. Do not run both sessions on the same branch or working directory. A owns the integration document; B owns `docs/decisions.md`; each appends to their own `docs/dev-a-notes.md` or `docs/dev-b-notes.md`.

## 2. Shared contract to agree in first 30 minutes

Both developers copy the following interface into their Claude Code instructions. B creates the canonical typed models and local service implementation. A builds against the shapes immediately using local stubs and fixtures. **A must not wait for B's code.** If B changes a schema, B proposes a versioned contract change; A accepts before it is merged.

### Shared IDs and envelopes

All IDs are synthetic opaque strings. All timestamps are UTC ISO-8601. Every message/event includes `schema_version: "1.0"`, `case_id`, `event_id`, `correlation_id`, `created_at` where relevant. Provider messages include `request_id`, `provider_id`, and `idempotency_key` for any action that can create a reservation/assignment. Validate incoming data with Pydantic.

### Core operations (our internal interface, NOT Fetch.ai API endpoints)

| Operation | Input | Output / meaning | Owner |
|---|---|---|---|
| `start_demo_warning(zone_id, scenario_id)` | demo-authorized zone and scenario | created check-ins/case IDs; simulated only | B implements; A calls |
| `submit_resident_response(case_id, text, language)` | synthetic resident reply | stored response and confirmed/extracted needs | B implements; A calls |
| `find_transport(request)` | case, consent-scoped needs, zone | offers with capability and acceptance state | B defines result; A's Transport agent uses it |
| `find_destination(request)` | accessibility, pet, capacity needs | eligible destination offers | B defines result; A's Destination agent uses it |
| `propose_assignment(case_id, offer_id)` | candidate offer | proposed assignment or safety rejection | B implements; A orchestrates |
| `accept_assignment(assignment_id, provider_identity)` | authorized provider response | accepted/declined, deduplicated | B implements; A routes message |
| `confirm_pickup(assignment_id, evidence)` | permitted confirmation evidence | pickup confirmed, never arrival | B implements; A orchestrates |
| `confirm_arrival(assignment_id, evidence)` | permitted arrival evidence | arrival confirmed only after pickup | B implements; A orchestrates |
| `request_recovery_handoff(case_id, consent)` | limited needs + consent | requested/accepted/unresolved | B implements simulator; A invokes |
| `escalate_case(case_id, reason)` | unsafe-zone or unresolved reason | simulated acknowledgment, assistance **not** confirmed | B implements; A invokes |
| `get_case_status(case_id)` | case ID | persisted timeline and current state | B implements; A displays in ASI:One |

### Agreed states

- Resident: `NEEDS_ASSISTANCE`, `PROVIDER_ACCEPTED`, `PICKUP_CONFIRMED`, `ARRIVAL_CONFIRMED`, `REQUIRES_COORDINATOR`, `UNKNOWN`.
- Communication: `NOT_SENT`, `SENT`, `DELIVERED`, `DELIVERY_FAILED`, `REPLIED`, `NO_REPLY_AFTER_DEADLINE`, `UNKNOWN`.
- Service: `DRAFT`, `PROPOSED`, `AWAITING_PROVIDER`, `ACCEPTED`, `DECLINED`, `CANCELED`, `COMPLETED`, `UNRESOLVED`.
- **Never** infer arrival from acceptance, infer danger from silence, or infer dispatch from emergency-request acknowledgment.

### Stable adapter boundaries

A's coordinator uses a `DoorstepBackend` client interface, not direct imports of B's SQLite implementation. B exposes the agreed functions through local FastAPI endpoints with Pydantic request/response types. A may initially use an in-memory fake with the same interface. When B's API is ready, A switches the base URL. This allows fully parallel work.

A's provider agents have separate synthetic inventories (transport and destination) and communicate through documented Fetch.ai messaging. They **must not** read B's shared coordinator database. For the first integration, A can use seeded provider JSON local to each provider. B owns central case/assignment state and checks all constraints before accepting actions. Providers only see consent-scoped data.

## 3. Bootstrap without blocking each other (H0-H2)

**Developer A**
1. Create GitHub repository, branch `feat/fetch-orchestration`, basic package skeleton and `.env.example` with placeholder names (no secrets). Create the shared contract file `docs/interface-contract.md` from Section 2, commit it immediately.
2. Check official Fetch.ai SDK/ACP/ASI:One registration docs; log confirmed SDK versions, commands, capabilities, and missing features in `docs/integration-decisions.md`. Test Coordinator hello-world in ASI:One.
3. Set up independent provider agents using local JSON fixtures; return stub offers with the agreed envelope.
4. Publish contract commit and tell B its hash. Continue using stubs even if B has not finished.

**Developer B**
1. Start branch `feat/domain-backend` from the bootstrap commit, or create an isolated worktree if the repo has not been pushed yet. If waiting for A's first commit, immediately develop local Pydantic models and tests in a temporary branch; cherry-pick afterward.
2. Build Pydantic models, synthetic fixtures, and a local FastAPI app implementing the contract. Make every endpoint testable with curl and pytest without any Fetch.ai credentials.
3. Create SQLite persistence and event timeline, including unique constraints on active assignments and idempotency keys.
4. Provide `/health`, `/demo/reset`, `/cases/{case_id}` and internal operations consistent with the contract. Restrict mutation/demo reset to demo-authorized callers.

**Gate at H2:** Both have a running independent hello-world. A has an agent that returns a stub response; B has an API that returns a seeded synthetic case. Neither depends on the other being deployed.

## 4. Workstreams and exact acceptance checks

### Developer A: Fetch.ai + workflow (P0)

**A1. Real agent registration and ASI:One interaction (H0-H6)**
- Register the Coordinator on Agentverse and make it discoverable in ASI:One.
- Confirm the current Agent Chat Protocol and actual supported interaction path from official documentation.
- Use official MCP registration only if an authenticated MCP tool actually supports it; otherwise use the documented registration path.
- Do not assume an autocomplete API is agent transport. Use documented uAgents messaging.
- Register/start Transport and Destination as independently addressable agents.
- Acceptance: ASI:One message reaches Coordinator, Coordinator calls Transport and Destination over Fetch.ai, returns offers to ASI:One. Save real URLs and a trace/transcript.

**A2. LangGraph coordination (H6-H14)**
- Implement graph: load case -> validate simulated alert -> consent -> check-in -> response -> discover providers -> request offers -> call B's safety/assignment API -> acceptance -> pickup -> arrival -> recovery consent -> handoff -> summary.
- Handle pauses without busy waiting; persist graph identifiers and use correlation IDs. Use B's backend for authoritative case state.
- Add branches for declined provider, unavailable provider, unverified alert, missing consent, timeout, and unsafe zone.
- For an unsafe-zone case, request **simulated** emergency escalation only; no live 911 contact or volunteer dispatch.
- Acceptance: Scenario A and Scenario B run via text commands in ASI:One using stubs if needed; after B's API is ready, use real state.

**A3. Fetch-side observability (H14-H22)**
- Add Sentry traces/spans to coordinator and providers; pass the same correlation ID across messages.
- Demonstrate a real debugging observation and fix, with before/after evidence. Never invent a debugging story.
- Acceptance: one trace links coordinator and two providers; no resident-sensitive information in logs.

**A4. Optional polish (after P0)**
- Photon adapter only if Spectrum supports required proactive sends, reply capture and safe test-mode operation. Preserve simulator fallback.
- ASI:One Interactive Cards only if documented Card Playground schema works. Plain text always works.
- Deployment and final ASI:One shared chat; backup video.

### Developer B: domain engine + API + simulation (P0)

**B1. Data and safety engine (H0-H8)**
- Build typed models for resident, caregiver, consent, case, provider, vehicle, destination, message, assignment, verification, escalation, and status event.
- Seed Maria: Spanish, wheelchair transport, transfer assistance, dog, step-free destination, safe-zone synthetic pickup. Seed David: inside active-order zone, requiring escalation.
- Matching is plain deterministic code: approved provider, service area, wheelchair and transfer capability, capacity, pet/service-animal constraints, oxygen handling if present, destination suitability, and no restricted-zone entry or blocked simulated edge.
- Enforce consent before data sharing, and provider approval before sharing pickup address. Never invent priority of human lives.
- Acceptance: tests reject unsuitable/unsafe providers and missing consent; only eligible offers pass.

**B2. State transitions and backend (H6-H14)**
- Implement contract operations as authenticated demo APIs; case state persisted in SQLite; atomic acceptance and idempotency for duplicate/delayed messages.
- Separate message-delivery state from resident-assistance state.
- A provider accepting never sets pickup or arrival; pickup never sets arrival; only appropriate evidence sets arrival.
- Unanswered text, failed delivery, and unknown status remain separate.
- Acceptance: complete Scenario A via API alone; Scenario B cannot assign an ordinary volunteer and ends unresolved with simulated acknowledgment.

**B3. Resident communication and recovery simulator (H10-H18)**
- Simulated SMS messages labeled `DOORSTEP DEMO`; English/Spanish fixed safety text; free-text parsing can use LLM only to extract candidate needs, requiring confirmation.
- Simulated transport acceptance, pickup confirmation, arrival confirmation, and recovery request/acceptance. Add event injection for duplicate replies, declined provider, no reply, failed delivery.
- Acceptance: deterministic `reset_demo.sh` recreates identical states; `smoke_test.sh` runs both cases without real SMS or external services.

**B4. Optional map/dashboard (H18-H26)**
- Only after P0, build a small dashboard with synthetic zones, case timeline, provider capacity and unresolved queue. Prefer Base44 if practical; otherwise simple fallback.
- Use red/yellow/blue/green/black/gray with text labels. Green only for verified simulated arrival. Display prominent `SIMULATION` banner.
- Do not show actual wildfire-safe routes or real residential addresses.
- Acceptance: dashboard reflects the same authoritative API state ASI:One displays, never independent mock status.

**B5. QA and documentation (H26-H36)**
- Own test matrix, fixtures, clean setup, safety README section, deterministic demo reset and local offline video path.
- Support A's live integration debugging without editing A's agent files.

## 5. Integration handoffs (specific times and payloads)

| Checkpoint | What A provides | What B provides | Combined test |
|---|---|---|---|
| H2 | Coordinator hello-world + contract | `/health`, seeded case | Compare model fields and sample JSON |
| H6 | Coordinator -> two provider agents, stub offers | `find_transport`, `find_destination`, `get_case_status` | A queries providers and B records proposed eligible plan |
| H10 | ASI:One start/status and LangGraph happy path | response intake, consent, safety/assignment API | ASI:One starts Maria's case and shows proposal |
| H14 | acceptance/pickup/arrival flow | atomic transitions + evidence log | Maria: accepted -> pickup -> arrival, each separately verified |
| H18 | unsafe-zone branch and escalation call | David unsafe-zone rejection + simulated acknowledgment | David remains unresolved; no volunteer assigned |
| H22 | cross-agent Sentry spans | backend logs and stable dashboard read API | One correlation ID across services |
| H26 | optional Photon/cards | optional map/dashboard | Text fallback works without optional tools |
| H30 | Agentverse URLs, ASI:One shared chat | clean checkout tests, reset script, backup demo | Feature freeze and rehearsal |
| H36 | submission-ready integration proof | submission-ready docs/video | Final submission complete |

**Handoff rule:** Each handoff includes (1) branch/commit hash, (2) example input/output JSON, (3) how to run it, (4) tests run, (5) known limitations. No verbal-only handoffs. If a dependency is late, use the stable mock adapter, keep progressing, and reconnect at the next checkpoint.

## 6. Git workflow for two Claude Code sessions

1. A creates repository and commits contract, base package, `.env.example`, and empty directories. B starts from that commit.
2. Each works in a separate clone/worktree and branch. Suggested names: `feat/fetch-orchestration` and `feat/domain-backend`.
3. Avoid simultaneous edits to `pyproject.toml`, `README.md`, `.env.example`, and shared contracts. **A owns** dependency/SDK changes in `pyproject.toml`; **B owns** `README.md` and `docs/decisions.md`. To request a dependency, B sends A the exact package/version and why; A adds it promptly. B can use an isolated dev environment until merged.
4. Merge B's contract/API changes early, then A's integration, using small PRs. A does not overwrite B's domain logic; B does not overwrite A's agent code.
5. After each merge run `pytest` and `scripts/smoke_test.sh`. If a test fails, stop merging unrelated features until fixed.
6. Use `SIMULATION_MODE=true`, `USE_PHOTON=false`, `USE_BASE44=false`, `USE_CARDS=false` as defaults. No credentials in commits. Add one `.env.example` with all documented variables.
7. Freeze features by H30 and rehearse from a clean demo reset.

## 7. Mandatory test matrix and who writes it

**B writes deterministic unit tests:** wheelchair mismatch; transfer-support mismatch; pet/service-animal requirements; oxygen capability when needed; nonapproved provider; active-order-zone restriction; blocked synthetic road; insufficient capacity; missing consent; unknown sender; duplicate assignment; delayed acceptance; acceptance not pickup; pickup not arrival; no reply not danger; failed delivery not no reply; escalation acknowledgment not rescue.

**A writes integration tests:** ASI:One -> Coordinator -> Transport -> Coordinator; Coordinator -> Destination; agent discovery; provider decline/timeout; workflow pause/resume; status reflected in ASI:One; correlation ID propagated to Sentry.

**Together write two end-to-end tests:**
- **Maria:** simulated official warning -> Spanish request -> needs confirmed -> safe eligible transport and accessible destination -> approved provider acceptance -> pickup evidence -> arrival evidence -> consented recovery referral -> final ASI:One status.
- **David:** simulated official warning -> inside active-order zone -> no ordinary volunteer dispatch -> simulated authorized-service acknowledgment -> assistance **unconfirmed**, case **unresolved** in ASI:One.

**P0 passes only if:** both scenarios work inside ASI:One; at least two independent Fetch.ai provider agents communicate; no unsafe assignment; every displayed state has persisted evidence; clean setup and tests pass; simulation labeling is unmissable.

## 8. If something breaks: ownership and fallback

| Failure | Owner | Immediate fallback |
|---|---|---|
| Agentverse registration or ACP fails | A | Debug official SDK; keep local provider agents and preserve ASI:One eligibility as highest-priority blocker; do not falsely claim sponsor qualification |
| B API not ready | A continues | In-memory `DoorstepBackend` fake implementing same interface |
| A agents not ready | B continues | API-only smoke tests and synthetic event driver |
| Provider message times out | A | Query status first; no blind retry of non-idempotent actions |
| Photon not available | A | B's labeled messaging simulator |
| Base44 integration fails | B | Simple read-only status page or ASI:One-only demo |
| ASI cards unavailable | A | Plain text status in ASI:One |
| Live route API unavailable | B | Synthetic blocked-edge graph; never infer real wildfire route safety |
| Sentry cross-service trace unavailable | A/B | Manual correlated spans/logs; document limitations |
| Time slipping at H14 | Both | Cut all P1 and polish; focus on both scenarios and Fetch.ai compliance |

## 9. Exact Claude Code prompt for Developer A

> You are Developer A on Doorstep. Read `Doorstep_Implementation_Master_Spec.md` and `Doorstep_Two_Developer_Execution_Plan.md` completely. You exclusively own Fetch.ai agent registration, ASI:One/ACP integration, uAgents messaging, coordinator and provider agent wrappers, LangGraph workflow, and cross-agent Sentry traces. Work only on branch `feat/fetch-orchestration` and your assigned files. Do not edit Developer B's models, services, backend, seed data, or dashboard. Use the shared interface in Section 2 and local stub data immediately so you never wait for B. Verify actual SDK and official APIs; never invent MCP commands, autocomplete behavior, or card schemas. First achieve ASI:One -> Coordinator -> Transport and Destination -> ASI:One. Then integrate B's API, implement Maria and David, and produce real Agentverse URLs and ASI:One evidence. Never contact real emergency services or dispatch volunteers. All data and messages are synthetic and labeled DEMO. Run your integration tests at every checkpoint, report commit hashes and exact handoff JSON.

## 10. Exact Claude Code prompt for Developer B

> You are Developer B on Doorstep. Read `Doorstep_Implementation_Master_Spec.md` and `Doorstep_Two_Developer_Execution_Plan.md` completely. You exclusively own typed data contracts, synthetic seed data, deterministic safety and matching, consent, state transitions, SQLite/event timeline, local FastAPI backend, messaging simulator, API tests, and optional map/dashboard. Work only on branch `feat/domain-backend` and your assigned files. Do not edit Developer A's Fetch.ai agents, LangGraph graph, Fetch adapter, or registration configuration. Implement the shared interface in Section 2 with a standalone API so you never wait for A. First get Maria and David passing API-only tests. Then hand A stable example payloads and endpoints. All data must be fictional; do not send real emergency alerts, contact 911, dispatch real volunteers, or mark anyone safe from an unconfirmed pickup. Build optional Base44/dashboard work only after core tests pass. Report commit hashes, sample JSON, and test results at each checkpoint.

## 11. Who handles final submission?

**A:** Agentverse agent URLs, ASI:One shared chat, Fetch.ai explanation, live agent demonstration, Sentry trace screenshots, sponsor integration verification.

**B:** README/setup, synthetic data statement, safety/limitations, demo reset, demo video editing, optional dashboard, test summary and measured demo metrics.

**Both:** verify current sponsor requirements, rehearse the same three-minute story, check every claim and demo label, submit on time. Do not assert partnerships or operational emergency capability.

## 12. First actions right now

1. Confirm official hackathon start and whether project code is allowed yet.
2. Both read the master spec and this split plan.
3. Decide who is A and B. A creates the repository and interface commit. B starts independent model/API tests immediately.
4. Exchange branch URLs and the contract JSON, not entire code files in chat.
5. Run the H2 gate before building more features.

**Final rule:** A resident request is not an assignment. An assignment is not a pickup. A pickup is not an arrival. A referral is not completed assistance.

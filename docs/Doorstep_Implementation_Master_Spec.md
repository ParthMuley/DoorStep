# DOORSTEP | LA Hacks 2026 Master Build Specification

**Version:** 1.0 | **Audience:** Two-person hackathon team, Claude Code, Codex | **Date:** October 16, 2026  
**Status:** Implementation proposal, not a deployed emergency service.  
**Primary target:** Fetch.ai ASI:One Agent Challenge. Secondary targets: Photon, Sentry, Applied Intelligence; Base44 only if feasible.

> **One-sentence product:** Doorstep helps trusted community organizations coordinate accessible transportation and immediate recovery support for residents affected by disasters, while showing exactly which assistance requests have been accepted and completed.

> **Safety boundary:** This hackathon project is a **synthetic-data simulation**. It must not dispatch volunteers, contact emergency services, send real emergency alerts, make live evacuation routing decisions, or claim to be operational emergency infrastructure. A real deployment would require agreements with authorized organizations, safety review, privacy controls, and approved procedures.

---

## 0. READ THIS FIRST: BUILD CONTRACT FOR CODING AGENTS

Claude Code and Codex must treat this document as the shared source of truth. Do not silently reinterpret safety rules, product scope, or sponsor requirements. When an external API or SDK capability is uncertain, inspect current official docs or the installed SDK before coding; record the finding in `docs/integration-decisions.md`. Do not invent endpoints, agent registration commands, ACP message formats, Photon features, or ASI:One card schemas. If unavailable, implement a clearly labeled simulation adapter and preserve the same interface.

**Order of work:** (1) Fetch.ai end-to-end proof of concept, (2) reliable synthetic coordination flow, (3) clear resident experience and confirmations, (4) Sentry, (5) Photon and dashboard polish. Every milestone must run and have tests before moving on. Keep a demo-safe offline fallback. Do not store API keys in code, logs, screenshots, or the repository.

**Important:** Hackathon rules about pre-event coding, team size, and sponsor eligibility must be confirmed by the team. If the event forbids pre-event project coding, do not implement the project until the permitted start time. Research, accounts, and throwaway SDK tests must also be checked against the event rules.

### Non-negotiable product rules

1. Only **officially verified** alerts can activate the simulated official-warning flow. A user's report creates a report requiring verification, never an official evacuation order.
2. **No automated volunteer dispatch inside or through an active evacuation-order zone.** The simulated system flags such requests for authorized emergency-response handling; no live 911 integration.
3. Volunteers are simulated as **preapproved by a fictional partner organization**, not verified by an LLM. They can decline without pressure.
4. Matching uses **deterministic code**, not an LLM, for accessibility, capacity, service area, and assignment safety constraints.
5. A match is **not** a pickup; a pickup is **not** an arrival. Green means arrival confirmed at an agreed destination, never merely assigned.
6. Unanswered SMS, failed delivery, and explicitly requested assistance are different facts. Silence is **not** proof of danger or evacuation.
7. Every unfulfilled request remains visible as unresolved; never say help is coming without a real provider acceptance (in the demo, clearly simulated).
8. The resident controls whether their relevant information is shared with each participating service. No full profile sent to every agent.
9. A simulated emergency-service acknowledgment means only **request received**, not that responders have been dispatched.
10. The resident-facing text must not suggest this prototype replaces official alerts, 911, or professional emergency services.

---

## 1. PRODUCT AND DEMO DECISION

### Primary user

A community or aid organization already responsible for helping enrolled residents with accessibility or transportation needs. Its staff may operate a coordination dashboard, but the system handles routine communication and information gathering automatically. The organization owns unresolved cases and escalation rules.

### Beneficiary

An enrolled resident who cannot easily leave home without assistance, or their authorized caregiver. Examples include mobility limitations, wheelchair requirements, portable oxygen equipment, service animals or pets, limited transportation, and language preferences. Do not assume all older adults or disabled people need evacuation help.

### Hackathon scope: ONE full journey, TWO scenarios

**Scenario A: Successful coordination.** A fictional resident needs wheelchair-accessible transportation, space for a dog, and an accessible temporary destination. An official **simulated** warning activates a check-in. Resident replies in Spanish. Independent provider agents return their actual simulated capacity. An authorized pickup outside the active-order area is proposed and accepted under preapproved simulation rules. Pickup and arrival are separately confirmed. The resident consents to sharing limited needs with a recovery provider; a simulated follow-up request is accepted.

**Scenario B: Unsafe or unavailable assistance.** A second fictional resident is inside the active-order zone, or no eligible provider exists. The system does **not** dispatch a volunteer. It prepares a structured escalation for a simulated authorized response service, receives an acknowledgment, and clearly displays **unresolved: assistance not confirmed**. If no response, the case remains unresolved with a visible next step.

**The wow moment:** The same ASI:One request initiates a multi-organization workflow; agents discover providers with different capabilities; the system coordinates one full confirmed journey while refusing an unsafe assignment and showing an honest unresolved case. A supplemental map shows progress but does not substitute for the ASI:One workflow.

### Explicit non-goals for this weekend

No real resident enrollment, live wildfire perimeter predictions, public volunteer marketplace, real emergency dispatch, real shelter booking, FEMA application filing, insurance claims, clinical advice, automated prioritization of human lives, background-check service, payment processing, or full disaster case-management platform. Avoid building a generic marketplace or adding a LangGraph security swarm unrelated to the resident outcome.

---

## 2. WHAT MAKES FETCH.AI CENTRAL

Do not implement four agents that are merely functions with a shared database. Model **independent service providers** with separate records and clear boundaries.

| Agent | Owns | Responds to | Must not do |
|---|---|---|---|
| Doorstep Coordinator | Case workflow, approvals, consent, state transitions, audit log | ASI:One user commands | Pretend to be official dispatch |
| Community Support Agent | Synthetic resident needs, contact preferences, trusted contacts | Limited resident-intake queries | Share whole resident database |
| Transport Provider Agent | Synthetic approved vehicles, service areas, capabilities, acceptance status | Availability requests, proposed assignments | Claim routes are wildfire-safe |
| Destination Provider Agent | Synthetic accessible destinations, pet policy, capacity, acceptance status | Accommodation queries, reservations | Claim space is confirmed without acceptance |
| Recovery Support Agent (P1) | Synthetic caseworker availability, follow-up request state | Consent-scoped recovery referral | Make eligibility or medical decisions |
| Emergency Escalation Simulator (P1) | Synthetic receipt acknowledgments | Escalation requests | Impersonate or contact real 911 |

**Minimum P0:** Coordinator + Transport Provider + Destination Provider as independently addressable Fetch.ai agents. Community intake can initially be a coordinator-owned module; recovery and escalation can be simple independent simulated agents if time permits. More agents are not automatically better.

### Required sponsor integration path

1. Register at least the Coordinator on Agentverse and make it discoverable through ASI:One.
2. Confirm current **Agent Chat Protocol (ACP)** and the required ASI:One interaction method from official docs. Test a real chat request and response.
3. Coordinator communicates with at least two independently running provider agents using documented Fetch.ai uAgents messaging/protocols.
4. The complete primary coordination journey is accessible in ASI:One: start, status, proposed arrangement, simulated approval, final confirmations, and unresolved case summary. Do not require the external map to finish the workflow.
5. Capture actual Agentverse URLs, a public ASI:One shared chat URL if supported, repository URL, and demo video for submission.
6. **ASI:One Interactive Cards:** inspect the developer Card Playground; use only documented schemas. P1: an arrangement approval card and a final status card; plain-text fallback mandatory.
7. **Fetch MCP registration:** investigate whether an official authenticated MCP server can register/manage Agentverse agents. Use it if supported; otherwise document and use the official registration workflow. Do not invent MCP tool names.
8. **ASI autocomplete API:** verify its actual purpose. Do not use it for agent-to-agent transport unless official documentation confirms that use; use uAgents messaging for the primary path.
9. **ASI:One coding assistant:** optional developer convenience, not a product requirement.

---

## 3. RESIDENT EXPERIENCE: SIMPLE FROM START TO FINISH

### Enrollment (simulated)

The resident or approved caregiver answers one question at a time, in a preferred language. Example: "I use a wheelchair, have a small dog, need help getting into a van, and prefer Spanish." The intake model extracts *candidate* fields. It must ask the person to confirm critical details before storing them. The user can update or withdraw consent.

Minimum fields: pseudonymous resident ID; synthetic zone; preferred language; chosen contact channel; mobility/transfer needs; wheelchair transport needs; oxygen equipment transport consideration; pets/service animals; trusted caregiver contact (optional); accessibility needs for destination; consent flags; last confirmed date. Store no real diagnosis or sensitive identifiers in demo data.

### Simulated warning

An authorized demo control triggers a **simulated official warning** for Zone 3. A resident receives a clearly labeled **DEMO** check-in. The wording asks whether they need assistance; it does not issue evacuation orders or make safety promises.

### Resident response

Offer minimal responses: `1 NEED HELP`, `2 I HAVE A PLAN`, `3 ALREADY LEFT`, `4 CALL ME`, plus free text. Respect language preference. Use approved, human-reviewed safety wording for alerts; LLMs may parse responses but must not improvise official evacuation guidance.

### Assistance arrangement

Coordinator asks independent providers for availability and capabilities, runs deterministic matching, checks the simulated zone rules, and presents an eligible proposal. In real life, the operating organization would define what can be preapproved; for the demo, use an explicit simulated authorization flag. The volunteer/provider accepts or declines freely. A resident is never told a ride is confirmed before provider acceptance.

### Pickup and arrival

Separate events: provider accepted; pickup confirmed by resident and provider (or authorized caregiver alternative); arrival confirmed by appropriate participants. A one-time code may help confirm contact, but it does not prove safety. Expire codes, limit attempts, and provide an accessible alternative. Do not display green until arrival is confirmed.

### Recovery handoff

After confirmed simulated arrival, ask: "Would you like me to share your accessibility needs with a recovery support organization to request help finding temporary accommodation?" On consent, share only necessary details, request service, record `REQUESTED`, `ACCEPTED`, or `UNRESOLVED`; do not imply housing has been secured unless a provider actually confirms a simulated reservation.

---

## 4. CASE AND MESSAGE STATES

### Separate three dimensions

**Resident assistance status:** `NEEDS_ASSISTANCE`, `PROVIDER_ACCEPTED`, `PICKUP_CONFIRMED`, `ARRIVAL_CONFIRMED`, `REQUIRES_COORDINATOR`, `UNKNOWN`.

**Communication status:** `NOT_SENT`, `SENT`, `DELIVERED`, `DELIVERY_FAILED`, `REPLIED`, `NO_REPLY_AFTER_DEADLINE`, `UNKNOWN`. Delivery receipts may not be supported by every provider; don't invent them.

**Service request status:** `DRAFT`, `PROPOSED`, `AWAITING_PROVIDER`, `ACCEPTED`, `DECLINED`, `CANCELED`, `COMPLETED`, `UNRESOLVED`.

**Map colors:** red = assistance needed; yellow = provider accepted; blue = pickup confirmed; green = arrival confirmed; black = coordinator attention; gray = unknown. Always include a text legend and accessible non-color labels.

### Transition rules

- `NEEDS_ASSISTANCE -> PROVIDER_ACCEPTED` only with accepted assignment and appropriate authorization.
- `PROVIDER_ACCEPTED -> PICKUP_CONFIRMED` only with recorded pickup evidence.
- `PICKUP_CONFIRMED -> ARRIVAL_CONFIRMED` only with destination/arrival evidence.
- Canceled or expired assignments cannot become active due to delayed replies.
- Multiple concurrent offers may be queried, but only one active accepted assignment per resident and service type. Use atomic database updates and idempotency keys.
- No provider available or no acknowledgment -> `UNRESOLVED` and an explicit owner/escalation status.
- If active-order zone or forbidden road is involved, block ordinary volunteer assignment and use simulated authorized escalation.

---

## 5. SYSTEM DESIGN

### High-level flow

```text
ASI:One coordinator chat
         |
         v
Doorstep Coordinator (Fetch.ai + LangGraph state machine)
         |
         +--> Community intake / resident record (consent checked)
         |
         +--> Transport provider agent (separate availability store)
         |
         +--> Destination provider agent (separate capacity store)
         |
         +--> Deterministic constraints + authorization gate
         |
         +--> Photon adapter (demo/test messaging only)
         |
         +--> Recovery / emergency escalation simulator
         |
         +--> Event log + Sentry spans
         |
         +--> ASI:One status/cards; optional Base44 map
```

### Recommended technology

- Python 3.11+; FastAPI for local provider simulation, callbacks, and dashboard read API.
- Fetch.ai uAgents and current ACP-compatible integration for discovery and ASI:One.
- LangGraph for long-running coordinator state transitions, pause/resume, and failure branches. Do not let an LLM override the deterministic safety gate.
- SQLite for hackathon demo state; each provider gets separate tables or databases and access restrictions. Use transactions for assignment acceptance. Consider Postgres only if required by deployment.
- Pydantic models for strict payload validation.
- Sentry SDK for error monitoring, traces, logs, and agent monitoring where supported. Meet sponsor's requirement of two products beyond error monitoring, and document an actual bug found/fixed.
- Photon Spectrum for test SMS if proactive sends, inbound callbacks, and sender identity can be verified. Otherwise a **clearly labeled messaging simulator**.
- Base44 for optional operator map/dashboard only if it can consume the read API and update reliably; otherwise a lightweight fallback.
- Mapping: synthetic zone map first. Optional Leaflet/OSM display. Do **not** infer wildfire-safe routes from a general road routing API. For the demo use a synthetic graph with explicit blocked edges and label routes as illustrative only.

### LLM responsibilities versus fixed code

**LLM:** understand resident free text; propose clarifying questions; translate noncritical messages; summarize status for coordinator; extract candidate accessibility needs with confidence/confirmation flags.

**Fixed code:** consent checks; matching eligibility; official-alert trust flag; zone restrictions; approved-provider verification; message deduplication; state transitions; escalation triggers; final status labeling; audit log.

### Matching eligibility

Hard constraints: verified/approved provider; correct vehicle accessibility and transfer capability; capacity; pet/service-animal accommodation as applicable; suitable destination; availability; service area; no restricted-zone entry or forbidden road; organization approval policy. Do not treat language preference as a reason to deny assistance: use multilingual communication support. Oxygen needs may require specialized handling; do not assume an ordinary volunteer can safely accommodate them.

After filtering eligible providers, rank candidates by non-safety factors such as availability and estimated travel distance within the **simulated safe service area**. Do not have an LLM rank the worthiness of residents. If supply is insufficient, show shortage and escalate using partner-defined policy.

---

## 6. DATA CONTRACTS (START HERE)

All IDs are opaque synthetic strings; all times are UTC ISO 8601; include `schema_version`, `case_id`, `event_id`, `correlation_id`, and `created_at` where applicable.

```json
{
  "schema_version": "1.0",
  "case_id": "case_maria_001",
  "resident_id": "resident_001",
  "zone_id": "zone_3",
  "needs": {
    "wheelchair_accessible_vehicle": true,
    "transfer_assistance": true,
    "portable_oxygen_equipment": false,
    "pet_count": 1,
    "preferred_language": "es",
    "destination_accessibility": ["step_free_entry"]
  },
  "consent": {
    "contact_for_checkins": true,
    "share_transport_needs": true,
    "share_destination_needs": true,
    "share_recovery_needs": false
  },
  "resident_status": "NEEDS_ASSISTANCE",
  "communication_status": "REPLIED"
}
```

```json
{
  "schema_version": "1.0",
  "request_id": "req_001",
  "case_id": "case_maria_001",
  "service_type": "accessible_transport",
  "zone_id": "zone_3",
  "requirements": {
    "wheelchair_accessible_vehicle": true,
    "transfer_assistance": true,
    "pet_count": 1
  },
  "status": "AWAITING_PROVIDER",
  "idempotency_key": "case_maria_001:transport:v1"
}
```

```json
{
  "schema_version": "1.0",
  "assignment_id": "assign_001",
  "case_id": "case_maria_001",
  "provider_id": "transport_org_a",
  "provider_approved": true,
  "service_area_allowed": true,
  "zone_rule": "OUTSIDE_ACTIVE_ORDER",
  "provider_response": "ACCEPTED",
  "authorization": "SIMULATED_PREAPPROVED",
  "status": "PROVIDER_ACCEPTED",
  "confirmed_pickup_at": null,
  "confirmed_arrival_at": null
}
```

```json
{
  "schema_version": "1.0",
  "escalation_id": "esc_002",
  "case_id": "case_david_002",
  "reason": "ACTIVE_EVACUATION_ORDER_ZONE",
  "recipient": "SIMULATED_AUTHORIZED_RESPONSE_SERVICE",
  "status": "ACKNOWLEDGED_REQUEST_ONLY",
  "assistance_confirmed": false
}
```

**Implement typed models** for Resident, Caregiver, Organization, Volunteer/Provider, VehicleCapability, Destination, ConsentGrant, Case, AlertEvent, MessageEvent, ServiceRequest, Assignment, StatusEvent, VerificationEvent, and Escalation. Avoid storing sensitive details in generic logs.

### API and message operations (logical contracts, not claimed official Fetch.ai endpoints)

- `start_demo_warning(zone_id, scenario_id)`
- `register_resident(profile, consent)`
- `submit_resident_response(case_id, text, language)`
- `find_transport(request)` -> eligible provider offers
- `find_destination(request)` -> eligible destination offers
- `propose_assignment(case_id, offer_id)` -> proposal
- `accept_assignment(assignment_id, provider_identity)` -> accepted/declined
- `confirm_pickup(assignment_id, evidence)` -> status
- `confirm_arrival(assignment_id, evidence)` -> status
- `request_recovery_handoff(case_id, consent)` -> referral status
- `escalate_case(case_id, reason)` -> simulated acknowledgment only
- `get_case_status(case_id)` -> full evidence-backed timeline

Do not expose `start_demo_warning` publicly without demo authorization. Validate identities and permissions on every write operation.

---

## 7. LANGGRAPH WORKFLOW

Graph nodes: `load_case` -> `validate_alert` -> `check_consent` -> `send_checkin` -> `await_response` -> `extract_and_confirm_needs` -> `discover_providers` -> `get_offers` -> `check_safety_and_constraints` -> `request_provider_acceptance` -> `await_acceptance` -> `notify_resident` -> `await_pickup` -> `await_arrival` -> `request_recovery_consent` -> `recovery_handoff` -> `final_summary`.

Branches: missing consent -> ask/stop; unverified alert -> report-only; no reply -> notify approved contacts/mark unknown; delivery failure -> alternate approved channel or unresolved; active order zone -> simulated emergency escalation, no volunteer assignment; provider declines -> search other eligible provider; no eligible provider -> unresolved; provider timeout -> query status before retry to prevent duplicate assignment; resident declines -> cancel; arrival unconfirmed -> stay in progress and flag follow-up.

**Persistence:** Store state transitions durably. Use deterministic case IDs, correlation IDs, idempotency keys, and max retries. Implement a replayable event timeline. The graph may pause while awaiting messages; no busy-waiting loops. Use short simulated delays for demo only.

**Testing swarm:** Not in P0. If time remains, build a tiny scenario generator and deterministic checker to test failures; never let a security swarm run in the resident-facing flow. Sentry value should come from a real trace and a documented fix, not extra agents for their own sake.

---

## 8. PHOTON AND MULTILINGUAL EXPERIENCE

**P0 fallback:** A local messaging simulator with two fictional phone numbers and event injection; all messages visibly marked `DEMO`. **P1 real integration:** Photon Spectrum only after verifying the actual API, sandbox availability, sender validation, webhook signatures, proactive messaging, and reply handling. Never message uninvolved real people. A teammate's opted-in test phone is permitted only within provider and hackathon rules.

Sample approved check-in (English): "DOORSTEP DEMO: A simulated warning affects your test area. Do you need transportation planning help? Reply 1 NEED HELP, 2 HAVE A PLAN, 3 ALREADY LEFT. This is a simulation, not an emergency alert."

Spanish: use a reviewed translation, not unchecked LLM-generated emergency instructions. The demo can accept Spanish free text and translate it for internal understanding; preserve original text alongside parsed fields. Show confirmation questions before using extracted needs.

Message safety: distinguish queued/sent/delivered/replied/no reply/failed. Rate limit. Deduplicate inbound messages. Unknown sender must not change a resident case. Delayed acceptance must not revive a canceled assignment.

---

## 9. DASHBOARD AND ASI:ONE CARDS

**Primary interface:** ASI:One chat. Required commands or natural-language equivalents:

- "Start the simulated Zone 3 readiness check."
- "Show residents who requested assistance."
- "Show available suitable providers and why each matches."
- "Approve the simulated arrangement for Maria." (if approval needed)
- "Show confirmed pickup, arrival, and unresolved cases."
- "Request Maria's recovery handoff after consent."

**Optional Interactive Cards:** check actual Card Playground API first. Ideal cards: `Case Summary`, `Assistance Proposal`, `Provider Accepted`, `Arrival Confirmed`, `Escalation: Unresolved`. Every card needs a plain-text fallback and must show evidence-backed status.

**Supplementary Base44 dashboard:** synthetic map, filters by state, case timeline, provider capacity, unresolved queue, consent-safe details, message status, and a clear "SIMULATION" banner. Avoid using real home coordinates or real fire perimeters. The map must not imply that a route is safe or a rescue has occurred without confirmation. Accessibility: keyboard support, readable text, color-independent labels.

---

## 10. SENTRY PLAN

Instrument coordinator and provider agents with a shared correlation ID. Capture spans for alert validation, resident outreach, message receipt, provider discovery, eligibility filtering, offer requests, provider acceptance, pickup/arrival confirmation, and escalation. Record structured, redacted logs and errors. Add Session Replay only if the dashboard supports it and privacy settings are correct.

**At least two Sentry products beyond error monitoring**, per the supplied sponsor description: choose Tracing + Logs (and optionally AI monitoring/Session Replay). Capture an actual bug, show trace evidence, fix it, and rerun the scenario. Candidate bugs to test: duplicated assignment on delayed reply, stale provider availability, lost correlation ID, incorrectly green status, or missing consent check. Do not fabricate the bug story.

Metrics: time to provider acceptance; time to confirmed arrival (simulated); number of unserved cases; unsuitable matches (must be zero); duplicate active assignments (must be zero); wrong status transitions (must be zero); coordinator actions; provider response latency; unknown communication statuses.

---

## 11. TESTS AND ACCEPTANCE CRITERIA

### Unit tests

- Wheelchair user is never matched to non-accessible vehicle.
- Required transfer support, oxygen handling, pets/service animals, and destination accessibility are respected.
- Unapproved provider cannot be assigned or access a resident address.
- Inside-order-zone assignment to ordinary volunteer is always blocked.
- Closed synthetic road edge cannot be used by synthetic route planner.
- Matching does not assign more capacity than available.
- Resident priority is not invented by an LLM.
- Without consent, recovery details are not shared.
- Unknown sender cannot update status.
- Duplicate or delayed webhook does not create duplicate assignments.
- Provider acceptance does not set pickup or arrival.
- Pickup does not set arrival.
- No reply does not imply rescue needed or safe.
- Failed message delivery does not imply no reply.
- Escalation acknowledgment does not imply assistance accepted.

### Integration tests

1. ASI:One -> Coordinator -> Transport Provider -> Coordinator -> ASI:One.
2. Coordinator -> Destination Provider -> compatible destination result.
3. Synthetic check-in -> response -> parsed needs -> user confirmation.
4. Proposed assignment -> provider accept -> pickup confirmation -> arrival confirmation.
5. Recovery referral only after consent; response tracked separately.
6. Unsafe zone -> no volunteer dispatch -> simulated escalation acknowledgment -> unresolved.
7. Provider decline -> alternate eligible provider or unresolved.
8. Restart coordinator mid-workflow -> state resumes without duplicate action.
9. Text simulator / Photon webhook receives repeated reply -> idempotent handling.
10. Sentry trace spans correlate across agent messages.

### Acceptance gate for P0

- A fresh user can run Scenario A from ASI:One without relying on the map.
- A fresh user can run Scenario B from ASI:One; no unsafe volunteer assignment occurs.
- Two independent provider agents actually communicate using Fetch.ai tooling.
- All displayed statuses correspond to persisted evidence.
- Tests pass locally and from a clean checkout with sample environment variables.
- Demo never implies live emergency capabilities.

---

## 12. IMPLEMENTATION PLAN: 36-HOUR HACKATHON

**Before H0 (only if permitted):** Confirm rules, create accounts, inspect current Fetch.ai/Photon/Base44/Sentry docs, identify credentials, test hello-worlds in throwaway repos. Do not write project code before the allowed start.

| Time | Developer A: Fetch.ai + agent workflow | Developer B: backend + UX + testing | Gate |
|---|---|---|---|
| H0-H2 | Create repo, confirm ACP/Agentverse, coordinator hello-world | Pydantic schemas, seed synthetic cases, basic API | Contract and SDK verified |
| H2-H6 | Coordinator-to-transport and destination agent calls | Matching constraints + state transitions + unit tests | Real agent-to-agent exchange |
| H6-H10 | ASI:One start/status commands, LangGraph core | Simulated check-ins and response handling | Scenario A through proposal |
| H10-H14 | Acceptance, pickup/arrival, recovery handoff | Evidence records, synthetic zone restrictions | Full Scenario A |
| H14-H18 | Unsafe-zone branch and escalation simulator | Scenario B, unresolved statuses, safety tests | Full Scenario B |
| H18-H22 | Sentry spans/logs and real bug investigation | Minimal dashboard/map and case timeline | Core frozen and traceable |
| H22-H26 | Photon integration if proven; otherwise simulator | ASI cards if supported; otherwise text fallback | Sponsor enhancements |
| H26-H30 | Run end-to-end tests, deploy agents, capture URLs | Accessibility QA, demo seed, backup recording | Feature freeze |
| H30-H36 | Demo rehearsal, public shared chat, README | Video, Devpost, sponsor descriptions, final test | Submitted |

**Cut order if behind:** voice, extra languages beyond one, real map routing, Base44 extras, recovery agent sophistication, cards, Photon live SMS. **Never cut:** Fetch.ai real integration, the safe-zone gate, correct status semantics, consent, Scenario B, and clear simulation labeling. If Scenario A is not working by H14, stop adding features and fix the core.

### Two-person collaboration rules

Use one GitHub repo; protect `main`; small PRs; shared `schemas/` package; single `.env.example`; feature flags `USE_PHOTON`, `USE_BASE44`, `USE_CARDS`, `SIMULATION_MODE`. One person owns Fetch registration and ACP; the other owns deterministic matching/state. Agree on schema before parallel coding. Run `pytest` and a smoke test before merging. Record decisions in `docs/decisions.md`.

---

## 13. SUGGESTED REPOSITORY STRUCTURE

```text
doorstep/
  README.md
  .env.example
  pyproject.toml
  docs/
    integration-decisions.md
    decisions.md
    safety-and-limitations.md
    demo-script.md
    sponsor-checklist.md
  src/doorstep/
    models/
      resident.py
      case.py
      provider.py
      events.py
    agents/
      coordinator.py
      transport_provider.py
      destination_provider.py
      recovery_provider.py
      escalation_simulator.py
    workflows/
      coordination_graph.py
      transitions.py
    services/
      intake.py
      matching.py
      safety_rules.py
      consent.py
      assignment_store.py
      verification.py
      event_log.py
    integrations/
      fetch_adapter.py
      photon_adapter.py
      message_simulator.py
      sentry_setup.py
    api/
      app.py
      routes.py
    demo/
      seed.py
      scenarios.py
      synthetic_zone_graph.py
  dashboard/                    # optional Base44 project or fallback
  tests/
    unit/
    integration/
    e2e/
  scripts/
    run_demo.sh
    smoke_test.sh
    reset_demo.sh
```

Use the exact structure only if it fits the actual SDK and deployment environment. Avoid overengineering for a two-person sprint.

---

## 14. DEMO SCRIPT (3 MINUTES)

**0:00-0:25 | The human problem.** "When an alert says leave, some people need help to act on it. And after they leave, their support needs don't disappear." Cite verified local wildfire sources in the final slides. Do not assert unverified casualty counts or current-fire status.

**0:25-0:50 | Activate.** ASI:One: "Start simulated Zone 3 check-in." Show synthetic residents and messages. One resident replies in Spanish describing wheelchair and pet needs.

**0:50-1:25 | Agent collaboration.** Coordinator discovers transport and destination providers, obtains compatible offers, rejects a closer but unsuitable vehicle, and requests provider acceptance.

**1:25-1:50 | Confirm.** Show accepted provider, then separate pickup and arrival confirmations. The resident becomes green only after arrival. Ask for consent and create a recovery follow-up.

**1:50-2:20 | Safety case.** Second resident is inside an active simulated order zone. Ordinary volunteer dispatch is blocked; a simulated emergency-response service acknowledges the request. Status remains "assistance unconfirmed".

**2:20-2:45 | Engineering proof.** Show Agentverse profiles, ASI:One transcript, Sentry cross-agent trace, and one real bug fixed. Map is supporting visual only.

**2:45-3:00 | Close.** "Doorstep connects trusted aid organizations so residents don't have to navigate emergency assistance alone. This is a simulation designed for partner-led coordination, not a live rescue system."

Prepare a backup recording and a deterministic reset command. Never simulate real emergency alerts to non-consenting recipients.

---

## 15. SUBMISSION AND VALIDATION CHECKLIST

- [ ] Official LA Hacks rules reviewed, including pre-event coding and sponsor entry limits.
- [ ] Current Fetch.ai hackpack reviewed and required ACP/Agentverse/ASI:One behavior confirmed.
- [ ] Coordinator Agentverse URL accessible.
- [ ] Independent provider agent(s) registered and reachable.
- [ ] ASI:One shared chat shows the complete primary workflow.
- [ ] Public GitHub repo with setup, environment variables, architecture, tests, and honest simulation notes.
- [ ] Short demo video, preferably with a backup offline recording.
- [ ] ASI:One cards tested against real schema if used.
- [ ] Photon eligibility and Spectrum integration verified if entering its track.
- [ ] Sentry has two eligible products beyond error monitoring and an authentic debugging story.
- [ ] Base44 console is substantially built in Base44 if entering its challenge.
- [ ] No real personal or medical data, real addresses, real dispatch calls, or real evacuation instructions.
- [ ] Pitch statistics checked against primary or reliable dated sources.
- [ ] Clearly identify simulated providers and prospective, not existing, partner organizations.
- [ ] Every case state can be explained from recorded evidence.

### Evidence and competition positioning

The prior Doorstep plan cites Eaton Fire reporting and discusses registry objections, communication failures, and 211-related gaps. Those are **background motivations**, not proof that Doorstep reduces evacuation deaths. Existing tools and networks include emergency alerting, emergency profiles, 211 referrals, disaster case management, and referral platforms such as Unite Us. Do not claim no solution exists. Our hypothesis is that **accessible, consent-based, cross-organization coordination with confirmed handoffs** could reduce administrative effort and unresolved requests. A real pilot is required to establish that benefit.

Recommended evaluation: compare the same synthetic scenario with a basic manual spreadsheet workflow versus Doorstep. Record time to *confirmed provider acceptance*, incorrect matches, duplicate assignments, and unresolved cases. Do not invent improvements or equate simulated performance with lives saved.

---

## 16. QUESTIONS FOR THE TEAM: DECISIONS TO CONFIRM

These questions do **not** block initial architecture work; defaults are given to avoid stalling.

| Question | Proposed default until answered |
|---|---|
| Is the hackathon still ~36 hours with two developers? | Yes; verify official schedule. |
| Is the primary demo evacuation coordination or post-disaster recovery? | Evacuation assistance + one small recovery handoff. |
| Do you have real organizational partners or approved APIs? | No; synthetic providers only. |
| Is Photon SMS available for proactive sends and inbound replies? | Unknown; build simulator first. |
| Is Base44 required for your sponsor strategy? | Optional; ASI:One first. |
| Are you comfortable showing only synthetic addresses and routes? | Yes, mandatory for this prototype. |
| What language besides English should the demo show? | Spanish; reviewed safety text. |
| Will real volunteers ever be contacted during the demo? | No; only consenting teammate test numbers if Photon works. |
| Who controls simulated approval of assistance arrangements? | Preapproved rules for nonrestricted zones; human/simulated authority for exceptions. |
| Which provider agents will be independent? | Transport and destination providers at minimum. |

### Ask the team immediately if any of these become true

1. A proposed implementation would contact a real emergency service or real resident.
2. An API requires sharing sensitive information with an unapproved party.
3. A desired card, MCP registration, or autocomplete feature cannot be found in official documentation.
4. The official sponsor rules conflict with the planned external dashboard or workflow.
5. A demo flow cannot be completed inside ASI:One.
6. A proposed feature would infer route safety or autonomously dispatch volunteers into active evacuation zones.

---

## 17. COPY-PASTE PROMPTS FOR CLAUDE CODE AND CODEX

### Prompt A: Planning and verification

> Read `Doorstep_Implementation_Master_Spec.md` in full. Treat its safety boundaries and acceptance tests as mandatory. First inspect the repository and the installed Fetch.ai SDK. Verify the current official ACP, Agentverse, and ASI:One integration methods, plus whether MCP-based registration and Interactive Cards are supported. Produce a concise implementation plan and `docs/integration-decisions.md`. Do not invent endpoints or implement live emergency dispatch. If pre-event coding is prohibited, stop after planning.

### Prompt B: Core implementation

> Implement P0 in this order: typed models and synthetic seed data; deterministic matching and safety checks with unit tests; independently running Fetch.ai coordinator, transport, and destination agents; ASI:One full Scenario A; Scenario B with unsafe-zone block and simulated escalation; event-sourced status timeline; consent-gated recovery handoff. After each milestone run tests and a smoke test. Keep provider state isolated. Do not add optional UI or SMS until both scenarios work.

### Prompt C: Sponsor polish and QA

> Add Sentry tracing and logs across agent messages with a shared correlation ID, document a real defect found and fixed, and add an ASI:One Interactive Card only if the documented schema supports it. Integrate Photon Spectrum in test mode only if proactive messaging and inbound replies are verified; otherwise retain the clearly labeled messaging simulator. Add a supplemental dashboard only after the ASI:One flow is complete. Run all safety tests, rehearse the three-minute demo, and generate the submission checklist with actual URLs and evidence.

### Prompt D: Code review

> Audit the implementation against every non-negotiable rule and acceptance criterion in the master spec. Prioritize unsafe dispatch, false arrival claims, consent leaks, wrong-provider matches, stale replies, duplicate assignments, unverified external APIs, misleading emergency messages, and missing ASI:One steps. Report severity, exact file and line, reproducible test, and suggested fix. Do not claim readiness unless both scenarios pass end-to-end.

---

## 18. SOURCE NOTES AND LIMITATIONS

**User-provided baseline:** `Doorstep LA Hacks Plan.md` (October 15, 2026), including its source list, original four-agent architecture, sponsor strategy, and build schedule. This master spec intentionally modifies the baseline to add safety boundaries, independent provider agents, consent, recovery handoff, and clearer statuses, based on subsequent discussion. **It is a proposal, not a verified official integration manual.**

Before slides or deployment, verify original reports and official guidance, including LA County's 2025 wildfire after-action materials, 211 LA's recovery coordination reports, the latest Fetch.ai hackpack, and current sponsor documentation. Avoid claiming a Malibu incident is ongoing without a current dated source. Avoid implying that partner organizations have endorsed Doorstep.

**Final engineering principle:** A resident request is not an assignment. An assignment is not a pickup. A pickup is not an arrival. A referral is not completed assistance. Make every one of these distinctions visible.

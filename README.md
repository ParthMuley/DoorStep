# Doorstep (LA Hacks 2026, Fetch.ai track)

> **DOORSTEP DEMO: SIMULATION ONLY.** Every resident, organization, volunteer, address, phone number, alert and road in this project is synthetic. Doorstep does **not** send real alerts, contact 911 or emergency services, dispatch real volunteers, or recommend wildfire-safe routes. It is a prototype of partner-led coordination, not emergency infrastructure.

Doorstep helps trusted community organizations get accessible transport and recovery help to residents who can't easily leave home during a disaster. It also shows, honestly, which requests have been accepted, picked up, delivered or are still unresolved.

## How it works

**Before a disaster**
1. Residents register (or sign up in their own ASI:One chat and link it with a one-time code): address, needs (wheelchair, transfer help, oxygen, pets…), emergency contacts and consent.
2. Partner organizations register their volunteers **where they are**: vehicle, capacity, and which needs they can handle.

**During a disaster**
3. The **Calamity Checker** agent reads the government evacuation feed every 2 minutes (Cal OES format; synthetic in the demo).
4. Residents inside an official evacuation-zone polygon get a check-in in their language.
5. At the same time, the **Volunteer Network** agent asks the nearest organizations that handle this calamity type whether their volunteers are available.
6. The **Matching** agent pairs each resident who asks for help with an available volunteer whose capabilities cover every need, plus an accessible shelter, nearest first. The rules are deterministic code; no LLM decides eligibility.
7. The **News** agent reports road closures; only *official* closures block roads.
8. The **Route** agent requests an illustrative HERE route that avoids evacuation-order zones and official closures.
9. The volunteer accepts, and only then is the resident told "help is on the way", with an ETA that is an estimate, not a guarantee.
10. Pickup and arrival are confirmed separately. A case turns green only at confirmed arrival.

    **Silence:** after 15 minutes without an answer, a volunteer counts as not available, and a resident goes to the coordinator's follow-up list. Silence never means safe.

**After evacuation**
11. With consent, the **Post-Calamity** agent refers the resident to recovery organizations (temporary housing, insurance guidance…). A referral is not completed help.

**Safety cases:**
- A resident inside an active **evacuation-order** zone never gets an ordinary volunteer. The case is escalated to a simulated authorized service and stays **unresolved**.
- If the feed goes **stale**, nothing is matched or routed, and nobody is called safe.

## Architecture

```text
ASI:One  ──►  Doorstep agent (Chat Protocol, ASI:One API tool calling, LangGraph, Interactive Cards)
                │  Fetch.ai agent messages
   ┌────────────┼──────────────┬───────────────┬──────────┬────────┬───────────────┐
Calamity    Volunteer       Matching       Post-Calamity   News     Route      Escalation
Checker     Network                                               (HERE)     Simulator
   └────────────┴──────────────┴──────┬────────┴──────────┴────────┴───────────────┘
                                      │ HTTP (contract v2.1, docs/interface-contract.md)
                         Doorstep backend (FastAPI)
              deterministic rules: zones · consent · matching · states · routes
                       │                                │
        MongoDB doorstep_users                MongoDB doorstep_partners
   residents · cases · messages ·        organizations · regions (area → orgs →
   alerts · closures · events            local volunteers / shelters) · agents
```

- **Agents (Developer A):** 8 Fetch.ai uAgents on Agentverse. See `docs/dev-a-notes.md` and `docs/integration-decisions.md`.
- **Backend (Developer B):** FastAPI and MongoDB. See `docs/dev-b-notes.md`. The status words come from here, and agents and cards show them verbatim.

| Path | Owner | What |
|---|---|---|
| `src/doorstep/agents/`, `workflows/`, `integrations/fetch_*` | A | agents, LangGraph, ASI:One, cards |
| `src/doorstep/models/`, `services/`, `api/`, `demo/` | B | backend, rules, MongoDB, synthetic data |
| `tests/integration/` / `tests/unit/` | A / B | agent tests / backend tests |
| `docs/DOORSTEP_V2_TEAM_PLAN.md` | both | the shared plan (revision 3) |
| `docs/interface-contract.md` | B | the HTTP contract (v2.1) |

## Setup

Requires Python 3.11 or 3.12.

```bash
python3.12 -m venv .venv && source .venv/bin/activate      # Windows: py -3.12 -m venv .venv
pip install -e ".[dev]"                                     # backend needs: fastapi uvicorn pydantic httpx pymongo shapely (+ mongomock for tests)
cp .env.example .env                                        # never commit .env
```

**MongoDB.** Without `MONGODB_URI`, the backend runs on an in-memory MongoDB (mongomock); data is lost when it stops. For persistent data:
```bash
scripts/start_mongo.sh                    # MongoDB 7 in Docker, bound to 127.0.0.1
export MONGODB_URI=mongodb://127.0.0.1:27017
```

## Run

```bash
scripts/run_backend.sh          # http://127.0.0.1:8000, auto-seeds the synthetic demo
scripts/reset_demo.sh [full]    # deterministic reset; `full` loads the bigger demo cast (docs/demo-cast.md)
scripts/smoke_test.sh           # temp backend + Scenarios A (Maria), B (David), C (stale feed) over HTTP, no keys needed
scripts/check_integration.sh    # ONE command: backend tests + A's agent tests + A's tests on B's real routes + smoke (--quick ~20 s)
PYTHONPATH=src python -m pytest tests/unit -q                                    # backend unit tests (offline)
DOORSTEP_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 PYTHONPATH=src python -m pytest tests/unit/test_real_mongo.py
```

Agents: see `docs/dev-a-notes.md` (agent seeds, Agentverse mailboxes, `scripts/run_agents.ps1`).

**Public deploy (Render + MongoDB Atlas, free):** see [docs/deploy-render.md](docs/deploy-render.md). It's needed only so the route-map image has a public https address for ASI:One.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `SIMULATION_MODE` | `true` | the backend refuses to start otherwise |
| `DEMO_AUTH_TOKEN` | `change-me-local-demo-token` | `Authorization: Bearer …` on writes |
| `NETWORK_AGENT_TOKEN` | `change-me-network-agent-token` | `X-Agent-Token` on Volunteer Network routes |
| `MONGODB_URI` | unset (in-memory) | e.g. `mongodb://127.0.0.1:27017` or Atlas |
| `MONGODB_USERS_DB` / `MONGODB_PARTNERS_DB` | `doorstep_users` / `doorstep_partners` | |
| `ALERT_STALE_AFTER_SECONDS` | `900` | feed age after which zones are STALE |
| `OUTREACH_MAX_ORGS` | `3` | nearest orgs contacted per alert |
| `AUTO_ESCALATION_ACK` | `true` | set `false` when the Escalation agent runs |
| `ROUTE_MAX_AVOID_AREAS` | `20` | HERE's polygon limit; above it, route constraints are refused (never truncated) |
| `DOORSTEP_AGENT_TOKEN` / `ROUTE_AGENT_TOKEN` / `CALAMITY_AGENT_TOKEN` | `change-me-…` | `X-Agent-Token` for linking/registration/replies, map uploads, the deadline sweep |
| `REPLY_DEADLINE_MINUTES` | `15` | after it a silent volunteer is NO_REPLY and a silent resident goes to the unresolved queue |
| `PUBLIC_BASE_URL` | unset | public https base for map links (Render's `RENDER_EXTERNAL_URL` is used if unset) |
| `ASI_ONE_API_KEY`, `HERE_API_KEY`, agent seeds | none | agents only; never committed |

## Safety and limitations

- **Synthetic data only.** No real people or addresses. Every resident and volunteer message starts with `DOORSTEP DEMO` and says it is a simulation.
- **No dispatch, no 911.** An escalation acknowledgment means only "request received" (`assistance_confirmed` is always false).
- **Deterministic safety core.** Zones, eligibility, consent, state changes and route acceptance are tested code. The ASI:One API may parse free text and write summaries, but it never decides any of these.
- **Truthful states.** Request ≠ assignment ≠ pickup ≠ arrival ≠ completed help. Silence is not danger or safety, and a failed delivery is not "no reply".
- **Zones.** Check-ins come from official zone polygons; a radius is awareness only. Missing or stale data is `UNKNOWN`/`STALE`, never safe. Live feed data is display-only.
- **Roads.** Only official closures block roads; news reports are cautions. "No report" never means open. Routes are labeled *illustrative only, not for live evacuation*.
- **Consent.** Purpose-specific (check-in, transport, destination, recovery). Each organization receives only the fields it needs.
- **Known gaps:**
  - The Spanish message templates were reviewed and signed off on 2026-10-18 (`docs/spanish-review.md`).
  - Token auth is demo gating, not production security.
  - The seeded ASI:One link codes (`MARIA-4821`, …) are public because they're in the repo. That's fine for synthetic people only.
  - The road map and polygons are fictional.
  - A real deployment would need agreements with authorized organizations, a safety review and privacy controls.

## Docs

- [Team plan (rev 3)](docs/DOORSTEP_V2_TEAM_PLAN.md)
- [Interface contract v2.1](docs/interface-contract.md)
- [Backend handoff notes](docs/dev-b-notes.md)
- [Backend decisions](docs/decisions.md)
- [Deploy on Render + Atlas](docs/deploy-render.md)
- [Agent notes](docs/dev-a-notes.md)
- [Master spec](docs/Doorstep_Implementation_Master_Spec.md)
- [Original two-developer plan](docs/Doorstep_Two_Developer_Execution_Plan.md)

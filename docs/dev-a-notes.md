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

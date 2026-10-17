# Developer A notes (Fetch.ai + orchestration)

Branch: `feat/fetch-orchestration`. Owns `src/doorstep/agents/`, `src/doorstep/workflows/`, `src/doorstep/integrations/fetch_adapter.py`, `src/doorstep/integrations/sentry_setup.py`, `tests/integration/fetch_*`, `docs/integration-decisions.md`, `pyproject.toml`, `.env.example`.

## Handoff log

Each entry: commit hash, sample JSON, how to run, tests run, known limitations.

### H0 — bootstrap
- Commit: _(fill after commit)_
- Contents: package skeleton, `pyproject.toml`, `.env.example`, `.gitignore`, `docs/interface-contract.md` v1.0, copies of both spec docs.
- For B: start `feat/domain-backend` from this commit. Implement the HTTP API in `docs/interface-contract.md` §3. Note the design decision there: provider agents return raw offers; B's `…/evaluate` endpoints decide eligibility.
- Known limitations: no agent code yet.

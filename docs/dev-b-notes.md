# Developer B handoff notes: domain engine + backend

Everything is synthetic and labeled DEMO. No real SMS, 911, or dispatch.

## Run

```bash
scripts/run_backend.sh            # http://127.0.0.1:8000, DB at var/doorstep_demo.db (auto-seeded)
scripts/reset_demo.sh             # deterministic reset (API if running, else reseeds the DB file)
scripts/smoke_test.sh             # temp backend + Scenario A and B over HTTP
PYTHONPATH=src .venv/bin/python -m pytest tests/unit -q
```

Env: `SIMULATION_MODE=true` (required), `DOORSTEP_DEMO_TOKEN`, `DOORSTEP_DB_PATH`, `DOORSTEP_API_URL`.
Dependencies to add to `pyproject.toml` (owned by A): `fastapi`, `uvicorn`, `pydantic>=2`, `httpx`; dev: `pytest`.
No other third-party packages are used.

All routes except `/health` need the header `X-Demo-Token: <token>`.

## Contract operations → HTTP

| Operation | Method + path | Body |
|---|---|---|
| `start_demo_warning` | `POST /demo/warnings` | `{zone_id, scenario_id?, correlation_id?}` |
| (user report, never activates) | `POST /reports` | `{zone_id, text}` |
| `register_resident` | `POST /residents` | `{profile: Resident, consent?: Consent}` |
| `submit_resident_response` | `POST /cases/{case_id}/responses` | `{text, sender, language?, external_id?}` |
| confirm needs (API alternative to SMS YES/NO) | `POST /cases/{case_id}/needs/confirm` | `{confirmed, confirmed_by, needs?}` |
| `find_transport` | `POST /transport/find` | `{case_id}` |
| `find_destination` | `POST /destinations/find` | `{case_id}` |
| `propose_assignment` | `POST /assignments/propose` | `{case_id, offer_id}` |
| `accept_assignment` | `POST /assignments/{id}/respond` | `{provider_id, accept: true\|false}` |
| pickup details (approved and accepted provider only) | `GET /assignments/{id}/pickup-details?provider_id=` | - |
| `confirm_pickup` | `POST /assignments/{id}/pickup` | `{evidence: {confirmations: [{party, party_id}]}}` |
| `confirm_arrival` | `POST /assignments/{id}/arrival` | same |
| `request_recovery_handoff` | `POST /cases/{case_id}/recovery` | `{consent, granted_by}` |
| recovery provider response (simulated) | `POST /recovery/{referral_id}/respond` | `{provider_id, accept}` |
| `escalate_case` | `POST /cases/{case_id}/escalate` | `{reason}` (`ACTIVE_EVACUATION_ORDER_ZONE`, `NO_ELIGIBLE_PROVIDER`, `PROVIDER_TIMEOUT`, `COORDINATOR_REQUESTED`) |
| `get_case_status` | `GET /cases/{case_id}` | - |
| list / unresolved queue | `GET /cases?status=&unresolved=true` | - |
| reset | `POST /demo/reset` | - |
| provider inventories, zone graph | `GET /providers`, `GET /zones` | - |

Every write accepts an optional `correlation_id`. If it is omitted, the case's own ID (`corr_<case_id>`) is used. Every timeline event carries it, so A can pass the Sentry trace ID through.

Errors: `{"error": code, "message", "reasons": [...]}` with 401 (token), 403 (wrong identity), 404, 409 (conflict, late reply, invalid transition), 422 (safety rejection, missing consent, insufficient evidence).

`GET /cases/{id}` returns `case`, `map{color,label}`, `evidence{provider_accepted,pickup_confirmed,arrival_confirmed,destination_accepted,timeline_replay_matches_status}`, `unresolved`, `next_step`, `offers`, `assignments`, `verifications`, `escalations`, `recovery_referrals`, `messages`, `timeline`. It also returns **`summary_text`**, a plain-text, evidence-backed summary that can serve as the ASI:One text fallback.

## Message simulator injection

| Inject | Path |
|---|---|
| inbound SMS routed by sender (unknown sender → 403, no change) | `POST /sim/inbound {sender, text, external_id?}` |
| delivery receipt / failure | `POST /sim/delivery {message_id, delivered}` |
| reply deadline passed | `POST /sim/cases/{case_id}/no-reply-deadline` |
| escalation service stops acknowledging | `POST /sim/escalation-ack {acknowledge: false}` |
| outbox | `GET /sim/messages?case_id=` |
| duplicate reply | resend the same `external_id` |
| provider decline | `POST /assignments/{id}/respond {accept: false}` |

## Seed (fictional)

- `case_maria_001` / `resident_001`, phone `sms:+15555550101`, zone_3, Spanish, wheelchair, transfer help, 1 dog, step-free destination.
- `case_david_002` / `resident_002`, phone `sms:+15555550102`, caregiver `caregiver_002` (`sms:+15555550103`), zone_3n (active order), transfer help, oxygen.
- Transport: `transport_org_a` (match), `_b` closer sedan, not accessible; `_c` not approved; `_d` no pets; `_e` eligible alternate behind a closed road.
- Destinations: `dest_center_a` (match), `dest_library_b` not step-free, `dest_hotel_c` no pets.

## Pure functions for A's provider agents

Provider agents can keep their own inventories and still use the same rules:
`doorstep.services.matching.find_transport(request, providers, graph)` / `find_destination(...)` with
`doorstep.demo.synthetic_zone_graph.build_demo_graph()`. The backend re-checks every proposal against current state.

## Example: Maria transport offers (abridged)

```json
{"request": {"request_id": "req_001", "case_id": "case_maria_001", "service_type": "accessible_transport",
             "status": "PROPOSED", "idempotency_key": "case_maria_001:transport:v1"},
 "eligible_count": 2,
 "offers": [
  {"offer_id": "offer_req_001_transport_org_a", "provider_id": "transport_org_a", "eligible": true,
   "reasons": ["MEETS_ALL_HARD_CONSTRAINTS"], "estimated_distance_km": 4.0},
  {"offer_id": "offer_req_001_transport_org_e", "provider_id": "transport_org_e", "eligible": true,
   "reasons": ["MEETS_ALL_HARD_CONSTRAINTS"], "estimated_distance_km": 11.0},
  {"offer_id": "offer_req_001_transport_org_b", "provider_id": "transport_org_b", "eligible": false,
   "reasons": ["NOT_WHEELCHAIR_ACCESSIBLE", "NO_TRANSFER_ASSISTANCE"], "estimated_distance_km": 0.0}],
 "route_note": "Illustrative route on a fictional graph; not a safety assessment."}
```

## Known limitations

- Spanish templates still need review by a fluent speaker (decision B-14).
- No one-time pickup codes yet. Evidence is party confirmations only.
- Token auth is demo gating only.
- Sentry API logs are not added yet (P1).

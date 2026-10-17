# Developer B handoff notes: domain engine + backend

Implements `docs/interface-contract.md` **v1.0** (Section 3). Everything is synthetic and labeled DEMO. No real SMS, 911, or dispatch.

## Run

```bash
scripts/run_backend.sh            # http://127.0.0.1:$DOORSTEP_API_PORT (default 8000); auto-seeds var/doorstep_demo.db
scripts/reset_demo.sh             # deterministic reset (via the API if running, else reseeds the DB file)
scripts/smoke_test.sh             # temp backend + Scenario A and B over real HTTP
PYTHONPATH=src python -m pytest tests/unit -q
```

Scripts load `.env` when it exists. Variables used: `SIMULATION_MODE=true` (required), `DEMO_AUTH_TOKEN`, `DOORSTEP_API_PORT`, `DOORSTEP_API_URL`, optional `DOORSTEP_DB_PATH`. Tested on Python 3.11 and 3.14. Only `fastapi`, `uvicorn`, `pydantic`, `httpx` and `pytest` are used, and all are already in `pyproject.toml`.

## Contract v1.0 conformance

- Paths, request bodies, response fields, status codes (201 on create, 200 on a repeated idempotency key) and error codes all follow Section 3.
- Write endpoints need `Authorization: Bearer $DEMO_AUTH_TOKEN`. GET endpoints are open.
- `X-Correlation-ID` takes precedence over a `correlation_id` in the body. It is echoed in every response body and response header, and stored on every timeline event.
- Every response carries `schema_version: "1.0"`. Errors look like `{schema_version, error, detail, correlation_id}`, plus `reasons[]` with the specific rule codes.
- Business-rule refusals are **409**: `UNSAFE_ZONE`, `PROVIDER_NOT_APPROVED`, `OFFER_NOT_ELIGIBLE`, `CONSENT_MISSING`, `INVALID_TRANSITION`, `NOT_AUTHORIZED`, `NEEDS_NOT_CONFIRMED`. Others: 401 (bad token), 403 (wrong identity / unknown sender), 404, 422 `VALIDATION_ERROR` (unknown or invalid fields).

## Behaviour A should know about

1. **Needs must be confirmed first.** `.../evaluate` returns 409 `NEEDS_NOT_CONFIRMED` until the resident replies SI/YES to the confirmation question.
2. **Approval and location come from B's registry**, not from the offer. An unknown `provider_id` gets `PROVIDER_NOT_APPROVED`. The route (closed-road check) starts from the registry's base zone. An offer's optional `base_zone` is used only when the registry has none.
3. **Offers are re-checked at proposal time** for expiry (`valid_until`), approval, zone and consent. A stale or expired offer gets 409.
4. **One proposal, two providers.** `POST /cases/{id}/assignments` with both `transport_offer_id` and `destination_offer_id` returns one `assignment_id`. **Both providers respond on that same id** through `/acceptance`, each with its own `provider_id`. Arrival requires the destination provider to have **ACCEPTED**: the spec forbids treating space as confirmed without acceptance.
5. **Pickup evidence:** `provider_confirmed` and (`resident_confirmed` or `caregiver_confirmed`). **Arrival evidence:** a `DESTINATION_CHECKIN` whose `destination_provider_id` matches the accepted destination, or resident plus transport provider. The optional `confirmations: [{party, party_id}]` list (proposed for v1.1) is checked against the real participants, and a mismatch is rejected.
6. **Recovery without consent** returns 409 `CONSENT_MISSING`. The decline is still recorded and nothing is shared. `granted_by` is `RESIDENT` or `CAREGIVER`.
7. **Escalation reasons:** `ACTIVE_EVACUATION_ORDER_ZONE` (the case must actually be inside an order zone), `NO_ELIGIBLE_PROVIDER`, `PROVIDER_TIMEOUT`, `NO_REPLY_AFTER_DEADLINE` (communication status must be `NO_REPLY_AFTER_DEADLINE`), `COORDINATOR_REQUESTED`. Acknowledgment is always `assistance_confirmed: false`.
8. **Extra fields in `GET /cases/{id}`**, beyond v1.0 and safe to ignore: `sector_id`, `needs`, `destination_assignment`, `map{color,label}`, `unresolved`, `next_step`, `evidence{...}`, and **`summary_text`**, a plain-text, evidence-backed status that can be shown directly in ASI:One. Other responses also include `next_step` and `duplicate` where useful.
9. **`submit_resident_response`** accepts an optional `external_id` (or `idempotency_key`). Resending the same value is ignored as a duplicate.

## Extras (B's test hooks, not in the contract)

| Purpose | Endpoint |
|---|---|
| recovery provider response (simulated) | `POST /recovery-referrals/{referral_id}/response {provider_id:"recovery_org_demo", decision}` |
| pickup point lookup (accepted, approved provider only) | `GET /assignments/{id}/pickup-details?provider_id=` (token required) |
| inbound SMS routed by sender | `POST /sim/inbound {sender, text, external_id?}` |
| delivery receipt / failure | `POST /sim/delivery {message_id, delivered}` |
| reply deadline passed | `POST /sim/cases/{case_id}/no-reply-deadline` |
| escalation service stops acknowledging | `POST /sim/escalation-ack {acknowledge:false}` |
| outbox, registry, zone graph | `GET /sim/messages?case_id=`, `GET /providers`, `GET /zones` |

## Seed (fictional; matches contract Section 5)

- `case_maria_001` / `resident_001` "Maria (synthetic)": sender `sim_phone_maria`, `zone_3` sector B (outside the order), Spanish, wheelchair, transfer help, 1 dog, step-free destination.
- `case_david_002` / `resident_002` "David (synthetic)": sender `sim_phone_david`, caregiver `sim_phone_david_caregiver`, `zone_3` sector A (**active order**), wheelchair.
- Registry: `transport_org_a` (approved, base zone_2), `transport_org_b` (approved, closer sedan), `transport_org_c` (**not approved**), `transport_org_d`, `transport_org_e` (based behind a closed road); `destination_org_a/b/c`.
- Sample raw offers in A's format: `doorstep.demo.seed.transport_offers()` / `destination_offers()` (`offer_t_001..005`, `offer_d_001..003`). A's agent fixtures can mirror these.

Expected for Maria: eligible `offer_t_001` (rank 1) and `offer_t_005` (rank 2, detour). Rejected: `offer_t_002` (`NOT_WHEELCHAIR_ACCESSIBLE`, `NO_TRANSFER_ASSISTANCE`), `offer_t_003` (`PROVIDER_NOT_APPROVED`), `offer_t_004` (`PETS_NOT_ALLOWED`). Destination: `offer_d_001`.
Expected for David: every offer rejected with `ACTIVE_ORDER_ZONE`, `escalation_required: true`, and proposal returns 409 `UNSAFE_ZONE`.

## Proposed contract v1.1 (needs A's approval)

1. Evidence may include `confirmations: [{party, party_id}]`. Already accepted, and checked when present.
2. Transport offers may include `base_zone`. Already accepted, but the registry value wins.
3. Approval comes from B's registry only (already how it works).
4. The destination provider accepts through `/assignments/{id}/acceptance` with its own `provider_id` (needed before arrival).

## Known limitations

- Spanish templates still need review by a fluent speaker.
- No one-time pickup codes beyond the `code_verified` flag.
- Bearer token is demo gating only.
- No Sentry on the backend yet.

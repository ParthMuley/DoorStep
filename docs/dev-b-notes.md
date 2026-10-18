# Developer B handoff notes: domain engine + backend

Implements `docs/interface-contract.md` **v1.0** (Section 3). Everything is synthetic and labeled DEMO. No real SMS, 911, or dispatch.

## Run

```bash
scripts/run_backend.sh            # http://127.0.0.1:$DOORSTEP_API_PORT (default 8000); auto-seeds on first start
scripts/start_mongo.sh            # optional: local MongoDB 7 in Docker, then export MONGODB_URI=mongodb://127.0.0.1:27017
scripts/reset_demo.sh             # deterministic reset (via the API if running, else reseeds MongoDB)
scripts/smoke_test.sh             # temp backend (in-memory MongoDB) + Scenario A and B over real HTTP
PYTHONPATH=src python -m pytest tests/unit -q
```

**Storage is MongoDB** with two databases: `doorstep_users` (residents, cases, messages, assignments, alerts, events…) and `doorstep_orgs` (organizations / provider registry, provider events). Without `MONGODB_URI`, the backend uses an in-memory mongomock (data is lost when it stops). Tests always use mongomock; `create_app(":memory:")` still works, so A's in-process tests need no change. Optional real-server test: `DOORSTEP_TEST_MONGODB_URI=… pytest tests/unit/test_real_mongo.py`.

Env: `SIMULATION_MODE=true` (required), `DEMO_AUTH_TOKEN`, `DOORSTEP_API_PORT`, `DOORSTEP_API_URL`, `MONGODB_URI`, `MONGODB_USERS_DB`, `MONGODB_ORGS_DB`, `USE_MONGOMOCK`. Dependencies to add to `pyproject.toml` (A owns it): `pymongo`, dev `mongomock` (plus `shapely`, `openai` for later steps).

## v2.1 endpoints available now (plan rev 3: location-first partners, one Volunteer Network agent)

Responses carry `schema_version: "2.0"`.

**Auth.** Writes need `Authorization: Bearer $DEMO_AUTH_TOKEN`. Network routes also need `X-Agent-Token: $NETWORK_AGENT_TOKEN` (local default `change-me-network-agent-token`). Network routes are `/alerts/{id}/outreach`, `/alerts/{id}/volunteers/{vid}/availability` and `/assignments/{id}/accept`. B checks every `org_id` against the volunteer or site (otherwise 403 `WRONG_ORG`).

**Partners.** `doorstep_partners`: canonical `organizations` plus `regions` (area → orgs → only their local volunteers and sites). Seed regions:
- `la_county:east_valley`: Sarah, Joe, Maya, Tom, Rina; civic shelter;
- `la_county:south_valley`: Lee; recovery housing;
- `la_county:westside`: Red Cross shelter;
- `sf:mission`: Red Cross volunteer Sam, never contacted for the LA fire.

**Registration:**
- `POST /organizations` (canonical; updates copy into every region);
- `POST /regions` (no overlaps);
- `POST /regions/{region_id}/orgs/{org_id}/volunteers`, `/shelter_sites` and presence. Location is checked; a wrong region → 409 that names the right one.
- `GET /organizations`, `GET /regions/near?alert_id=|zone_id=|lat=&lon=&radius_km=` (+ `calamity_type`, `service`).
- `POST /residents` is unchanged.

**Agents.** `PUT /agents/{role} {agent_address}` at startup; `GET /agents`. B returns `network_agent_address` in `/alerts/ingest` and in matches.

**Loop for the agents** (scripted in `doorstep.demo.scenarios.run_scenario_{a,b,c}_v2`; `scripts/smoke_test.sh` runs v1 + v2):
1. `POST /demo/alerts/trigger {"action":"ISSUE","preset":"ZONE_3_WILDFIRE"}`. The Calamity agent polls `GET /demo/feeds/caloes` every 120 s and posts it to `POST /alerts/ingest`. The response lists `affected_cases`, `checkins_sent`, `outreach_orgs` (with `region_ids`, nearby only) and `network_agent_address`.
2. The Volunteer Network agent calls `POST /alerts/{alert_id}/outreach {}`. B texts the nearby orgs' approved volunteers and returns who was asked.
3. Volunteers answer by `/sim/inbound` (YES/SI/NO), or the network agent posts `POST /alerts/{id}/volunteers/{vid}/availability {org_id, available}`. Live counts: `GET /alerts/{id}/outreach`; `POST /sim/outreach/{id}/deadline` marks the rest NO_REPLY.
4. The resident replies and confirms needs (`/cases/{id}/responses`).
5. `POST /matches/propose {case_id}`. Use `create_proposal:false` to preview; otherwise you get a 201 match with the volunteer reserved and a `region_id`.
6. `POST /assignments/{id}/accept {org_id, volunteer_id | site_id, decision}` (network token). A volunteer ACCEPTED triggers "help is on the way" + an ETA estimate. DECLINED returns `next_alternate`.
7. Pickup: the resident texts `RECOGIDO` / `PICKED UP` (or send `resident_confirmed`), then `POST /assignments/{id}/pickup {"type":"VOLUNTEER_AND_RESIDENT_CONFIRMATION","volunteer_confirmed":true}`.
8. Arrival: `POST /assignments/{id}/arrival {"type":"SHELTER_CHECKIN","shelter_org_id","site_id","shelter_confirmed":true}`. Green; the volunteer is released.
9. David: propose returns `ORDER_ZONE`. Then `POST /cases/{id}/escalate`, then `POST /escalations/{id}/ack` (`AUTO_ESCALATION_ACK=false` when the Escalation agent runs).
10. Scenario C: `{"action":"FREEZE_FEED","freeze_age_minutes":30}`, then ingest. Zones go STALE and matching refuses.
10b. Closures + routes (B6), after acceptance:
    - The News agent reads `GET /demo/feeds/closures` (official) and `GET /demo/feeds/news`, extracts candidates (ASI:One), and posts `POST /closures/ingest {source:{source_id, source_type: OFFICIAL_SIMULATION|NEWS|REAL_WORLD_CONTEXT}, items:[{source_item_id, headline, raw_text, extraction_method, candidate:{road_name, claimed_status}}]}`. B sets the state; `GET /closures` lists them.
    - The Route agent calls `POST /routes/constraints {assignment_id}` and gets stops, `avoid_areas` (order zones + official closures, as polygons) and `cautions`. It calls HERE, then `POST /routes/previews {route_request_id, polyline, distance_m, duration_s, provider_notices}` → `ILLUSTRATIVE_ONLY` (with ETA) / `REFUSED` / `NO_ROUTE_CONFIRMED`.
    - Demo control: `POST /demo/closures/trigger {action: PUBLISH_OFFICIAL|LIFT_OFFICIAL|PUBLISH_NEWS, road_name}`.
11. Post-calamity (B5):
    - After arrival the resident replies `SI` (consent).
    - The Post-Calamity agent calls `POST /cases/{id}/recovery {consent:{share_recovery_needs:true, granted_by:"RESIDENT"}, help_types:["TEMPORARY_HOUSING","INSURANCE_GUIDANCE"]}`. That creates one referral per type, to the nearest org offering it, with a minimal `shared_payload` to forward.
    - The network agent answers for the recovery org: `POST /recovery/{referral_id}/respond {org_id, decision: ACCEPTED|DECLINED|COMPLETED, evidence?}` (network token). COMPLETED needs `{"type":"SIMULATED_SERVICE_CONFIRMED","reference"}`. DECLINED returns `next_alternate`.
    - `GET /cases/{id}` shows a `recovery` block with `status`, `referrals` and `housing_secured`.

**Card data (B7):** `GET /dashboard/summary` (counts, unresolved queue, alerts, outreach, closures, recovery), `GET /dashboard/cases` (coarse locations + progress), and `progress_steps` on `GET /cases/{id}`. `GET /health` reports version 2.2.0 and feed freshness.

**B8 (contract v2.2, contract §5.13):**
- **Files:** `services/links.py` (link, unlink, register, invites, approve, pending), `services/deadlines.py` (15-minute reply deadline, one clock `deadlines.now`), `services/maps.py` (hosted route PNGs).
- **Agent tokens:** `api/security.py` `require_agent(...)`, one `X-Agent-Token` per agent role.
- **Sender check:** `engine._linked_sender`.
- **Deploy:** `render.yaml` + `docs/deploy-render.md`.
- **Tests:** `tests/unit/test_links_deadlines_maps.py`; A's rev 4/5/roster tests also pass against the real routes with the stand-ins off.

**Integration check (either developer, after any change):** `scripts/check_integration.sh` (or `--quick`).
- Stage 1: backend unit tests.
- Stage 2: A's agent tests as written.
- Stage 3: A's linking, registration and roster tests with A's stand-ins switched off (`scripts/checks/no_standins.py`), i.e. on B's real routes.
- Stage 4: the smoke test.
- Stage 5: real MongoDB, if `DOORSTEP_TEST_MONGODB_URI` is set.
- Needs Python 3.11/3.12 with `pip install -e ".[dev]"` (or `CHECK_PY=`). Forces offline mode (mongomock, no ASI:One calls).
- Its first run caught `_env.sh` exporting the old `MONGODB_ORGS_DB=doorstep_orgs`. It's now `MONGODB_PARTNERS_DB=doorstep_partners`. A local Mongo seeded before this fix needs `scripts/reset_demo.sh` once.

**v1 routes:** still mounted for A's old test (`tests/integration/test_fetch_backend_client.py`) and `workflows/backend_client.py`. A's agents no longer call any v1-only endpoint (they use `GET /cases/{id}` and the v2 routes). Remove them in one PR together with A's v1 client and test (plan §6.2).

**Removed (v2.0):** `/organizations/{id}/volunteers`, `/orgs/{id}/volunteers`, `/orgs/{id}/volunteers/{vid}/availability`, `/orgs/{id}/outreach`, `X-Org-Agent`. A's stand-ins for these should switch to the v2.1 routes above.

**Request for A (`.env.example`):** add `NETWORK_AGENT_TOKEN=` and `MONGODB_PARTNERS_DB=doorstep_partners`.

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
9. **Extra fields in raw offers are ignored, not trusted.** Your agents' `approved_by_partner`, `base_node`, `org_name`, `accepts_requests` and `valid_for_minutes` are accepted and dropped. Please send **`valid_until`** (absolute UTC time) so expiry is enforced, and `eta_minutes` if you want ETA ranking (without it, offers are ranked by fictional route distance). Checked against your real fixtures: Maria gets `transport_org_a` (then `_e`) and `destination_org_a`; David gets nothing eligible and `escalation_required: true`.
10. **`submit_resident_response`** accepts an optional `external_id` (or `idempotency_key`). Resending the same value is ignored as a duplicate.

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

- Spanish templates reviewed and signed off 2026-10-18 (`docs/spanish-review.md`, decision B-14 closed).
- No one-time pickup codes beyond the `code_verified` flag.
- Bearer token is demo gating only.
- No Sentry on the backend yet.

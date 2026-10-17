# Doorstep decisions (owned by Developer B)

Synthetic-data simulation only. These decisions cover the domain engine, backend, and simulator.

| # | Decision | Why |
|---|---|---|
| B-01 | New cases start `resident_status=UNKNOWN`, not `NEEDS_ASSISTANCE`. | Silence is not evidence. `NEEDS_ASSISTANCE` only after an explicit request. |
| B-02 | `Assignment.status` uses the **service** vocabulary (`AWAITING_PROVIDER`, `ACCEPTED`, `COMPLETED`, ...). Resident vocabulary (`PROVIDER_ACCEPTED`, ...) lives only on the case. | Keeps the three state dimensions separate. The master spec's sample JSON shows `status: PROVIDER_ACCEPTED` on an assignment; we read that as illustrative. |
| B-03 | `zone_3` is the simulated warning area (Maria). `zone_3n` is a child zone with an active simulated evacuation order (David). A warning for `zone_3` covers both. | One warning starts both scenarios. |
| B-04 | Edge `zone_3`–`zone_4` is closed. The planner avoids closed edges and every active-order zone, and labels routes "illustrative only". | Shows the blocked-road rule without claiming any route is safe. |
| B-05 | Pickup evidence = transport provider **and** resident/caregiver. Arrival evidence = resident/caregiver **and** destination or transport provider, plus an accepted destination assignment. | Spec Section 3: confirmations come from the right participants, at an agreed destination. |
| B-06 | Free-text parsing is deterministic keyword matching (EN/ES). It produces candidate needs only; nothing is used until the resident replies YES/SÍ (or `POST /cases/{id}/needs/confirm`). | No LLM needed for P0. An LLM extractor can be added later under the same confirm-first contract. |
| B-07 | No eligible transport means the request becomes `UNRESOLVED` and the case becomes `REQUIRES_COORDINATOR` automatically, with an explicit next step. Escalation is a separate, explicit call. | Every unfulfilled request stays visible; escalation leaves a record. |
| B-08 | Escalation acknowledgment is `ACKNOWLEDGED_REQUEST_ONLY` with `assistance_confirmed=false`, always. The no-acknowledgment branch is switched on with `POST /sim/escalation-ack`. | Spec rule 9. |
| B-09 | The simulator never makes up delivery receipts. Outbound messages stay `SENT` until a receipt is injected (`POST /sim/delivery`). | Spec Section 4: don't make up receipts. |
| B-10 | IDs (`req_001`, `assign_001`, `event_001`...) come from DB counters, so a reset followed by the same calls gives identical IDs. Case IDs are fixed per resident (`case_maria_001`, `case_david_002`). | `reset_demo.sh` must reproduce identical state. |
| B-11 | Every route except `/health` requires `X-Demo-Token` (env `DOORSTEP_DEMO_TOKEN`, local default `doorstep-local-demo-token`). Provider writes also check `provider_id` against the assignment and the approval list. | Plan Section 3: restrict mutation to demo-authorized callers. This is demo gating, not production auth. |
| B-12 | One active accepted assignment per (case, service type) is enforced by a partial unique index in SQLite. Acceptance runs in a `BEGIN IMMEDIATE` transaction. | Atomic acceptance; duplicate or delayed replies cannot create a second assignment. |
| B-13 | `request_recovery_handoff` requires `granted_by` (resident or caregiver ID). It does not require confirmed arrival. | Consent must be attributable. Gating on arrival is left to the coordinator workflow (A). |
| B-14 | The Spanish templates in `services/templates.py` are **not yet reviewed** by a fluent speaker. They must be reviewed before the demo. | Spec Section 8: use a reviewed translation. |
| B-15 | The backend refuses to start unless `SIMULATION_MODE=true`. | Spec safety boundary. |

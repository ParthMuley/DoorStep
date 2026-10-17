# Doorstep decisions (owned by Developer B)

Synthetic-data simulation only. These decisions cover the domain engine, backend, and simulator.

| # | Decision | Why |
|---|---|---|
| B-01 | New cases start `resident_status=UNKNOWN`, not `NEEDS_ASSISTANCE`. | Silence is not evidence. `NEEDS_ASSISTANCE` only after an explicit request. |
| B-02 | `Assignment.status` uses the **service** vocabulary (`AWAITING_PROVIDER`, `ACCEPTED`, `COMPLETED`, ...). Resident vocabulary (`PROVIDER_ACCEPTED`, ...) lives only on the case. | Keeps the three state dimensions separate. The master spec's sample JSON shows `status: PROVIDER_ACCEPTED` on an assignment; we read that as illustrative. |
| B-03 | `zone_3` is the simulated warning area. Residents live in its sectors: `zone_3_sector_b` (Maria, outside) and `zone_3_sector_a` (David, active simulated order). Case `zone_id` is `zone_3`; `sector_id` drives the zone rule and routing. An unknown location is `UNVERIFIED` and blocks assignment. | Matches contract v1.0 Section 5. One warning starts both scenarios. |
| B-04 | Edge `zone_3_sector_b`–`zone_4` is closed. The planner avoids closed edges and every active-order zone, and labels routes "illustrative only". | Shows the blocked-road rule without claiming any route is safe. |
| B-05 | Pickup = provider **and** resident/caregiver confirmed. Arrival = `DESTINATION_CHECKIN` by the accepted destination provider, **or** resident/caregiver plus transport provider, and always an accepted destination. Optional identified `confirmations` are checked against the real participants. | Contract v1.0 evidence format, plus identity checks proposed for v1.1. |
| B-06 | Free-text parsing is deterministic keyword matching (EN/ES). It produces candidate needs only; nothing is used until the resident replies YES/SÍ . | No LLM needed for P0. An LLM extractor can be added later under the same confirm-first contract. |
| B-07 | No eligible transport (including an empty offer list) means the request becomes `UNRESOLVED` and the case becomes `REQUIRES_COORDINATOR` automatically, with an explicit next step. Escalation is a separate, explicit call. | Every unfulfilled request stays visible; escalation leaves a record. |
| B-08 | Escalation acknowledgment is `ACKNOWLEDGED_REQUEST_ONLY` with `assistance_confirmed=false`, always. The no-acknowledgment branch is switched on with `POST /sim/escalation-ack`. | Spec rule 9. |
| B-09 | The simulator never makes up delivery receipts. Outbound messages stay `SENT` until a receipt is injected (`POST /sim/delivery`). | Spec Section 4: don't make up receipts. |
| B-10 | IDs (`assign_001`, `evt_001`, `resp_001`...) come from DB counters, so a reset followed by the same calls gives identical IDs. Case IDs are fixed per resident (`case_maria_001`, `case_david_002`). | `reset_demo.sh` must reproduce identical state. |
| B-11 | Write endpoints require `Authorization: Bearer $DEMO_AUTH_TOKEN`; reads are open. Provider writes also check `provider_id` against the assignment and the registry. | Contract v1.0 Section 3. Demo gating, not production auth. |
| B-12 | One active accepted assignment per (case, service type) is enforced by a partial unique index in SQLite. Acceptance runs in a `BEGIN IMMEDIATE` transaction. | Atomic acceptance; duplicate or delayed replies cannot create a second assignment. |
| B-13 | `request_recovery_handoff` requires `granted_by` (`RESIDENT`/`CAREGIVER`, mapped to the party ID). No consent means 409 `CONSENT_MISSING`, with the decline still recorded. Confirmed arrival is not required. | Consent must be attributable. Contract v1.0 3.10. |
| B-14 | The Spanish templates in `services/templates.py` are **not yet reviewed** by a fluent speaker. They must be reviewed before the demo. | Spec Section 8: use a reviewed translation. |
| B-15 | The backend refuses to start unless `SIMULATION_MODE=true`. | Spec safety boundary. |
| B-16 | B no longer owns provider inventories. A's provider agents send raw offers; B evaluates them against a **partner approval registry** (approval + base zone). Approval is never taken from the offer. | Contract v1.0 design note: providers never read B's database. |
| B-17 | A proposal pairing transport and destination is stored as two linked assignment rows under one public `assignment_id`. Each provider accepts on that id with its own `provider_id`. | Keeps the one-accepted-per-service unique index, and destination acceptance stays explicit. |
| B-18 | Offers are re-evaluated at proposal time (expiry, approval, zone, consent). Expired or unparseable `valid_until` means rejected. | Stale availability must not slip through. |
| B-19 | Safety and business-rule refusals are HTTP 409 with contract codes; request validation is 422. | Contract v1.0 Section 3. |

# Doorstep Transport Provider (DEMO)

**Simulation only. Fictional organizations and vehicles. Does not dispatch real vehicles or volunteers.**

An independent provider agent in the Doorstep demo. It owns its own synthetic inventory of partner-approved accessible vehicles and answers the Doorstep Coordinator over Fetch.ai messaging.

- Reports raw capability and capacity: wheelchair access, transfer assistance, oxygen handling, pets, seats, service zones.
- Does not decide eligibility. The coordinator's deterministic matching does that.
- Decides freely whether to accept or decline a proposed assignment. Decisions are idempotent.
- Receives only consent-scoped needs, never a resident's name, phone number, or pickup point before acceptance.

Talks to: Doorstep Coordinator. Messages: `OfferRequest`/`OfferResponse`, `AcceptRequest`/`AcceptResponse` (schema 1.0).

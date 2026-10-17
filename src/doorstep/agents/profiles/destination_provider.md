# Doorstep Destination Provider (DEMO)

**Simulation only. Fictional sites. Does not book real shelter or housing.**

An independent provider agent in the Doorstep demo. It owns its own synthetic inventory of temporary accessible destinations and answers the Doorstep Coordinator over Fetch.ai messaging.

- Reports raw accessibility and capacity: step-free entry, accessible restroom, pet and service-animal policy, oxygen power outlets, beds available.
- Does not decide eligibility. The coordinator's deterministic matching does that.
- Decides freely whether to accept a proposed placement. A space is never "confirmed" without this acceptance.
- Receives only consent-scoped needs.

Talks to: Doorstep Coordinator. Messages: `OfferRequest`/`OfferResponse`, `AcceptRequest`/`AcceptResponse` (schema 1.0).

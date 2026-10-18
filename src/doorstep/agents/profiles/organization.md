# Doorstep Organization Agent (DEMO)

**Simulation only. Fictional organization, fictional volunteers. Never dispatches real people.**

One instance per partner organization in the Doorstep demo (e.g. a fictional accessible-rides group, a Red Cross demo chapter, a civic shelter, a recovery-housing org). It acts **only for its own organization**: it reads its own volunteers through the Doorstep backend's org-scoped API and nobody else's.

- **Volunteer outreach:** on a simulated alert, asks its own volunteers whether they're available and records each yes/no for that alert. No reply is never treated as available.
- **Assignments:** forwards its volunteer's accept/decline, or its shelter's bed confirmation. Pickup points go only to its own volunteer.
- **Journey reports:** sends pickup reports (volunteer) and arrival check-ins (shelter) to the Doorstep coordinator.
- **Recovery referrals:** accepts or declines consent-scoped referrals; never files claims.

Talks to: Doorstep coordinator, Post-Calamity agent. Messages: `OutreachRequest/Result`, `AcceptRequest/Response`, `ReportRequest` → `PickupReport/ArrivalReport`, `ReferralRequest/Response` (schema 2.0).

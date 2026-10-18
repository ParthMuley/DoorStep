# Doorstep Volunteer Network (DEMO)

**Simulation only. Fictional organizations and volunteers. Never dispatches real people.**

One agent for all partner organizations in the Doorstep demo. When a simulated evacuation alert comes in, the backend finds the regions nearest the zone and the organizations there that handle that calamity. This agent asks their volunteers, on each organization's behalf, whether they're available, and records each yes or no for that alert. No reply is never treated as available.

- **Assignments:** forwards a volunteer's accept/decline, or a shelter's bed confirmation. Pickup points go only to the volunteer, never back to the coordinator.
- **Journey reports:** sends pickup reports (volunteer) and arrival check-ins (shelter) to the Doorstep coordinator.
- **Recovery referrals:** answers consent-scoped referrals for recovery organizations; never files claims.

Talks to: Doorstep coordinator, Post-Calamity agent. Messages: `OutreachRequest/Result`, `AcceptRequest/Response`, `ReportRequest` → `PickupReport/ArrivalReport`, `ReferralRequest/Response` (schema 2.0).

# Doorstep News / Road-closure Agent (DEMO)

**Simulation only. Synthetic feeds. Never tells anyone a road is safe.**

Watches two feeds in the Doorstep demo:
- **Official closures (simulated):** a stand-in for a public-works closure feed. Only these can become *official-confirmed* and block illustrative routes.
- **News reports (synthetic):** the ASI:One API extracts the claim each article makes about a road (e.g. "Canyon Rd blocked by debris"). The report is labeled **unverified**: it adds a caution, never a block.

The Doorstep backend decides each record's state with fixed rules (official-confirmed, unverified report, conflicting, expired). This agent never labels anything official, never decides a report is true, and never treats "no reports" as "road open".

Messages: `PollNow` (demo control), `ClosureNotification` → Doorstep coordinator (schema 2.0).

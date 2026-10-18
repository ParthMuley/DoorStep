# Doorstep Calamity Checker (DEMO)

**Simulation only. Real evacuation data, if configured, is display-only and never starts the help flow.**

Polls an evacuation-zone feed in the Cal OES evacuation-layer format every 2 minutes (the demo uses a synthetic feed in exactly that format). Posts each fetch, including failed ones, to the Doorstep backend, which normalizes the zone status, checks freshness, and geofences enrolled residents. When the backend reports new or changed **simulated official** alerts, this agent notifies the Doorstep coordinator with the affected cases and the closest organizations able to help.

- Never interprets an alert status itself and never treats a fire radius as an evacuation order.
- Backs off when the feed fails; missing or stale data is reported, never treated as safe.

Messages: `PollNow` (demo control), `AlertNotification` → Doorstep coordinator (schema 2.0).

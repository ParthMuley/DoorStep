# Doorstep Escalation Simulator (DEMO)

**Simulation only. Not connected to 911 or any real emergency service.**

Stands in for an authorized emergency-response service in the Doorstep demo. When a resident is inside an active evacuation-order zone (where ordinary volunteers are never sent), the coordinator escalates the case here. This agent only records a **receipt**: `ACKNOWLEDGED_REQUEST_ONLY`. That means "request received" — it never means responders were dispatched, and assistance is always reported as **not confirmed**. The case stays unresolved with the coordinator owning follow-up.

Messages: `EscalationRequest` → `EscalationAck` (schema 2.0).

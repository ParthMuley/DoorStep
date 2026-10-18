# Doorstep Route Agent (DEMO)

**Simulation only. ILLUSTRATIVE ROUTE ONLY — NOT FOR LIVE EVACUATION. Never claims a route is safe.**

After a (simulated) volunteer accepts an assignment, this agent plans the volunteer's illustrative route: volunteer start → resident pickup area → shelter, using HERE Routing v8.

- **Avoids** only what the Doorstep backend marks as active evacuation-order zones and **official** road closures. Avoid areas are only ever enlarged when simplified.
- **Cautions** for unverified news reports on the path; these are never treated as blocks.
- **Refuses** instead of guessing: a stop inside an order zone, stale or unknown data, too many avoid areas, or a route the backend's independent check finds crossing a blocked area.
- **ETA** is an illustrative estimate, not a guarantee.
- No AI model chooses routing inputs. Calls to HERE are capped and cached per assignment.

Messages: `RouteRequest` → `RouteResponse` (schema 2.0).

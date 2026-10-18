# Doorstep Matching Agent (DEMO)

**Simulation only. Deterministic rules, no AI ranking of people.**

Matches a resident who asked for help with an **available** volunteer whose registered capabilities cover all of the resident's needs (wheelchair space, transfer help, pets, seats...) and an accessible shelter, closest first. Every eligible and rejected candidate comes with reason codes (e.g. `WHEELCHAIR_OK`, `NO_WHEELCHAIR_SPACE`). Residents inside an active evacuation-order zone, or in stale/unknown data, are never matched to an ordinary volunteer.

A proposed match is **not** a confirmation: nothing is confirmed until the volunteer accepts.

Messages: `MatchRequest` → `MatchResult` (schema 2.0).

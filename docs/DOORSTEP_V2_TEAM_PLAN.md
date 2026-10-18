# DOORSTEP V2 — Two-Person Plan (Fetch.ai track) — revision 6

*Shared plan for Developer A and Developer B. Both Claude Code sessions read this file. Change only by PR, agreed by both. Revision 2 (2026-10-17) re-aligned the plan with the team's original idea and switched to MongoDB. **Revision 3 (2026-10-17, proposed by A, agreed by B):**
- no agent per organization: one Volunteer Network agent serves all partner orgs;
- the partner database becomes location-first (`region → orgs → volunteers`), so finding the closest help to an evacuation zone is one geo query.

**Revision 4 (2026-10-17, proposed by A, agreed by B on 2026-10-18 with the amendments in §0.5, which A confirms):**
- residents and volunteers use **their own ASI:One accounts** instead of simulated SMS;
- the **Route agent** design is fixed (HERE Routing v8, avoid areas from B only, B post-check);
- §17 explains how to get a HERE API key;
- B's amendments (§0.5): the sender address must come from the authenticated Doorstep agent, the demo link codes are public, and a 15-minute reply deadline applies.

**Revision 5 (2026-10-18, proposed by A, agreed by B):** self-registration in ASI:One with address geocoding (§00).

**Revision 6 (2026-10-18, proposed by A, agreed by B on 2026-10-18; B's answers in §000.10):** what we learned running everything live in ASI:One, plus:
- bulk volunteer roster import with invite codes;
- "Your trip" snapshot cards;
- the HERE route map image, **hosted by B**;
- one consolidated list of asks and questions for B (§000.9).

See §000 (rev 6), §00 (rev 5), §0 (rev 4), §0.5 (amendments) and §0b (rev 3).*

## 000. Revision 6 (2026-10-18, proposed by A, agreed by B)

All of this runs on `feat/fetch-agents` against B's real app (`scripts/dev_backend_v2.py` = B's app plus A's stand-ins for routes B hasn't built yet). The 8 agents are on Agentverse mailboxes. Everything was verified live in ASI:One with synthetic people only. Commits: `1cbad8a`, `f35e2ba`, `a656ef8`, `d0e1915` and this one.

### 000.1 Live ASI:One behaviour we must design for (verified)
| Finding | Consequence / what A did |
|---|---|
| ASI:One shows an agent message **only in the chat whose `session` the envelope carries**. A push sent from an agent-to-agent handler (e.g. the alert) carried the Calamity agent's session and never appeared anywhere. | The outbox now sends each person's messages through the context of **their latest chat message** (`Outbox.remember`). After an agent restart, the person must send one message before pushes reach them again. |
| Every agent message that arrives before the person's next reply is **folded into one bubble** (newest text first), and **only the last card renders**, even when the messages are minutes apart. | Every person-facing update is now a **full snapshot card** (§000.4). The outbox adds an "Also in this update" row naming any cards it had to drop. |
| **Cards without buttons don't render on their own** (`is_terminal`). | Info-only cards need a Refresh button when they're sent alone (A: to do). |
| `<code>` in text is swallowed as an HTML tag. | Reply wording fixed ("LINK followed by your code"). |
| **ASI:One's built-in personal assistant can intercept.** After a page reload the chat's "To:" switched to the assistant; it called our agent itself and told the user a **stale status from old chat history**. Our next push then followed the assistant's session and never reached the chat. | Demo rule: check "To: doorstep_coordinator" and turn off the assistant's auto-response in chat settings. A (to do): remember only sessions from direct chat messages. |
| Card `hero_image` (tested live): a public **`https://`** URL renders, loaded **directly by the viewer's browser** (no proxy); a **`data:` URI makes ASI:One reject the whole card**; `http://localhost` is blocked by asi1.ai's CSP (`img-src 'self' data: blob: https:`). | The map image needs a **public https URL** → B hosts it (§000.7). |

### 000.2 Self-registration (rev 5) verified live
- Flow: `UNLINK` (new demo command) → "register as resident" → form → confirm → linked.
- The check-in card then reached the resident's own chat after the alert. The case was in the WARNING zone and `CHECKIN_SENT`.
- The geocode guardrail worked: "Del Mar High School, …" matched a POI (`NOT_PRECISE:place`) and was refused. The bare street address matched at house-number level (`HIGH`). That took 2 HERE geocodes.

### 000.3 Bulk volunteer roster import + invite codes (new)
- **How it works:** `scripts/import_volunteers.py <csv> --org <org> --region <region>` → `workflows/roster_import.py`.
  - Each row goes through B's real `POST /regions/{r}/orgs/{o}/volunteers`.
  - Rows are validated first; a bad row never stops the others.
  - Re-import reports `EXISTS` and never overwrites.
  - Imported volunteers are approved by default (the org vouches for its roster); `approved=no` per row.
- **Invite codes:** each imported volunteer gets a **one-time invite code** (e.g. `EASTSIDE-6128`) that they type as `LINK <code>` in ASI:One.
- **Sample roster:** `scripts/rosters/eastside_rides_demo.csv` (5 synthetic volunteers).
- **Live run:** imported → Alex linked → "Are you available?" → yes → coordinator matched Maria.
  - **Alex ranked #1 at 0.3 km.** The other imported volunteers were rejected with B's reason codes (no wheelchair space, pet capacity, awaiting reply, not approved).
  - Then: approve → assignment card → accept → live HERE route → two-party pickup → arrival → GREEN.
- **Needs B:** `POST /organizations/{org_id}/invites` (stand-in in `fake_v2_backend.py`); optionally a batch volunteer endpoint.

### 000.4 "Your trip" snapshot cards (new)
Residents and volunteers get one `trip_card` at every step:
- progress (✓/○ accepted · picked up · arrived);
- who is coming and the ETA (resident), or the route summary plus what it avoids (volunteer);
- the next step;
- **the one button that applies now** (Confirm pickup, then Refresh).

Turn-by-turn steps go in the text. Verified live: pickup and arrival folded into one bubble whose card was the complete final state. The coordinator's case card (with coordinator buttons) is no longer sent to residents or volunteers.

### 000.5 ASI:One commands by role (current)
Every role: `LINK <code>`, `UNLINK` (demo), `register as resident` / `register as volunteer` (unlinked only), `status`. Dev: `test push`, `test image web|data|local|plain`. Card buttons send the same actions as the text commands.

| Role | Text commands | Card buttons |
|---|---|---|
| **Resident** | `1`/`2`/`3`/`4` (need help / have a plan / already left / call me) · `yes`/`sí`/`no` (confirm needs) · `confirm pickup` · `status` | Check-in options · Confirm needs · Confirm pickup · Further help yes/no (recovery consent) · Refresh |
| **Volunteer** | `yes`/`no` (availability) · `accept`/`decline` (assignment) · `confirm pickup` · `status` | Yes, I'm available / Not now · Accept / Decline · Confirm pickup · Refresh |
| **Coordinator** (ASI:One tool calling, keyword fallback) | `Start the simulated Zone 3 readiness check` · `Simulate Maria's/David's reply` · `Find a match for Maria/David` · `approve` · `Confirm pickup for Maria` · `Confirm arrival for Maria` · `Request recovery for Maria` · `Escalate David` · `Road conditions` · `Status for Maria` · `help` | Approve / Reject (match) · Show suitable volunteers · Confirm pickup / arrival · Recovery consent · Escalate · Refresh status |

### 000.6 Why these are agents (judge question) and what A will strengthen
- **Strong:**
  - **Doorstep:** the only interface a person reaches in ASI:One; runs multi-step conversations, pushes unprompted and orchestrates the rest.
  - **Calamity Checker:** autonomous; perceives the feed and starts the response with nobody asking.
  - **Volunteer Network:** acts on the orgs' behalf, alone holds the network token, and waits minutes for people. In reality each partner would run it.
  - **News:** an LLM reads text into claims and never decides truth; reusable by any ASI:One user.
- **Medium:**
  - **Route:** reusable avoid-the-zones routing.
  - **Post-Calamity:** a separate, consent-gated phase.
- **Weak today:**
  - **Matching** is a pass-through.
  - **Escalation** only records a receipt.
- **A's plan:**
  - Matching re-ranks B's top 3 by **HERE drive time**, negotiating with the Route agent. This fixes straight-line ranking and the ETA mismatch: B estimated 4 min, HERE said 1 min.
  - Escalation owns the **deadline sweep** (needs B's `/deadlines/sweep`).
- **Pitch line:** each agent maps to a real-world party with its own trust boundary. The LLM is used only for language. Every life-safety decision stays deterministic in B, with reason codes.

### 000.7 Route map image: A renders, **B hosts** (ask)
**A (done, `integrations/map_image.py`):**
- After a volunteer accepts and B's post-check says `ILLUSTRATIVE_ONLY`, the Route agent calls the **HERE Map Image API v3** server-side (the key never leaves A's process).
- Overlays: the route as a flexible-polyline `line` (blue), ORDER zones and official closures as translucent `polygon`s, and labelled Start / Pickup / Shelter `point`s.
- The image auto-fits with `padding=48`; a PNG is about 80 KB at 640x400.
- One HERE call per accepted assignment, cached, counted in the daily cap.
- HERE gotchas: polygon rings must be closed; polygons accept only `color` (`#rrggbbaa`); `outline-*` on a polygon returns HTTP 400 E622002.

**Ask for B: host the PNG at a public https URL** (ASI:One loads `hero_image` straight from the viewer's browser, so it can't send auth headers):
- `PUT /maps/{map_id}` (`X-Agent-Token`; the network token or a new `ROUTE_AGENT_TOKEN`), body `image/png` ≤ 300 KB → `{"url": "https://<public-host>/maps/{map_id}.png", "expires_at": …}`.
  - `map_id` is chosen by A: `secrets.token_urlsafe(24)`, unguessable.
  - Optional body field or query `assignment_id`, so B can expire maps with the assignment.
- `GET /maps/{map_id}.png`: public, no auth, `Content-Type: image/png`, `Cache-Control: private, max-age=3600`, `X-Robots-Tag: noindex`, **404 after expiry**. Expiry: 24 h or when the assignment is completed or cancelled.
- No listing endpoint, and never log the map id with personal data. **The map shows the pickup point**, so A sends the URL only to the assigned volunteer, after Accept (synthetic data only in the demo).
- The backend must be reachable at a **public https host** for the demo. Set `PUBLIC_BASE_URL` (B's deploy). Until then A shows the route as text only. If no deploy is planned, A can run an ngrok tunnel serving only the maps folder as a fallback.

### 000.8 A's next steps
1. The Route agent renders the map → `PUT /maps/{id}` → `RouteResponse.map_url` → `hero_image` on the volunteer's trip card (as soon as B's endpoint exists).
2. Refresh buttons on info cards; only remember direct-chat sessions (ignore the built-in assistant).
3. Matching re-rank by HERE drive time; coordinator card to approve self-registered volunteers; Calamity → `/deadlines/sweep`.
4. Three-account demo (resident, volunteer, coordinator), then a thin LangGraph over the same actions.

### 000.9 Asks and questions for B (consolidated; stand-ins exist in `tests/integration/fake_v2_backend.py`)
**Endpoints:**
1. `POST /link`: one-time codes → link an ASI:One address (rev 4).
2. `POST /register`: create + link in one call (rev 5).
3. `POST /orgs/{org}/volunteers/{vid}/approve`: coordinator approves self-registered volunteers.
4. `POST /organizations/{org}/invites` → one-time invite code that `/link` accepts (rev 6). Optional: batch `POST …/volunteers`.
5. `PUT /maps/{id}` + `GET /maps/{id}.png` (§000.7), and a **public https deploy** of the backend.
6. `POST /deadlines/sweep`: the 15-minute reply deadline (rev 4 amendment).
7. Accept the **linked ASI:One sender** on resident replies (today A maps it to `sim_phone_*`).

**Small fixes:**
- align `ROUTE_MAX_AVOID_AREAS` to HERE's 20;
- clear `NETWORK_AGENT_TOKEN` in unit tests;
- move demo coordinates off real street addresses where possible.

**Questions:**
- Where will the backend be deployed for judging (host, https), and can it serve `/maps` there?
- Should the ETA shown to people come from HERE's route when there is one, instead of B's estimate? Live they disagreed: 4 min vs 1 min.
- Should B rank by drive time if A sends it, or should the Matching agent re-rank (§000.6)?
- Do you agree imported volunteers are approved by default because the org vouches, while self-registered ones are not?
- Is a 24 h map expiry and a ≤ 300 KB size OK?

### 000.10 B's answers and what B built (B8, 2026-10-18; contract v2.2 = `docs/interface-contract.md` §5.13)
**Built on `feat/backend-geodata`, so A can delete the stand-ins in `fake_v2_backend.py`:**
1. `POST /link` and `POST /unlink` (Doorstep token). The same seeded codes as A's stand-in; invite codes work too.
2. `POST /register`: same response shape as A's stand-in. Residents are stored as `SELF-REGISTERED (demo)` with coordinates only; volunteers always start unapproved.
3. `POST /orgs/{org}/volunteers/{vid}/approve`, plus `GET /volunteers/pending?org_id=` for the coordinator card.
4. `POST /organizations/{org}/invites` → a one-time code (e.g. `NEIGHBOR-4821`) that `/link` accepts. No batch endpoint yet; A's per-row import works.
5. `PUT /maps/{map_id}` (`X-Agent-Token: ROUTE_AGENT_TOKEN`, raw PNG ≤ 300 KB) and public `GET /maps/{map_id}.png` (24 h or assignment-end expiry, `noindex`).
   - **Deploy:** Render (free) + MongoDB Atlas, see `docs/deploy-render.md`. Until it's deployed, map URLs point at the local backend.
6. `POST /deadlines/sweep` (Doorstep **or** Calamity token: `CALAMITY_AGENT_TOKEN`). The deadline is also applied whenever a case, outreach, match or dashboard is read.
7. **Linked ASI:One sender on resident replies:** accepted with the Doorstep token. A can stop sending `sender_for_backend` (B's `/link` doesn't return it) and send the linked address. Sim-phone senders still work during the switch.
   - Volunteer availability takes an optional `sender` (the linked address), which B checks.
8. **Small fixes:** `ROUTE_MAX_AVOID_AREAS` default **20**; unit tests clear all agent-token env vars; `KEYWORD_EXTRACTION` / `UNCLEAR` accepted (`d25e373`).
   - Demo coordinates: they're fictional labels on real-world LA coordinates, which the geofence needs. Seeded street addresses are never real.

**Verified:** A's `test_rev4_linking`, `test_rev5_registration` and `test_roster_import` pass with the stand-ins switched off, i.e. against B's real routes. Full suite: 268 passed.

**Answers to A's questions:**
- **Deploy:** Render + MongoDB Atlas (free), public https at `https://<service>.onrender.com`, serving `/maps`. B sets it up; tokens go to A privately.
- **ETA:** use HERE's when there's an `ILLUSTRATIVE_ONLY` route. B already replaces its straight-line estimate with the preview's `duration_s`. **Send the first section's duration (volunteer → pickup), not the whole trip.**
- **Drive-time ranking:** B ranks, so every matching decision stays in one tested place. `/matches/propose` accepts optional `drive_minutes: {volunteer_id: minutes}` and ranks the *eligible* volunteers by it, falling back to distance. Eligibility never changes. **Built** (contract §5.6). The Matching agent can get B's top eligible volunteers with `create_proposal: false`, ask the Route agent / HERE for drive times, then propose with `drive_minutes`. The ETA then comes from the drive time.
- **Approval:** agreed. Org-imported volunteers keep the approval the org gives them (default yes); self-registered ones start unapproved.
- **Maps:** 24 h and ≤ 300 KB are fine (`MAP_TTL_HOURS` configurable).

**New env vars for `.env.example` (A's file):** `DOORSTEP_AGENT_TOKEN`, `ROUTE_AGENT_TOKEN`, `CALAMITY_AGENT_TOKEN`, `REPLY_DEADLINE_MINUTES=15`, `PUBLIC_BASE_URL` (optional), plus `NETWORK_AGENT_TOKEN` and `MONGODB_PARTNERS_DB` if still missing.

**Not built (on purpose):** B-side `notify` lists for check-ins and outreach. A's Doorstep agent already composes role cards, so only the sweep returns a `notify` list.

### 000.11 A's follow-up to B8 (2026-10-18)
**Done on `feat/fetch-agents`, fast-forwarded to B's `2a0d0ec`:**
- **Stand-ins deleted.** `/link`, `/register` and invites now hit B's real routes. `tests/integration/fake_v2_backend.py` is B's app plus one new stand-in (below).
- **Linked senders.** Resident replies send the linked ASI:One address (Doorstep token); `sender_for_backend` is gone. Volunteer availability sends `sender` = the linked address (`VolunteerAnswer.sender` → Volunteer Network → B).
- **Route map wired.** For an `ILLUSTRATIVE_ONLY` route, the Route agent renders the HERE map (one more call, same daily cap) and calls `PUT /maps/{secrets.token_urlsafe(24)}?assignment_id=…` with `ROUTE_AGENT_TOKEN`. It returns `RouteResponse.map_url`.
  - The volunteer's trip card shows it as `hero_image` **only when the URL is https** (ASI:One rejects the card otherwise).
  - A failed map never fails the route. The map id is never logged. `ROUTE_MAP_IMAGES=false` turns it off.
- **Drive-time ranking wired:**
  1. The Matching agent calls `/matches/propose` with `create_proposal: false` to get B's eligible volunteers.
  2. It sends the top `DRIVE_TIME_CANDIDATES` (3) to the Route agent (`DriveTimeRequest`).
  3. The Route agent makes one HERE route per candidate (start → pickup, avoiding ORDER zones and official closures, counted in the cap).
  4. Matching then proposes with `drive_minutes`; B ranks.
  - Any failure falls back to distance. The match card shows "N min by road". `DRIVE_TIME_RANKING=false` turns it off.
- **Tests:** our integration tests pin every token to its placeholder, so a developer's `.env` (now holding the Render tokens) can't change results. New: `test_drive_time.py` (Lee at 4 min by road beats Sarah at 15 min; ETA 4) and two map tests in `test_route.py` (render → B upload → public GET; a map failure keeps the route). **All 58 integration tests pass on B's real routes.**
- `.env.example`: `ROUTE_AGENT_TOKEN`, `CALAMITY_AGENT_TOKEN`, `REPLY_DEADLINE_MINUTES`, `MAP_TTL_HOURS`, `PUBLIC_BASE_URL`, `MONGODB_PARTNERS_DB`, `ROUTE_MAP_IMAGES`, `DRIVE_TIME_RANKING`, `DRIVE_TIME_CANDIDATES`.

**New asks for B:**
1. **`POST /routes/candidates`** (Route token): the Route agent needs coordinates for *candidate* volunteers before anyone accepts, and `/routes/constraints` only covers accepted assignments.
   - Body `{case_id, volunteer_ids (≤5)}` → `{case_id, pickup: {lat, lon}, candidates: [{volunteer_id, lat, lon}], avoid_areas: [{kind, id, geometry}]}`.
   - Only volunteers B lists as eligible for that case should be returned (409 otherwise); never in GET views.
   - The stand-in is in `fake_v2_backend.py` (`build_candidates_standin`) and uses your `store.partners.locate_volunteer` and `routes._order_areas` / `_official_areas`.
2. **Unit-test `.env` leak:**
   - `create_app()` calls `load_dotenv()`, which reloads `.env` *after* `tests/unit/conftest.py`'s `hermetic_env` has deleted the tokens.
   - On a machine whose `.env` holds the Render tokens, `test_http_accept_requires_network_token` and `test_v2_scenarios_end_to_end` fail with 403.
   - With the placeholders preset, all 218 unit tests pass.
   - Fix: in `hermetic_env`, `setenv` the placeholder values instead of `delenv` (`load_dotenv` never overrides a set variable), or skip `load_dotenv` when `PYTEST_CURRENT_TEST` is set.

**For the live run, A needs:** the Render URL (`DOORSTEP_API_URL`) in A's `.env`. The tokens are already there.

## 00. Revision 5 (2026-10-18, proposed by A, agreed by B): self-registration in ASI:One

**Why:** today a person can only link to a record that already exists (seeded one-time codes). Revision 5 lets a resident or a volunteer **register themselves in their own ASI:One chat**, before a disaster, and be linked in the same step.

**Fetch / ASI:One limits (verified in the card docs):** inputs are only `text`, `number`, `email`, `select` and `checkbox`. There is no location picker, no map input and no device location, and an agent never receives GPS. So the person **types an address and the agent geocodes it** with HERE Geocoding (`/v1/geocode`, same `HERE_API_KEY`, free tier).

**Flow (Doorstep agent):**
1. Unlinked chat → link card **plus** "Register as resident" / "Register as volunteer".
2. **Resident form:** name (synthetic label is fine), language (`en`/`es`), address, needs checkboxes (codes 1–10), pet count, consents (check-ins, transport, destination; recovery stays per-request).
   **Volunteer form:** name, organization (`select` of approved orgs), address, vehicle type, seats, wheelchair spaces, pet capacity, capability checkboxes.
3. **Geocode** (HERE, `in=countryCode:USA`, `limit=2`):
   - `HIGH` only if the top result is a house number or street with `queryScore ≥ 0.9` and no near-tie with a second result;
   - otherwise ask the person to rephrase, and never register a guessed location;
   - no result → `FAILED`, nothing registered.
4. **Confirm card:** "We found: <HERE's label>" plus rounded coordinates → Confirm / Change. Nothing is stored before Confirm.
5. **Register + link in one call** (needs B): `POST /register` with `X-Agent-Token: DOORSTEP_AGENT_TOKEN`:
   ```json
   {"role":"RESIDENT"|"VOLUNTEER","asi_one_address":"<envelope sender>","profile":{…ResidentProfile or volunteer fields…},"org_id":"…"}
   ```
   - B creates the record (residents → `POST /residents` rules; volunteers → the region found from their location) and links the address.
   - It returns the same shape as `POST /link` (role, `resident_id` + `case_id` or `volunteer_id` + `org_id`).
   - The ASI:One address becomes the person's contact (`channel: ASI_ONE`).
6. **Volunteers start unapproved** (`approved: false`): they're never matched until their organization approves them. Needs B: `POST /orgs/{org_id}/volunteers/{volunteer_id}/approve` (coordinator, demo token). A will add a coordinator card listing pending volunteers.

**Privacy rules for addresses:**
- Agents never log the address text. It goes only to HERE for geocoding, and B stores the coordinates plus `geocode_confidence`, with address label `"SELF-REGISTERED (demo)"`, not the street address.
- The form says **"Demo: use a fictional or public-place address"**.
- `GET` endpoints never return a person's coordinates (B's existing rule).
- `LOW`/`FAILED` → zone `UNKNOWN`, never safe (B's existing rule).

**Until B ships `POST /register`:** A uses a stand-in in `tests/integration/fake_v2_backend.py` that calls B's real `POST /residents` and `POST /regions/{region}/orgs/{org}/volunteers` and then links the address.

## 0. What changed in revision 4 (and why)

| Change | Why |
|---|---|
| **Residents and volunteers chat with the Doorstep agent in their own ASI:One accounts.** No more simulated SMS on the main path. | Fetch.ai/ASI:One can't send SMS or push notifications to people who haven't talked to an agent. An ASI:One user who has messaged the Doorstep agent **can** receive agent-initiated messages (verified live 2026-10-17). So everyone who must be reached (resident, volunteer, coordinator) needs an ASI:One account and links it once. The Fetch.ai track then shows real people acting through agents, not a simulator. |
| **One entry point:** every person talks to the **Doorstep agent**. Other agents never message people directly; they ask Doorstep to notify (Volunteer Network → Doorstep → volunteer). | ASI:One users only reach agents they chat with. One "face" keeps registration, linking and push in one place. |
| **Role-based cards** (resident / volunteer / coordinator), §0.2. | Each person sees only their part. Card clicks are the real answers: the resident's check-in reply, the volunteer's YES/accept, both pickup confirmations. |
| **Route agent design fixed** (§0.3): HERE Routing v8, multi-stop volunteer → pickup → shelter, avoid areas only from B, refuse instead of truncate, B's Shapely post-check, no LLM in routing. The route card goes to the **volunteer**. | The team's sample HERE agent was a chat assistant where the LLM chose user-supplied "blocked roads". Our safety rules need official-only blocks and an independent check. |
| The SMS simulator stays only as a **fallback** for unanswered steps, automated tests and the offline demo. | Tests and the smoke test must run without ASI:One accounts. |
| **Contract v2.2** (B): ASI:One contact channel, link codes, "notify" lists instead of SMS sends, resident pickup confirmation (§0.4). | Answers A's review items 4–5. |

### 0.1 Linking an ASI:One account (before a calamity)
- **First chat:** the Doorstep agent shows a link form card ("I'm a resident" / "I'm a volunteer"). Each role then sees its own cards.
- **Demo:** pre-seeded people link with a **one-time code** from the seed, e.g. `LINK MARIA-4821`, `LINK SARAH-7310`, `LINK COORD-1150`. B stores their ASI:One address as their `contact`, and the code is then spent. A random account can't claim to be Maria.
- **Coordinator / org staff** link the same way, with role `COORDINATOR`.
- **Someone who never linked can't be reached.** Their case shows `communication_status: NOT_REACHABLE` and stays visible to the coordinator. In the pitch this is "enroll before a calamity".
- **Demo accounts:** three consenting teammates on separate ASI:One accounts (resident, volunteer, coordinator), everything labeled DEMO.

### 0.2 What each role sees (cards)
| Role | Cards pushed to their ASI:One chat |
|---|---|
| **Resident** | Check-in card on a simulated official alert ("Do you need help?" Need help / Have a plan / Already left / Call me) → needs-confirmation card (the extracted needs; Confirm / Change) → "A volunteer accepted, about N min (estimate, not a guarantee)" → **"Confirm you were picked up"** → arrival → "Want further help?" consent card → referral status |
| **Volunteer** | Availability card for an alert (Yes / No) → **assignment card**: consent-scoped needs, the **route card** (§0.3), pickup point shown only after Accept → Accept / Decline → **"Confirm pickup"** → done |
| **Coordinator** | Alert, outreach, operations board, unresolved queue, David's escalation, road conditions; can approve arrangements and trigger demo controls |

### 0.3 Route agent (HERE Routing v8)
```
volunteer accepts → Doorstep → RouteRequest(assignment_id) → Route agent
Route agent → B POST /routes/constraints → stops + avoid_areas + cautions   (or 409 ROUTE_REFUSED)
Route agent → HERE GET /v8/routes  origin=volunteer, via=pickup, destination=shelter,
              avoid[areas]=polygon:…|…, return=polyline,summary,actions,instructions
Route agent → B POST /routes/previews (decoded polyline) → ILLUSTRATIVE_ONLY | REFUSED | NO_ROUTE_CONFIRMED
Route agent → RouteResponse → Doorstep → route card to the volunteer (+ summary to the coordinator)
```
- **Kept from the team's sample:** the HERE v8 request shape, buffering closure lines into avoid polygons with Shapely in a local metric projection, the 250-area limit, refusing when HERE's `notices` report a violated avoid area, and the first N instructions.
- **Changed for Doorstep:**
  - **No LLM in routing.** It's a service agent: `RouteRequest` in, `RouteResponse` out.
  - **Avoid areas come only from B:** active order-zone polygons plus **official-confirmed** closures. Unverified or conflicting reports are **cautions**, never blocks.
  - **Refuse instead of truncating** (`TOO_MANY_AVOID_AREAS`).
  - Polygons are simplified only in ways that **enlarge** them (buffer outward, then simplify or convex hull). HERE's per-polygon vertex limit must be checked in their docs.
  - **No geocoding:** stops are B's synthetic coordinates. Any future geocoding refuses on an ambiguous result.
  - **Multi-stop with `via`:** the first section's duration is the volunteer's ETA to the resident, the "about N min" in the help-on-the-way card.
  - **`return=polyline`** (decoded with HERE's `flexpolyline` package) for B's independent Shapely post-check: no order-zone or official-closure crossing, data still fresh.
  - **Secret seed** from `.env` (`ROUTE_SEED`), `httpx` async, idempotent per `assignment_id`.
  - **Wording:** never "safe" or "clean"; always "ILLUSTRATIVE ROUTE ONLY - NOT FOR LIVE EVACUATION" and "ETA is an estimate, not a guarantee".
- **Route card (volunteer):** distance, ETA to pickup and total, order zones and official closures avoided, cautions on the path (e.g. "Canyon Rd: unverified report"), the first ~6 directions, and the banner. A refusal shows the reason and no route.
- **Map image (P1, after the text card works):** HERE Map Image API with the route and zone overlays, if its docs confirm overlay support. Its URL carries the API key, so the agent fetches it server-side and the image is hosted or embedded (≤64 KB card limit). Never expose the key in a card. Google Maps is **not** used.
- **Tests:** HERE mocked with `httpx.MockTransport` (avoids zones / crosses an order zone / empty result); a HERE key is needed only for live runs.

### 0.4 Contract v2.2 asks for B
1. `residents` and `volunteers` gain `contact: {"channel": "ASI_ONE", "address": "agent1q…|user address", "linked_at"}`, plus seeded one-time `link_code`s. Add `POST /link {code, asi_one_address, role}` → `{role, resident_id | volunteer_id | coordinator_id}`, with 409 if the code is spent or unknown.
2. Wherever B "sends a simulated SMS" today (check-ins, outreach, help-on-the-way, arrival follow-up), it returns a **`notify` list** instead: `[{"person_id", "role", "channel": "ASI_ONE", "address", "template_id", "language", "text"}]`. The Doorstep agent delivers it as cards. Templates stay human-reviewed text (Spanish reviewed). The simulator is used only when the channel is `SIM`.
3. Inbound answers arrive through the existing endpoints with `sender` = the linked ASI:One address (B checks it against `contact.address`; unknown sender → 403): resident replies (`/cases/{id}/responses`) and volunteer availability (`/alerts/{id}/volunteers/{vid}/availability`).
4. **Resident pickup confirmation:** `POST /assignments/{id}/pickup` accepts `{"evidence": {…, "resident_confirmed": true, "confirmations": [{"party": "resident", "party_id": "resident_001", "via": "ASI_ONE"}]}}` when the click comes from the resident's linked address. This settles review item 5.
5. `communication_status` adds `NOT_REACHABLE` (never linked); still never treated as danger or safety.

### 0.5 Amendments (proposed by B on 2026-10-18 when agreeing to rev 4; A to confirm)
1. **The sender address comes only from the Doorstep agent.**
   - The ASI:One address on `POST /link` and on inbound answers (`sender`) is the address of the chat the message really arrived from. The Doorstep agent reads it from the message envelope and never from text the user typed (typing "I am Maria" or pasting an address proves nothing).
   - The Doorstep agent authenticates to B with `X-Agent-Token: DOORSTEP_AGENT_TOKEN`. B refuses `POST /link` and any request that carries a `sender` without it (401), and refuses a sender that doesn't match the person's linked `contact.address` (403).
   - Other agents never send a `sender`. They only ask Doorstep to notify people.
2. **The demo link codes are public.**
   - The seeded one-time codes (`MARIA-4821`, `SARAH-7310`, `COORD-1150`, …) are in the repo, so anyone reading it can see them.
   - That's acceptable for a synthetic demo, and it's documented in the README and the contract as a known limitation.
   - A code works once (a second use gets a 409, even from the same address). `POST /demo/reset` reissues the codes.
   - A real deployment would issue codes out of band (through the partner org) and expire them.
3. **A 15-minute reply deadline** (`REPLY_DEADLINE_MINUTES`, default 15). Every check-in and availability request stores `reply_by = asked_at + 15 min`.
   - **Volunteer, no answer by `reply_by`:** availability becomes `NO_REPLY`, which matching treats as **not available** (reason code `NO_REPLY`). Matching moves on to the next eligible volunteer.
   - **Resident, no answer by `reply_by`:** `communication_status` becomes `NO_REPLY_AFTER_DEADLINE`, and the case joins the coordinator's unresolved queue with the next step "follow up". It **never** means safe or "no help needed": silence is not evidence of danger or of safety.
   - **Late answers still count.** A resident replying at minute 20 is handled normally. A volunteer saying YES at minute 20 becomes `AVAILABLE` again while the alert is still active, but an assignment already given to someone else is not taken back.
   - **No automatic SMS fallback.** The simulator is used only for people whose contact channel is `SIM` (not linked), and in tests. Any other fallback needs both of us to agree first.
   - **How it runs:**
     - B applies the deadline whenever it reads the data (case, outreach, matching, dashboard), so it holds even if no agent is running.
     - `POST /deadlines/sweep` (Doorstep or Calamity Checker token) applies it to everything at once and returns a `notify` list for the coordinator. The **Calamity Checker calls it on its 2-minute poll**, so cards update without anyone asking.
     - The existing `/sim/…/deadline` demo buttons stay, so the demo doesn't have to wait 15 minutes.


## 0b. What changed in revision 3 (and why)

| Change | Why |
|---|---|
| **No Organization agent per org.** One **Volunteer Network agent** handles outreach and acceptance for every partner org in the affected area. | Real deployments have many orgs in many places, and one process plus one Agentverse slot per org doesn't scale. We already hit the 8-agent account cap with 5 orgs. Agents now represent **services**, not tenants. |
| **The partner DB is location-first.** Each `regions` document is keyed by a location ID and holds the orgs active in that region, each with only its volunteers there. GeoJSON fields carry `2dsphere` indexes. | The system's real question is "who can help **near this evacuation zone**?" With location as the document key, that's one indexed `$near` / `$geoIntersects` query instead of a scan of every org. Location IDs are document `_id`s, not dynamic keys inside one document, because MongoDB can't index dynamic keys. |
| The agent count is **8**: Doorstep, Calamity Checker, Matching, Volunteer Network, Escalation, Post-Calamity, News, Route. | Fits the Agentverse account cap, so every agent gets a profile page. |
| The contract moves from v2.0 to **v2.1** for the region and network endpoints (§7). | B owns the contract. A's review items 1–5 in `dev-a-notes.md` still apply where relevant. |

**For:** Developer A (Fetch.ai agents, ASI:One, cards, LangGraph) and Developer B (backend, MongoDB, geography, matching).
**Base documents:** `Doorstep_V2_Two_Person_Claude_Code_Plan.md` + `Doorstep_Implementation_Master_Spec.md`. This plan overrides both on scope, tech stack and next steps; their safety rules still apply.
**Status:** synthetic-data simulation. No real alerts to people, no 911, no real volunteers, never a "safe route". Everything says **SIMULATION / DEMO**.

---

## 1. The idea (end-to-end flow)

**Before a calamity**
1. **Residents register:** address, phone, emergency contacts, needs, and whether they want to be contacted for help.
2. **Organizations register** themselves and their **volunteers per location**. Each registration lands in the **region** where those volunteers are, with the volunteer's location, vehicle type and size, which needs they can handle, and whether they're available to help. An org active in several places appears in each of those regions, with only its local volunteers.

**During a calamity**
3. **Calamity Checker** polls the government feed **every 2 minutes** (Cal OES evacuation zones, which include LA County). It finds the affected **zone polygons** and the calamity type (e.g. wildfire).
4. **Doorstep Help** asks every registered resident **inside the affected zone** (who agreed to be contacted) whether they need help, with a **check-in card in their linked ASI:One chat**, in their language (rev 4; simulated SMS only as fallback).
5. **At the same time**, Doorstep finds the **regions closest to the evacuation zone** with one geo query, and the organizations inside them that handle this calamity type. The **Volunteer Network agent** asks those organizations' volunteers whether they're available (an availability card in each volunteer's ASI:One chat, delivered by the Doorstep agent on each org's behalf; rev 4). Their yes/no answers are saved per alert in the partner (regions) DB.
6. **Matching agent** matches each resident who asked for help to an available volunteer whose capability codes cover all the resident's needs and whose vehicle fits. It also matches a shelter. Closest first, never ranking people.
7. **News agent** reports which roads are blocked or areas inaccessible: **official** closures vs **unverified** news reports.
8. **Route agent** (HERE Routing v8; design in §0.3) gives the volunteer an illustrative route card in their ASI:One chat: volunteer → resident → shelter, avoiding order zones and **official** closures, with cautions for unverified reports, or a refusal.
9. The **volunteer accepts** on their assignment card. The resident is then told, in their ASI:One chat, **"help is on the way" with an estimated arrival time** (marked as an estimate, not a guarantee). This is only said after the volunteer has accepted.
10. **Pickup** (volunteer **and** resident each confirm in their own chat) and **arrival** (shelter check-in) are confirmed separately. Green only at arrival.

**After evacuation**
11. Doorstep asks if they need further help. **Post-Calamity agent** takes over: temporary housing, insurance guidance, supplies, etc. It matches recovery organizations and refers with consent. It never files claims or promises housing.

**Safety case (David):** a resident inside an active **evacuation-order** zone never gets an ordinary volunteer. The case is escalated to a simulated authorized service and stays **unresolved**.
**Data-failure case (C):** if the feed goes stale, the zone becomes STALE/UNKNOWN, and matching and routing refuse. Nobody is called safe.

**Radius rule:** check-ins are based on the official **zone polygon**. Nearby help is found by a geo query from the zone polygon (or an incident point's awareness radius) to the **regions** collection. A radius alone never triggers the evacuation flow.

## 2. Tech stack

| Component | Technology | Owner |
|---|---|---|
| AI agents | Fetch.ai uAgents (§4) | A |
| Agent discovery | Fetch.ai Agentverse (mailboxes + profile READMEs for every agent) | A |
| User interaction | ASI:One via Chat Protocol (Doorstep agent is the entry point) | A |
| AI reasoning | ASI:One API (`https://api.asi1.ai/v1`, OpenAI-compatible, tool calling, structured output): intent → tools (A), free-text needs extraction and news extraction (B / News agent), plain summaries (A). **Never** decides eligibility, zones, consent or status | A + B |
| Agent communication | Fetch.ai agent messaging, correlation ID on every hop | A |
| Workflow | LangGraph (durable per-case graph) | A |
| Databases | **MongoDB**: `doorstep_users` + `doorstep_partners`, which holds the location-first `regions` with `2dsphere` indexes. Runs on local MongoDB or Atlas. Tests use `mongomock`, which needs a Shapely fallback for geo queries (see §5). | B |
| Backend | Python + FastAPI (contract v2.0) | B |
| Disaster detection | Cal OES evacuation layer (includes LA County Genasys zones) + synthetic feed in the same format | Calamity agent fetches, B normalizes |
| Zone detection | Shapely (`covers`: a point on the edge counts as inside; ORDER dominates) | B |
| Road closures | News agent + ASI:One extraction; only official closures block roads | A gathers, B classifies |
| Route planning | HERE Routing v8 (adapted from the team's route-agent code) | A agent, B gates and post-checks |
| Notifications | **ASI:One chats with the Doorstep agent** (rev 4). Residents, volunteers and coordinators link their accounts once, and the agent then pushes cards to them. B returns `notify` lists; the SMS simulator is only a fallback and test path | A + B |
| Dashboard | ASI:One Interactive Cards (text fallback) | A renders, B supplies data |

**Cut:** Sentry, Photon, Base44, web dashboard, Google Maps, scraping real news sites.

## 3. Where we are now (integrated branch `feat/fetch-orchestration` @ `9ef2738`; plan + contract draft on `feat/backend-geodata`)

| | Done | Changes with revision 2 |
|---|---|---|
| A | Done on `feat/fetch-agents` @ 4b578d2 (live on Agentverse, 7 of 8 agents on mailboxes):<br>• Doorstep drives the full V2 journey from ASI:One (alert push, outreach, match, approve, accept, pickup, arrival, recovery, David escalation) with cards and ASI:One tool calling<br>• Calamity Checker, Volunteer Network (rev 3), Matching, Escalation, Post-Calamity, News (ASI:One claim extraction) agents<br>• tested against B's app + a contract-shaped test double for routes not yet built | Still to do: Route agent (HERE, §0.3); rev 4 account linking + role cards; switch from the test double to B's real v2.1 routes; thin LangGraph |
| B (older status, see the row below) | Done on `feat/backend-geodata` @ 27e6295:<br>• MongoDB (2 DBs, mongomock tests, real-server test)<br>• B2 registration + needs codes<br>• B3 Cal OES-shaped feed, `/alerts/ingest`, Shapely geofencing, STALE/UNKNOWN, outreach list, volunteer outreach<br>• B4 `/matches/propose`, reservation, accept/decline, v2 pickup/shelter check-in, escalate + ack, Scenarios A/B/C v2 (158 unit tests)<br>• contract v2.1 written for rev 3 | Still to do: move partners to location-first `regions` + the v2.1 network endpoints (replacing the per-org ones), resident pickup SMS, `PUT /agents/{role}`; then B5 post-calamity, B6 closures + routes, B7 card data |
| **B (2026-10-18)** | Done on `feat/backend-geodata` @ `37426f9`:<br>• B1–B4 as above, now on location-first `regions` (2dsphere + Shapely), v2.1 network endpoints, `PUT /agents/{role}`, resident pickup SMS<br>• B5 post-calamity referrals (consent, nearest recovery org per help type, evidence for COMPLETED, next alternate on decline)<br>• B6 closures (official / unverified / conflicting, gazetteer) + `/routes/constraints` and `/routes/previews` post-check, ETA update<br>• B7 `/dashboard/summary`, `/dashboard/cases`, `progress_steps`, `/health` 2.1.0, README<br>• 196 unit tests, smoke test (v2 Scenarios A/B/C), real-MongoDB test | Still to do: **B8 (rev 4, contract v2.2 + §0.5)**; remove the v1 routes when A removes its v1 client and test; Spanish review |
| Next joint step | A's double still stands in for closures, routes and the dashboard, which are now live in B's app | drop the test double for those; run C3–C5 on B's real backend |

## 4. Agents (all uAgents on Agentverse, owned by A)

| Agent | Does | Never does |
|---|---|---|
| **Doorstep** (Coordinator + Doorstep Help) | the **only** agent people talk to in ASI:One (Chat Protocol). Links accounts to roles (§0.1), delivers B's `notify` lists as role cards (§0.2), and takes card clicks as the real answers. Uses ASI:One API tool calling for free text, plus LangGraph. Tells the resident "help is on the way" + ETA only after the volunteer accepts | decide eligibility or safety; claim dispatch; message a person who never linked |
| **Calamity Checker** | `on_interval(120s)`: fetch feed → `POST /alerts/ingest` → `AlertNotification` (zones, calamity type, affected residents) to Doorstep | interpret status itself; use a radius as an order |
| **Volunteer Network** (one agent for all partner orgs) | **Outreach:** on an `OutreachRequest` for an alert, has B pick the regions near the zone and the matching orgs in them, sends each of their volunteers a simulated "available?" message on the org's behalf, records the answers per alert, and replies with counts per org.<br>**Assignments:** forwards a volunteer's accept/decline and a shelter's bed confirmation.<br>**Journey:** reports pickup (volunteer) and arrival (shelter check-in).<br>**Recovery:** answers referrals for recovery orgs. | rank people; read the residents DB; forward pickup points or phones back to Doorstep |
| **Matching** | calls B's deterministic `matches/propose` and returns the explained result (wrapper; B's code decides) | match with an LLM |
| **News / Road-closure** | polls synthetic news + official-closure feeds; ASI:One extracts candidate `{road, claimed_status}`; posts to `/closures/ingest` with an honest source type | label anything official; treat "no reports" as "open" |
| **Route** (HERE) | on `RouteRequest(assignment_id)`: gets stops + avoid areas (order zones + official closures) + cautions from B → HERE v8 multi-stop route → submits the polyline to B's post-check → `RouteResponse` with the illustrative route, ETA to pickup and directions, or a refusal (§0.3) | say "safe"; use unverified closures as blocks; truncate avoid areas; use an LLM to choose routing inputs |
| **Post-Calamity** | after arrival + consent: matches recovery orgs by help type (housing, insurance guidance, supplies…), sends a consent-scoped referral, reports accepted/completed | file claims; promise housing |
| **Escalation Simulator** | `ACKNOWLEDGED_REQUEST_ONLY` receipts for order-zone cases | imply responders were dispatched |

Messages (A, `integrations/fetch_messages.py`):
- `AlertNotification`, `PollNow`
- `OutreachRequest/OutreachResult` (per alert; the result lists orgs with asked/available/awaiting)
- `MatchRequest/MatchResult`
- `AcceptRequest/AcceptResponse` (role `VOLUNTEER` or `SHELTER`; carries `org_id`)
- `ReportRequest` → `PickupReport` / `ArrivalReport` / `ReportUnavailable`
- `ClosureNotification`, `RouteRequest/RouteResponse`
- `RecoveryRequest/RecoveryResponse`, `ReferralRequest/ReferralResponse`
- `EscalationRequest/Ack`

All 8 agents are on Agentverse with profiles. All carry `schema_version: "2.0"`, `correlation_id`, `case_id`, and an `idempotency_key` when they create something. Agents receive only consent-scoped fields.

## 5. The two MongoDB databases (B)

**Shared needs codes** (`models/needs.py`, also in the contract). Residents' `needs` and volunteers' `needs_they_can_cater` use the **same integer codes**, so matching is code-to-code:

| Code | Need | Code | Need |
|---|---|---|---|
| 1 | WHEELCHAIR (wheelchair-accessible vehicle) | 6 | STEP_FREE_DESTINATION |
| 2 | TRANSFER_ASSIST (help getting in) | 7 | SPANISH_SPEAKER (communication support, **never** a reason to deny) |
| 3 | OXYGEN_EQUIPMENT | 8 | MOBILITY_AID (walker, cane) |
| 4 | PET | 9 | MEDICAL_EQUIPMENT_SPACE |
| 5 | SERVICE_ANIMAL | 10 | CAREGIVER_RIDES_ALONG |

New codes may be added with a contract bump; codes never change meaning.

**`doorstep_users`** (residents + operational data)
```json
// residents
{"_id":"resident_001","name":"Maria (synthetic)","phone":"sim_phone_maria","language":"es",
 "address":{"label":"SYNTHETIC: Zone 3 Sector B","lat":34.1012,"lon":-118.0964,"geocode_confidence":"HIGH"},
 "emergency_contacts":[{"name":"Ana (synthetic)","phone":"sim_phone_ana","relationship":"daughter"}],
 "needs":[1,2,4,6],"pet_count":1,"wants_help_contact":true,
 "consents":{"CHECKIN":true,"TRANSPORT":true,"DESTINATION":true,"RECOVERY":false},"registered_at":"…"}
```
Other collections: `cases`, `communications`, `assignments`, `escalations`, `recovery_requests`, `alerts`, `closures`, `route_previews`, `events` (append-only timeline, monotonic `seq` from a `counters` collection).

**`doorstep_partners.regions`** (rev 3, location-first: `region → orgs → volunteers`). There is one document per **location** (`_id` = region ID, e.g. a county zone or a fixed geo cell). It holds the orgs active there, each with **only its volunteers in that region**:
```json
{"_id":"la_county:zone_2","label":"Zone 2 (synthetic)",
 "center":{"type":"Point","coordinates":[-118.110,34.095]},
 "area":{"type":"Polygon","coordinates":[[[-118.13,34.08],[-118.09,34.08],[-118.09,34.11],[-118.13,34.11],[-118.13,34.08]]]},
 "orgs":[{"org_id":"eastside_rides_demo","name":"Eastside Accessible Rides (fictional)",
   "calamity_types":["WILDFIRE"],"services":["TRANSPORT"],"approved":true,"service_radius_km":25,
   "volunteers":[{"volunteer_id":"volunteer_sarah","name":"Sarah (synthetic)","phone":"sim_phone_sarah",
     "location":{"type":"Point","coordinates":[-118.110,34.095]},
     "vehicle_type":"WHEELCHAIR_VAN","vehicle_seats":2,"wheelchair_spaces":1,"pet_capacity":1,
     "needs_they_can_cater":[1,2,4,7],"approved":true,
     "availability":{"alert_id":null,"state":"UNASKED","responded_at":null},"reserved_case_id":null}],
   "shelter_sites":[],"recovery_services":[]}]}
```
- **Indexes:** `2dsphere` on `center` and `area`; `orgs.org_id`; `orgs.volunteers.volunteer_id` (unique across regions, so each volunteer is in exactly one region).
- **Find help near an alert:**
  1. Query `regions` whose `area` intersects the zone polygon buffered by `service_radius_km` (or `$near` the zone centroid), nearest first.
  2. Keep the approved orgs with the alert's calamity type and the needed service.
  3. Take their volunteers. Volunteer-to-resident distance comes from each volunteer's `location`.
- **Orgs in several places** appear in several region documents, each with only that region's volunteers. Org-level facts (name, approval) are copied along with the `org_id`. A small `organizations` collection keeps the canonical org record for registration and approval changes.
- **`mongomock`** doesn't support geo operators, so tests use B's Shapely fallback over the same documents, which gives the same results. The live demo uses a real MongoDB (local or Atlas).

Also `provider_events` (reservations, with a dedupe key) and `counters`.

**Atomicity without multi-DB transactions:**
- **Reserve a volunteer:** one conditional `update_one` on the **region** document, using `arrayFilters` on `org_id` + `volunteer_id`. It succeeds only if the volunteer's availability is `AVAILABLE` for this alert and `reserved_case_id == null`, and it sets `reserved_case_id`. Re-running it for the same case is safe.
- **Accept:** a `find_one_and_update` on the assignment, allowed only while its status is still PROPOSED or AWAITING_PROVIDER. A partial unique index stops a second accepted assignment for the same case and service.
- **If acceptance fails after the reservation:** a compensating release frees the volunteer.
- **Counters:** `find_one_and_update($inc)`.
- `mongomock` runs all of these in offline tests.

**Volunteer availability is per alert:** `available_to_help` is reset when a new calamity alert starts outreach. Answers from an older alert are ignored.

## 6. Decisions (both agree before coding)

1. **Contract v2.0 → v2.1** (B owns `docs/interface-contract.md`; v2.0 is still unsigned; revision 3 needs the v2.1 changes in §7 and A's review items in `dev-a-notes.md`). Kept from v1: case/resident IDs, Bearer `DEMO_AUTH_TOKEN` on writes, `X-Correlation-ID` echo, error shape, 409 for rule refusals. After A signs off, any change needs a 2.1 bump and both of you agreeing.
2. **Switch-over in one PR window:** B ships v2, A switches the client, both merge together, and the v1 routes are deleted then.
3. **One code path for real and synthetic alerts:** B serves a synthetic feed in **Cal OES's exact GeoJSON format**. The Calamity agent fetches whichever URL is configured. **Real alerts are display-only**; only simulated alerts start check-ins and outreach.
4. **Deterministic core:** zones, eligibility, consent, states and route acceptance are B's tested code. The LLM proposes text; code decides.
5. **Volunteers live in the location-first partner DB** (rev 3): `region → orgs → volunteers`. There is **no agent per org**; the Volunteer Network agent acts on the orgs' behalf through B's API. Per-org data scoping stays in B: every write names its `org_id`, and B checks the volunteer belongs to that org. For Fetch.ai, independence is shown by the 8 separate service agents.
6. **Which orgs get contacted:**
   1. Geo query from the alert's zone polygon to `regions`, nearest first.
   2. In those regions, keep approved orgs whose `calamity_types` include the alert's type (or `ANY`), whose `services` include TRANSPORT, and that are within their own `service_radius_km`.
   3. Contact the closest `OUTREACH_MAX_ORGS` (default 3).
7. **Matching rule:** volunteer and org approved, `available_to_help == true` for **this** alert, not reserved, the resident's needs ⊆ `needs_they_can_cater` (code 7 never blocks), seats ≥ 1 + companions, wheelchair spaces ≥ 1 if code 1, pet capacity ≥ pet count, the resident outside any ORDER/STALE/UNKNOWN zone, and the route from the volunteer's address doesn't pass through an order zone. Rank by distance, then volunteer ID. Shelter: needs ⊆ site `features`, beds ≥ 1, outside order zones.
8. **Branches:** A `feat/fetch-agents`, B `feat/backend-geodata`. Small PRs into `feat/fetch-orchestration`, merged to `main` at freeze.
9. **Ownership:** A owns `agents/`, `workflows/`, `integrations/{fetch_adapter,agentverse_setup,asi_cards,asi_one_client,here_client}.py`, `tests/integration/`, `pyproject.toml`, `.env.example`, `docs/dev-a-notes.md`, `docs/integration-decisions.md`, agent scripts. B owns `models/`, `services/`, `api/`, `demo/`, `integrations/message_simulator.py`, `tests/unit/`, backend scripts, `docs/interface-contract.md`, `docs/dev-b-notes.md`, `docs/decisions.md`, `README.md`. Dependencies go through A: B needs `pymongo`, `mongomock` (dev), `shapely>=2`, `openai`.

## 7. Contract v2.0 summary (full detail in `docs/interface-contract.md`)

| Path | Purpose |
|---|---|
| `GET /health`, `POST /demo/reset` | health (+ DB, last ingest); reseed (token) |
| `POST /residents` | register a resident (§5 shape) |
| `POST /organizations` | register or update an org's canonical record (approval, services, calamity types) |
| `POST /regions/{region_id}/orgs/{org_id}/volunteers` | *(rev 3)* register volunteers where they are; B places each one in a region by its location |
| `GET /regions/near?zone_id=` or `?lat=&lon=&radius_km=` | *(rev 3)* regions near a zone or point, nearest first, with matching orgs and volunteer counts (card data) |
| `POST /alerts/{alert_id}/outreach` | *(rev 3)* the Volunteer Network agent starts outreach for an alert. B picks the regions and orgs (decision 6), marks their approved volunteers `ASKED`, sends the simulated SMS, and returns asked/skipped per org |
| `POST /alerts/{alert_id}/volunteers/{volunteer_id}/availability` | *(rev 3)* records a volunteer's yes/no for that alert (`org_id`, `available`, `responded_at`). An answer for an older alert → 409 `STALE_AVAILABILITY` |
| `GET /demo/feeds/caloes` | synthetic feed in Cal OES shape |
| `POST /alerts/ingest` | Calamity agent posts the raw feed (and failed fetches) → B normalizes, geofences, sends resident check-ins → returns affected cases + **`outreach_orgs`** (closest matching orgs to contact) |
| `GET /alerts/active`, `POST /demo/alerts/trigger` | normalized alerts (+ awareness radius for incident points); demo control incl. `FREEZE_FEED` |
| `GET /cases`, `GET /cases/{id}` | state, `zone_status`, `progress_steps`, `map`, `summary_text`, timeline |
| `POST /cases/{id}/responses` | resident reply (sender check, dedupe, needs confirmation SI/YES) |
| `POST /matches/propose` | `{case_id, idempotency_key, create_proposal}` → B matches against **available volunteers in the org DB** + a shelter site; returns explained eligible/rejected volunteers and, if possible, a `PROPOSED` match with a volunteer reservation |
| `POST /assignments/{id}/accept` | the Volunteer Network agent forwards the volunteer's or shelter's decision (`org_id` plus `volunteer_id` or `site_id`; B checks they belong to this assignment). The pickup point is released only on volunteer acceptance and never returned to Doorstep |
| `POST /assignments/{id}/pickup`, `/arrival` | evidence (PickupReport + resident confirmation; shelter check-in) |
| `POST /cases/{id}/escalate` → `POST /escalations/{id}/ack` | order-zone escalation; `assistance_confirmed:false` always |
| `POST /cases/{id}/recovery` → `POST /recovery/{id}/respond` | after arrival: consent + help types (`TEMPORARY_HOUSING`, `INSURANCE_GUIDANCE`, `SUPPLIES`, `MEDICAL_EQUIPMENT_REPLACEMENT`…) → matched recovery orgs → referral accepted/completed (completed needs evidence) |
| `GET /demo/feeds/news`, `GET /demo/feeds/closures`, `POST /closures/ingest`, `GET /closures` | news + official closures; B sets OFFICIAL_CONFIRMED / UNVERIFIED_REPORT / CONFLICTING / EXPIRED |
| `POST /routes/constraints`, `POST /routes/previews` | avoid areas (order zones + official closures) and cautions for volunteer → resident → shelter; HERE polyline post-check → ILLUSTRATIVE_ONLY / REFUSED / NO_ROUTE_CONFIRMED + ETA label |
| `GET /dashboard/summary`, `GET /dashboard/cases` | card data |
| `/sim/*` | simulator **fallback** for residents and volunteers without a linked ASI:One account, and for tests (inbound, delivery, deadline) |
| `POST /link` | *(rev 4, v2.2)* link an ASI:One address to a resident, volunteer or coordinator with a one-time code |

States: Assistance `UNKNOWN, NEEDS_ASSISTANCE, PROVIDER_ACCEPTED, PICKUP_CONFIRMED, ARRIVAL_CONFIRMED, REQUIRES_COORDINATOR`; Assignment `PROPOSED, AWAITING_PROVIDER, ACCEPTED, DECLINED, CANCELED, COMPLETED, UNRESOLVED`; Zone `ORDER, WARNING, SHELTER_IN_PLACE, OUTSIDE_KNOWN_ZONES, UNKNOWN, STALE`; Recovery `NOT_REQUESTED, REQUESTED, ACCEPTED, COMPLETED, UNRESOLVED`; Volunteer availability `UNASKED, ASKED, AVAILABLE, UNAVAILABLE, NO_REPLY`.

## 8. ASI:One Interactive Cards (the dashboard)

**A0 blocker:** cards aren't in the public ASI:One docs, and `uagents-core` chat content has only text / resource / metadata / session / stream. Verify the Card Playground spec (hackpack, Fetch.ai mentors) before building. Until then, render the deck as structured text.

Deck (each card has a SIMULATION banner, color + text label, a "data as of / source" footer, and a text fallback):
1. **Alert**: zone polygon status, calamity type, source/time, freshness, residents in zone, nearby (awareness radius).
2. **Operations board**: counts by status, unresolved queue, last poll.
3. **Volunteer outreach**: orgs contacted (calamity type, distance), volunteers asked / available / unavailable / no reply.
4. **Resident case**: progress *Requested → Volunteer accepted → Pickup → Arrival* with evidence times.
5. **Match**: chosen volunteer (vehicle, needs covered as chips) + shelter; rejected volunteers with reasons; *Approve*.
6. **Help on the way**: volunteer accepted, illustrative route summary, ETA "estimate, not a guarantee".
7. **Escalation (David)**: unresolved, receipt-only acknowledgment.
8. **Road conditions**: official closures vs unverified reports vs conflicting.
9. **Route**: illustrative route or refusal reason.
10. **Post-calamity help**: help types requested → orgs matched → referral accepted/completed.
11. **Data health (C)**: STALE feed, refusals.

## 9. Research already done (2026-10-17)

- **Cal OES evacuation layer** (includes LA County Genasys): `https://services.arcgis.com/BLN4oKB0N1YSgvY8/ArcGIS/rest/services/CA_EVACUATIONS_CalOESHosted_view/FeatureServer/0/query?where=1=1&outFields=*&outSR=4326&f=geojson`. Fields `COUNTY, CITY, ZONE_NAME, ZONE_ID, STATUS, EVENT_TYPE, EDIT_DATE, STATEWIDE_LAST_UPDATED`.
  - `STATUS` is free text; the live value seen was "Evacuation Order" while the docs say "EVACUATION ORDER", so normalize case and flag unknown values.
  - Refresh is documented as both 5 and 10 min; features vanish for 15 s–1 min during rebuilds. So cancel only on an explicit NORMAL **or** after 2 consecutive polls missing the record.
  - `EVENT_TYPE` was null live, so the calamity type may need a fallback: `UNKNOWN` type → contact orgs supporting `ANY`/all types.
- **ASI:One API:** OpenAI-compatible, `asi1-mini`, tool calling, structured output.
- **HERE (team route code):** reviewed in rev 4; see §0.3 for what is kept and changed. Summary of fixes:
  - closures come from B (official only), not user input;
  - **refuse instead of truncating** above the avoid-area limit;
  - secret seed from env;
  - ambiguous geocode → refuse;
  - durable state (`ctx.storage`, not a global dict);
  - wording never "safe" or "clean".
- **Cards:** see §8.

## 10. Developer A — tasks in order

- **A0 — unblock:** verify the cards spec; check the hackpack judging criteria; investigate the 4 timing-out tests with B; add deps (`pymongo`, `mongomock`, `shapely`, `openai`) and env vars (`MONGODB_URI`, `ASI_ONE_API_KEY`, `HERE_API_KEY`, `ALERT_FEED_URL`, poll intervals, agent seeds/ports).
- **A1 — contract v2.0:** switch `backend_client.py` / `coordinator_actions.py` once B's revised contract lands.
- **A2 — agents (8 total, rev 3):**
  - Calamity Checker (done).
  - **Volunteer Network agent** (rev 3): replaces the per-org agents. Runs outreach for all orgs near an alert, forwards acceptances, reports pickup/arrival, and answers recovery referrals.
  - Matching (done).
  - News.
  - Route (HERE v8, §0.3), with the route card for the volunteer.
  - Rev 4: account linking + role cards in the Doorstep agent (§0.1–0.2); Volunteer Network asks Doorstep to message volunteers.
  - §0.5: the Doorstep agent takes `sender` only from the message envelope and sends `X-Agent-Token: DOORSTEP_AGENT_TOKEN`; the Calamity Checker calls `POST /deadlines/sweep` every poll and forwards the returned `notify` list to Doorstep.
- **A7 — housekeeping:**
  - Add `NETWORK_AGENT_TOKEN`, `DOORSTEP_AGENT_TOKEN`, `MONGODB_PARTNERS_DB` and `REPLY_DEADLINE_MINUTES=15` to `.env.example` (the dependencies are already added).
  - Point the agent tests at B's real routes for closures, routes and the dashboard instead of the test double.
  - Remove the v1 `backend_client.py` and its test in the same PR window in which B removes the v1 routes (§6.2).
  - Post-Calamity (done).
  - Escalation (done).
  - All 8 on Agentverse with profiles, which fits the account's 8-agent cap.
- **A3 — Doorstep flow (LangGraph):** alert → check-ins + parallel volunteer outreach → wait for replies (no busy-waiting; explicit status queries) → match → Volunteer Network agent forwards acceptance → route → "help on the way + ETA" → pickup → arrival → post-calamity offer. Branches: decline → next volunteer; no volunteers → unresolved; order zone → escalation; stale → refusal.
- **A4 — ASI:One:** ASI:One API tool-calling intent with keyword fallback. Commands: start check, operations board, case status, outreach status, approve, confirm pickup/arrival, road conditions, route, recovery, freeze feed.
- **A5 — cards** (§8) on the verified schema.
- **A6 — delivery:** Agentverse URLs, shared ASI:One chat (Maria, David, route, C), video, README Fetch.ai section.

## 11. Developer B — tasks in order

- **B0 — contract:** revise `docs/interface-contract.md` v2.0 for revision 2 and send A the hash.
- **B1 — MongoDB port:**
  - `services/db.py` → Mongo client with two DBs (`MONGODB_URI`, `mongomock` in tests).
  - `services/store.py` keeps its typed-repository interface but over collections.
  - `event_log.py` uses a counters collection.
  - Indexes (partial unique on accepted assignments; unique dedupe keys) and the atomic patterns in §5.
  - Existing services (consent, transitions, verification, intake, templates) are reused unchanged.
- **B2 — registration + needs codes:**
  - `models/needs.py`.
  - Resident documents, plus the **location-first `regions` documents** (§5, rev 3) with `2dsphere` indexes and a Shapely fallback for mongomock.
  - Endpoints: `POST /residents`, `POST /organizations`, `POST /regions/{region_id}/orgs/{org_id}/volunteers`, `GET /regions/near`.
  - Seed (same IDs as rev 2, now placed in regions): Maria (WARNING zone, needs `[1,2,4,6]`), David (ORDER zone, needs `[1]`), and orgs `red_cross_demo` (in two regions), `eastside_rides_demo` (the match: `volunteer_sarah`), `neighbor_sedans_demo` (closer, no wheelchair), `unlisted_vans_demo` (not approved), `flood_only_demo` (wrong calamity type), `civic_shelter_demo`, `recovery_housing_demo`.
- **B3 — alerts + geofencing + outreach list:** synthetic Cal OES feed, `/alerts/ingest` (case-insensitive status, freshness, dedupe, 2-poll cancellation, Shapely `covers`, ORDER dominance, STALE/UNKNOWN), resident check-ins (idempotent per alert and resident), the **region geo query** and `outreach_orgs` selection (decision 6), `POST /alerts/{id}/outreach` and per-alert availability (rev 3), awareness radius for incident points, per-alert availability reset.
- **B4 — matching + states:** decision 7, explained reason codes, volunteer reservation, accept/decline, next volunteer on decline, escalation + ack, Scenario C.
- **B5 — post-calamity:** help types, consent-scoped referral payload, recovery-org matching by `recovery_services`, accepted/completed with evidence.
- **B6 — closures + routes:** feeds, `/closures/ingest` with deterministic states and a road gazetteer; `/routes/constraints` (volunteer → resident → shelter, avoid order zones + official closures, cautions for unverified, refuse if stale or too many areas) and `/routes/previews` post-check.
- **B7 — card data, API, scripts, docs:**
  - `/dashboard/*`, `progress_steps`, `summary_text`.
  - Scenarios A, B, C + outreach + route refusal in `demo/scenarios.py`.
  - `smoke_test.sh` with mongomock or a local Mongo; no Fetch/HERE/ASI:One keys.
  - Update `dev-b-notes.md`, `decisions.md`, README.
  - Spanish templates reviewed by a fluent speaker.
- *B0–B7 are done (see §3); the Spanish review still needs a fluent speaker.*
- **B8 — rev 4 (contract v2.2, §0.4 + §0.5), next:**
  1. Contract v2.2 in `docs/interface-contract.md`: the `contact` field, `POST /link`, `notify` lists, the `sender` check, resident pickup via ASI:One, `NOT_REACHABLE`, `reply_by`, and `POST /deadlines/sweep`.
  2. Linking: seeded one-time codes for Maria, David, Sarah and a coordinator; a spent or unknown code gets a 409; `DOORSTEP_AGENT_TOKEN` is required.
  3. `notify` lists instead of simulated SMS for check-ins, volunteer outreach, help on the way and the after-arrival question. People with a `SIM` contact still go through the simulator.
  4. Sender check (401 without the Doorstep token, 403 on a mismatch), resident pickup confirmation via ASI:One, `NOT_REACHABLE` for people who never linked.
  5. The 15-minute deadline (§0.5.3): applied whenever data is read, plus `POST /deadlines/sweep`. A volunteer becomes `NO_REPLY` (not available). A resident becomes `NO_REPLY_AFTER_DEADLINE` and goes to the unresolved queue. Late answers count.
  6. Tests (including a simulated clock for the deadline), smoke test, README, decisions, dev-b-notes.

## 12. Checkpoints

| # | A | B | Joint check |
|---|---|---|---|
| C1 | cards spec, hackpack criteria, deps/env, timeouts | contract v2.0 (rev 2) committed | **sign off on the contract** |
| C2 | client on v2.1, Calamity agent, Volunteer Network agent | Mongo port, location-first regions + geo query, registration, ingest + geofence, outreach | alert → check-ins + volunteer outreach near the zone, end to end |
| C3 | Matching, accept via the Volunteer Network agent, cards for match/case | matching, reservation, evidence | **Maria matched, accepted, picked up, arrived in ASI:One** |
| C4 | Escalation + Post-Calamity agents | escalation ack, recovery referrals | **David unresolved; Maria post-calamity referral** |
| C5 | News + Route (HERE) agents, road conditions + **volunteer route card**, account linking + role cards | closures, route constraints + post-check, FREEZE_FEED, contract v2.2 (link, notify, sender check, 15-min deadline + sweep) | **three teammates on three ASI:One accounts run Maria end to end; a volunteer who doesn't answer becomes NO_REPLY and the next one is asked; route avoids the official closure and cautions on the unverified one; refusal; Scenario C** |
| C6 | all agents on Agentverse, shared chat, video | README, smoke, reset, Spanish review | **freeze → merge to `main` → rehearse from reset** |

**No-wait rule:** A tests against B's real app in-process (mongomock-backed); B tests API-only with a fake agent caller. HERE and ASI:One are mocked on both sides.

## 13. Tests

- **B (offline, mongomock):**
  - polygon inside / outside / **edge**; overlapping zones; feed canceled/expired/stale/malformed/empty/unavailable;
  - 10 identical ingests → 1 check-in and 1 outreach per volunteer;
  - rebuild gap; fire incident or radius ≠ order;
  - regions found by geo query, nearest first (including a point on the zone polygon's edge, and radius limits); only approved orgs with the matching calamity type are selected; an org in two regions contributes only that region's volunteers; a volunteer can't be recorded under the wrong org;
  - stale availability from an old alert ignored; needs ⊆ capabilities (code 7 never blocks); wheelchair, pet, seat and oxygen limits;
  - volunteer reserved once (concurrent accepts → one wins); decline → next volunteer;
  - news never official; official closure avoided; route crossing an order zone refused;
  - recovery without consent shares nothing; completed needs evidence;
  - plus all existing invariants (acceptance ≠ pickup ≠ arrival, silence ≠ danger, failed delivery ≠ no reply, ack ≠ assistance, unknown sender).
- **A (integration):** each agent pair over Bureau; Volunteer Network outreach for an alert; decline → next volunteer; restart mid-workflow without duplicates; correlation ID across hops; cards + text fallback; LLM never changes a status string.
- **Together:** Maria, David, route, Scenario C from ASI:One.

## 14. Demo (3 min)

0:00 problem → 0:15 Calamity agent detects simulated wildfire zones (Alert card) → 0:30 check-ins + Volunteer Network outreach to the closest fire-capable orgs, found by location (Outreach card); volunteers answer → 0:50 Maria replies in Spanish; needs confirmed → 1:05 Matching agent: Sarah's wheelchair van matched, closer sedan rejected (Match card) → 1:15 News agent: official closure + unverified report → Route agent: HERE route avoiding the order zone and the closure (Route card) → 1:30 "help is on the way, ETA ~18 min (estimate)" → pickup → arrival (green) → 1:50 Post-Calamity: housing + insurance guidance referral → 2:05 David: order zone, escalation receipt only, unresolved → 2:20 freeze feed: STALE, refusals → 2:35 Agentverse agents + shared chat → 2:50 limits: simulation, partner-led future.

## 15. Fetch.ai submission checklist

- [ ] Doorstep agent chattable in ASI:One; Agentverse URLs + profiles for every agent
- [ ] Real agent messages: alerts, outreach, matching, acceptance, pickup/arrival, closures, routes, recovery, escalation
- [ ] ASI:One API for intent and extraction (never safety), documented
- [ ] Interactive Cards on the verified schema (or a documented fallback)
- [ ] Public ASI:One shared chat: Maria, David, route, Scenario C
- [ ] README (setup incl. MongoDB, architecture, agent list, simulation/safety statement); demo video + backup
- [ ] Synthetic people, orgs, volunteers and addresses only; real feed display-only; every card says SIMULATION

## 16. Prompts for each Claude Code session

**Developer A:**
> You are Developer A on Doorstep V2 (Fetch.ai track; Fetch-first everywhere). Read `docs/DOORSTEP_V2_TEAM_PLAN.md` (this plan, revision 4 incl. the §0.5 amendments), `docs/interface-contract.md` (v2.1; v2.2 once B commits it), and the two spec documents; this plan wins on scope. Work on `feat/fetch-agents` in A-owned files only (§6.9). Do A0 first (verify the ASI:One Interactive Cards spec from official sources before building cards). Then switch the backend client to contract v2.0 and build the agents in §4: Doorstep, Calamity Checker, one Volunteer Network agent for all partner orgs (no agent per org), Matching, News, Route (adapt the team's HERE code with the §9 fixes), Post-Calamity, Escalation. Add the LangGraph flow (§10 A3), ASI:One API tool-calling intent with keyword fallback, and the card deck (§8) with text fallback. The LLM never decides eligibility, zones, consent or status. Never invent endpoints, MCP commands or card schemas. Everything simulated and DEMO-labeled. Report commit hashes, payloads, agent URLs and test results at each checkpoint (§12).

**Developer B:**
> You are Developer B on Doorstep V2 (Fetch.ai track). Read `docs/DOORSTEP_V2_TEAM_PLAN.md` (revision 4 incl. the §0.5 amendments), `docs/interface-contract.md`, and the two spec documents. Work on `feat/backend-geodata` in B-owned files only (§6.9). B0–B7 are done; next is B8 (§11). Originally: first revise the contract to v2.1 for revision 3 (location-first regions, `/regions/near`, `/alerts/{id}/outreach`, network accept) and send A the hash. Then finish MongoDB storage (two DBs, location-first `regions` documents with 2dsphere indexes + Shapely fallback, §5 shapes, atomic conditional updates, mongomock tests), add needs codes and registration, the Cal-OES-shaped synthetic feed with `/alerts/ingest` + Shapely geofencing + STALE/UNKNOWN + outreach-org selection, volunteer availability per alert, matching against volunteers found by region geo query, with reservation, escalation, post-calamity referrals, closures with deterministic states, route constraints + HERE polyline post-check, card data, and Scenarios A/B/C in API-only tests and the smoke test (no Fetch/HERE/ASI:One keys). Real feed data is display-only. Missing or stale data never means safe.


## 17. Getting a HERE API key (for the Route agent)

Source: HERE docs, [How to create an App ID, API key and token credentials](https://docs.here.com/here-kb/docs/how-to-create-an-app-id-api-key-and-token-credentials-on-here-s-platform) and [Using API keys](https://docs.here.com/identity-and-access-management/docs/plat-using-apikeys).

1. Sign in (or sign up) at **platform.here.com**.
2. Open the launcher menu and choose **Access Manager**.
3. On the **Apps** tab, click **Register new app** and give it a name (e.g. `doorstep-demo`). HERE creates an app ID.
4. For **Default access to a project**, keep **No project**. HERE's knowledge base recommends this, and it lets the key reach all location-service APIs, including Routing v8.
5. Open the app's **Credentials** tab → **API Keys** → **Create API key** (at most two keys per app). If the Credentials tab is missing or greyed out, you lack manager rights for that app.
6. Copy the key and paste it into your local `.env` as `HERE_API_KEY=...`. **Never commit it, paste it in chat, or put it in a card or image URL** (the Route agent calls HERE server-side only).
7. Optional: restrict the key. Trusted domains apply to browser use; changes can take up to 30 minutes.

The Freemium/Base plan includes a free monthly allowance (check the current numbers on HERE's pricing page); a hackathon demo uses a tiny fraction of it. Tests mock HERE and need no key.
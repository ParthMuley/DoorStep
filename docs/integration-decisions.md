# Fetch.ai / ASI:One integration decisions

Owner: Developer A. Every claim here comes from official docs or the installed SDK — source recorded. Nothing is assumed.

## Versions

| Package | Version | Source |
|---|---|---|
| Python | 3.12 (venv) | `py -3.12` |
| uagents | 0.26.1 | PyPI latest on 2026-10-17 |
| uagents-core | 0.4.12 | PyPI latest on 2026-10-17 |
| langgraph | 1.2.16 | PyPI latest on 2026-10-17 |
| pydantic | 2.14.1 | installed alongside uagents without conflict |

## Findings

| Question | Status | Finding + source |
|---|---|---|
| Chat protocol import path and message types | confirmed | `uagents_core.contrib.protocols.chat`: `ChatMessage(timestamp, msg_id, content)`, `ChatAcknowledgement(timestamp, acknowledged_msg_id, metadata)`, `TextContent(type, text)`, `EndSessionContent`, `chat_protocol_spec`. Source: installed SDK + [uAgents ASI:One example](https://uagents.fetch.ai/docs/examples/asi-1) |
| uagents `Model` base | confirmed | `uagents_core.models.Model` subclasses **`pydantic.v1.BaseModel`**. Agent message models use v1 API (`.dict()`, `.parse_raw()`); B's API models are pydantic v2. Keep them as separate types and convert at the boundary (dict/JSON). Source: installed SDK MRO |
| Publishing the manifest | confirmed | `agent.include(chat_proto, publish_manifest=True)`. Source: official example |
| Discoverability | confirmed | `Agent(..., mailbox=True, publish_agent_details=True, readme_path=..., description=..., handle=...)`. README/description are shown on the Agentverse profile. Source: SDK signature + official example |
| Mailbox connection for a local agent | confirmed (docs), pending manual step | Run agent → open printed Inspector URL → **Connect → Mailbox** (needs the user's Agentverse login). Until then the log shows `Agent mailbox not found`. Source: official example |
| Chatting from ASI:One | confirmed (docs), pending manual step | Inspector → Agent Profile → **Chat with Agent** opens ASI:One with the agent selected. Agent process must stay online. Source: official example |
| Almanac registration | confirmed | `Registration on Almanac API successful` at startup. Warning "not enough funds to register on Almanac contract" is the optional on-chain path; does not block chat. Source: our run log + Fetch hackpack note |
| Agent-to-agent request/response | confirmed | `ctx.send_and_receive(destination, message, response_type, sync=False, timeout=30) -> (Model | None, MsgStatus)` exists in 0.26.1; waits on a dispatcher future (no busy loop) and returns `None` + FAILED status on timeout. Use it in the coordinator for provider fan-out. Coordinator also sets `handle_messages_concurrently=True`. Source: installed SDK source |
| Unsolicited agent → ASI:One user messages (push) | confirmed (live, 2026-10-17) | The `test push` command replied, then a `ChatMessage` sent 15 s later with no new user message appeared in the ASI:One chat. So the Doorstep agent can push alert/journey updates to the last ASI:One sender; status cards stay as the pull fallback. |
| Async reply to ASI:One after awaiting providers | design | The chat handler awaits `send_and_receive` to each provider, then `ctx.send(sender, ChatMessage)`. No pending map needed. Verify end-to-end in Step 2. |
| ASI:One LLM API (intent) | confirmed (live, 2026-10-17) | Models listed by the API: `asi1-mini`, `asi1`, `asi1-ultra`. Tool calling works on `asi1-mini` (0.5–0.7 s) and `asi1` (~0.9 s). `integrations/asi_one_client.py`: the model only picks one allow-listed tool (enum-validated args); replies always come from actions/B. A model-chosen resident must be named in the message, otherwise the coordinator asks; never guesses. Errors/timeouts (8 s) fall back to keywords. Enabled by `USE_LLM_INTENT=true` + `ASI_ONE_API_KEY`; model via `ASI_ONE_MODEL` (default `asi1-mini`). Earlier note: | OpenAI-compatible: `base_url="https://api.asi1.ai/v1"`, model `asi1`. Source: official example. Only used to map free text → known command; behind `USE_LLM_INTENT`. |
| ASI:One Interactive Cards / Card Playground | confirmed (docs) | See section below. Sources: [ASI interactive cards](https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards), [predefined card schemas](https://docs.agentverse.ai/documentation/advanced-usages/predefined-card-schemas), [Card Playground](https://asi1.ai/developer/card-playground) |
| Official MCP server for Agentverse registration | confirmed (docs) | Agentverse MCP: main `https://mcp.agentverse.ai/sse`, lite `https://mcp-lite.agentverse.ai/mcp`; needs an Agentverse API token. Tool groups: Agents & Hosting (create/update/upload code/start/stop/logs), Marketplace Search, Storage, Secrets, Almanac, Mailbox, Health. It is a **developer-side** management tool, not agent transport. Hosted agents it creates have a curated import allowlist and can't reach our local backend, so Doorstep agents stay **local uAgents with mailboxes**. Use the MCP for inspection (logs, mailbox status, marketplace search) once connected; Claude Code connection command and auth header are not documented on the page — confirm before configuring. Source: [Agentverse MCP docs](https://docs.agentverse.ai/documentation/advanced-usages/agentverse-mcp) |
| Automatic mailbox registration (no Inspector click) | implemented | `integrations/agentverse_setup.py` POSTs `AgentverseConnectRequest{user_token, agent_type:"mailbox"}` to the agent's own `/connect` REST route at startup — the exact call the Inspector's Connect button makes (`uagents/agent.py` `_handle_connect` → `register_in_agentverse`). Enabled only when `AGENTVERSE_API_KEY` is set; providers then default to mailbox mode. |
| ASI autocomplete API purpose | open | Not used for agent transport. |
| ASI:One shared-chat URL | open | |

## Live evidence (2026-10-17)

- All three agents registered as Agentverse mailbox agents automatically at startup (`Successfully registered as mailbox agent in Agentverse`), no Inspector clicks.
  - Coordinator: `agent1qfnlwm4d4tm9pwczcmc4d3y76qr2df3kq732tyelpq00fklmrn7h2f3qqz0`
  - Transport provider: `agent1qd3gnx9qmtdswprn88q2gjsfkjcm8zw8gd8fktt0565wrl7q2v6vwmx52hh`
  - Destination provider: `agent1qtdt9wgqmwdaay0m7rjj7g8uv7hfl2n8qlneht5k6zzn2nlh8v73wmrppwc`
- `scripts/chat_probe.py` (separate process) → Coordinator via Agentverse mailbox → Transport + Destination via their mailboxes → reply with 5 vehicles / 3 sites in ~21 s. Same `correlation_id` (`corr_001c6c5696c0`) logged by all three agents.
- Pitfall seen: an ASI:One `sk_` key is not an Agentverse key; Agentverse returns `Could not validate credentials`. Agentverse keys are JWTs from agentverse.ai → API Keys.

## Local evidence

- Coordinator address (local seed from `.env`): `agent1qfnlwm4d4tm9pwczcmc4d3y76qr2df3kq732tyelpq00fklmrn7h2f3qqz0`
- `tests/integration/test_fetch_coordinator_chat.py`: Bureau round-trip — ChatMessage → ChatAcknowledgement + DEMO-labeled reply. Passing.

## Integration with Developer B's backend (Step 3, 2026-10-17)

B's merged API (PR #1, commit 7244c28) implements `docs/interface-contract.md` v1.0 §3 as written: Bearer `DEMO_AUTH_TOKEN`, `X-Correlation-ID`, `/cases/{id}/transport|destination/evaluate` taking raw offers, 409 for business-rule refusals. (An earlier draft of B's notes used different routes; that is superseded.)

Flow implemented (`agents/coordinator_actions.py`, `workflows/backend_client.py`):
1. `GET /cases/{id}` → needs, consent, `needs_confirmed`, `zone_rule`. 404 means no case yet (cases are created only by a verified simulated warning).
2. If needs are unconfirmed or consent is missing, no provider is contacted.
3. Consent-scoped requirements → `OfferRequest` to Transport and Destination agents over Fetch.ai (`send_and_receive`, concurrent).
4. Agents return contract-shaped raw offers (own inventory; approval is not self-declared).
5. Raw offers → B's `/evaluate`; B's registry + deterministic matching decide eligibility and reasons.
6. Reply built from B's result; "Nothing is assigned yet" until a provider accepts.

Live evidence: via Agentverse mailboxes, after "Start the simulated Zone 3 readiness check" and Maria's simulated SMS reply + confirmation, "Show available suitable providers for Maria" returned eligible `transport_org_a` (#1), `transport_org_e` (#2), `destination_org_a`; rejected `transport_org_b` (NOT_WHEELCHAIR_ACCESSIBLE, NO_TRANSFER_ASSISTANCE), `transport_org_c` (PROVIDER_NOT_APPROVED), `transport_org_d` (PETS_NOT_ALLOWED), `destination_org_b` (NOT_STEP_FREE), `destination_org_c` (PETS_NOT_ALLOWED) — identical to B's expected results.

No in-memory FakeBackend: B's real app runs in-process for tests (`httpx.ASGITransport`, in-memory SQLite), which is stricter than a fake.

## ASI:One Interactive Cards (verified from docs, 2026-10-17)

- **Transport:** a `ChatMessage` carrying a `TextContent` (narration, which must also work as the plain-text fallback) plus one `MetadataContent(type="metadata", metadata={...})`. `metadata` is `dict[str, str]`:
  - `card_protocol_version: "1"`. If it's missing, the card is silently dropped.
  - `requires_card_interaction: "true"` for interactive cards.
  - `card_kind`: `carousel | detail | form | review | custom`.
  - `card_payload`: `json.dumps(payload)`, at the top level with no wrapper.
  - Optional: `is_terminal: "true"` for informational cards with no actions, and `preferred_drawer_width_px` (320–800).
- **Limits:** payload ≤ 64 KB, custom element trees ≤ 8 levels deep. Unknown kinds or invalid payloads are shown as **plain text**, so the narration must stand on its own.
- **Payload shapes:**
  - `carousel{title, subtitle, items[{id, image, title, subtitle, badges[{label, variant}], secondary_text, primary_cta{label, selection}}]}`
  - `detail{title, hero_image, summary_rows[{label, value}], sub_options{name, kind:"radio", label, choices[{value, label, secondary_text}]}, ctas[{label, selection, primary?}]}`
  - `form{title, fields[{name, kind: text|number|email|select|checkbox, label, required?, options?}], submit_cta}`
  - `review{title, summary_rows, approve_cta{label, selection, primary?}, reject_cta{label, selection}}`
- **Interactions come back** as a new `ChatMessage` whose text is either JSON of the `selection` (merged with sub-option or form values), when the user @mentions the agent, or planner prose that mentions the selection values. **Parse JSON first, then fall back to keyword text.**
- **Validate** every payload in the [Card Playground](https://asi1.ai/developer/card-playground) before relying on it live. The Playground enforces the runtime schema.
- **Live result (2026-10-17):** the `detail` case card rendered in ASI:One, and its Refresh button sent the selection back and got a new card.
- **Doorstep rules:** every card's title starts with `SIMULATION`; statuses are shown as color **and** text label; footer row "Data as of <time> · source <x>"; status words are copied verbatim from B; never "safe".

## Agentverse limits found live (2026-10-17)

- **Agent name ≤ 32 characters** (`uagents_core.registration.RegistrationRequest.name`). Longer names fail mailbox registration with `string_too_long`. Org agents are therefore named `doorstep_<org_id>`.
- **Per-account agent cap:** the current Agentverse plan allows **8** agents (`Agent limit reached 10/8`). Doorstep V2 needs 10 now and 12 with News and Route. Options: delete stale agents (old v1 Transport/Destination), host some agents on a second account (e.g. B's API key), or upgrade. Meanwhile `LOCAL_ONLY_AGENTS` runs the overflow agents on local endpoints. They remain Fetch.ai agents registered on the Almanac and are reachable from the other agents on the same machine, but they have no Agentverse mailbox or profile page.

## Live V2 journey (2026-10-17, dev backend = B's app + v2 test double)

`scripts/journey_probe.py` drove the full journey against the live Doorstep agent through Agentverse in about 50 s:
- Start check → Calamity Checker `AlertNotification` → **pushed** Alert card and Outreach card (3 orgs, simulated volunteer replies).
- Maria: simulated SMS + SI → Matching agent proposal (Sarah eligible #1, Lee #2, Joe's sedan rejected `NO_WHEELCHAIR_SPACE`) → approve → org agents accept (volunteer + shelter) → Help on the way (ETA labeled an estimate) → pickup (blue) → arrival (green) → consent card → Post-Calamity referrals ACCEPTED, housing not secured.
- David: no match `ORDER_ZONE` → escalate → Escalation agent `ACKNOWLEDGED_REQUEST_ONLY`, unresolved.

Transcript: `var/logs/journey_probe.txt` (local, not committed).

## uagents pitfall: concurrent `send_and_receive` to one agent (2026-10-17)

`ctx.send_and_receive` matches the reply by (sender, destination, session). Two **concurrent** calls from one handler to the **same** destination collide: one reply is lost and that call times out. We found this when per-org agents became one Volunteer Network agent (approve sent volunteer + shelter acceptance in parallel; Post-Calamity sent referrals in parallel). Calls to the same agent are now sequential. Concurrent calls to *different* agents are fine.

## Rev 3 live run (2026-10-17)

The same journey ran live with **one Volunteer Network agent** instead of 5 org agents. The Outreach card lists orgs by region, nearest first (`neighbor_sedans_demo · la_county:zone_3 (0.9 km)`, `eastside_rides_demo · la_county:zone_2 (4.1 km)`, `red_cross_demo · la_county:zone_4 (7.9 km)`). The Agentverse account still holds stale agents (`Agent limit reached 10/8`), so the Volunteer Network and Calamity Checker ran on local endpoints (`LOCAL_ONLY_AGENTS`).

## All agents on Agentverse mailboxes (2026-10-17)

- At the user's request, five stale registrations were removed with the SDK's `uagents.mailbox.unregister_in_agentverse` (the Inspector's Disconnect call): the old v1 Transport and Destination agents and the Eastside, Red Cross and Civic Shelter org agents. Each now returns 404 on `GET {agents_api}/{address}`.
- **Now on mailboxes:** Doorstep, Volunteer Network, Matching, Escalation, Post-Calamity, Calamity Checker (6 of the account's 8). `LOCAL_ONLY_AGENTS` is empty.
- **The 2 remaining slots** are for the News and Route agents.
- **Live journey probe:** 58 s end to end, every hop through Agentverse.

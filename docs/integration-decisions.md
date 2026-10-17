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
| Async reply to ASI:One after awaiting providers | design | The chat handler awaits `send_and_receive` to each provider, then `ctx.send(sender, ChatMessage)`. No pending map needed. Verify end-to-end in Step 2. |
| ASI:One LLM API (intent fallback) | confirmed (docs) | OpenAI-compatible: `base_url="https://api.asi1.ai/v1"`, model `asi1`. Source: official example. Only used to map free text → known command; behind `USE_LLM_INTENT`. |
| ASI:One Interactive Cards / Card Playground | open | |
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

## Reconciliation with Developer B's as-built API (2026-10-17)

B's notes (`dev-b-notes.md`) define the real HTTP API; it supersedes §3 of `docs/interface-contract.md` where they differ. Key differences A adapts to:
- Auth header `X-Demo-Token` (not Bearer). Env `DOORSTEP_DEMO_TOKEN`.
- `find_transport` = `POST /transport/find {case_id}`; B's backend evaluates its seeded provider inventory and returns offers with `eligible` + `reasons`.
- `propose_assignment` = `POST /assignments/propose {case_id, offer_id}`; `accept_assignment` = `POST /assignments/{id}/respond {provider_id, accept}`.
- `GET /cases/{id}` returns `summary_text` — use it as the ASI:One plain-text status.

**How provider agents stay genuine:** Transport/Destination agents keep their own inventory JSON and answer `OfferRequest` over Fetch.ai (they may reuse B's pure `doorstep.services.matching` functions). Coordinator then calls B's `/transport/find` for the authoritative, re-checked offer IDs, proposes, sends `AcceptRequest` to the matching provider agent over Fetch.ai, and forwards the agent's decision to `/assignments/{id}/respond`. The provider's decision comes from the agent; B's backend stays the source of truth for state.

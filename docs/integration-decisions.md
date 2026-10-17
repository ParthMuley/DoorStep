# Fetch.ai / ASI:One integration decisions

Owner: Developer A. Every claim here must come from official docs or the installed SDK — record the source. Nothing is assumed.

## Versions

| Package | Version | Source |
|---|---|---|
| Python | 3.12 (venv) | `py -3.12` |
| uagents | 0.26.1 | PyPI latest on 2026-10-17 |
| uagents-core | 0.4.12 | PyPI latest on 2026-10-17 |
| langgraph | 1.2.16 | PyPI latest on 2026-10-17 |

## To verify (status: open / confirmed / not available)

| Question | Status | Finding + source |
|---|---|---|
| Chat protocol import path and message types (`ChatMessage`, `ChatAcknowledgement`, `TextContent`, `chat_protocol_spec`) | open | |
| `agent.include(proto, publish_manifest=True)` publishes the manifest ASI:One needs | open | |
| `mailbox=True` + Agentverse Inspector "Connect" flow for a locally running agent | open | |
| How ASI:One discovers/routes to an agent (handle, README/description, keywords) | open | |
| Agent-to-agent request/response: `ctx.send` + `on_message` vs `ctx.send_and_receive` | open | |
| Can one uAgent reply to the ASI:One sender after awaiting other agents (async reply) | open | |
| ASI:One Interactive Cards / Card Playground schema | open | |
| Official MCP server for Agentverse registration | open | |
| ASI autocomplete API purpose (not used for agent transport unless docs say so) | open | |
| ASI:One LLM API for intent fallback (endpoint, model name) | open | |
| ASI:One shared-chat URL for submission | open | |

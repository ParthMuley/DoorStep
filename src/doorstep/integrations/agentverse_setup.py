"""Automatic Agentverse mailbox registration.

Does exactly what the Agent Inspector's "Connect -> Mailbox" button does: POSTs an
AgentverseConnectRequest to the agent's own local `/connect` REST endpoint, which proves
the agent's identity to Agentverse and registers its mailbox and profile. Uses only the
agent's public REST interface, no private SDK attributes.

Requires AGENTVERSE_API_KEY in .env. The key is never logged.
Re-running on every start is safe: it re-registers and refreshes the profile/README.
"""

import asyncio
import os

import httpx
from uagents import Agent, Context

CONNECT_ATTEMPTS = 10


def agentverse_api_key() -> str:
    return os.getenv("AGENTVERSE_API_KEY", "").strip()


def enable_auto_mailbox(agent: Agent, port: int) -> None:
    """Register a startup hook that connects this agent's mailbox. No-op without an API key."""
    if not agentverse_api_key():
        return

    @agent.on_event("startup")
    async def connect_mailbox(ctx: Context):
        # The REST server may not be listening yet when startup hooks run; retry in the background.
        asyncio.create_task(_connect(ctx, port))


async def _connect(ctx: Context, port: int) -> None:
    payload = {"user_token": agentverse_api_key(), "agent_type": "mailbox"}
    url = f"http://127.0.0.1:{port}/connect"
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(CONNECT_ATTEMPTS):
            try:
                resp = await client.post(url, json=payload)
            except httpx.TransportError:
                await asyncio.sleep(1)
                continue
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code == 200 and body.get("success"):
                ctx.logger.info("Agentverse mailbox connected automatically")
            else:
                ctx.logger.error(f"Agentverse mailbox registration failed: HTTP {resp.status_code} {body.get('detail', '')}")
            return
    ctx.logger.error("Agentverse mailbox registration failed: agent REST endpoint not reachable")

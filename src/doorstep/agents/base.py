"""Shared construction for Doorstep uAgents: seed + port from env, Agentverse mailbox
(automatic when AGENTVERSE_API_KEY is set), profile README, and address lookup."""

import os
from pathlib import Path

from uagents import Agent, Context
from uagents.crypto import Identity

from doorstep.integrations.agentverse_setup import agentverse_api_key, enable_auto_mailbox

PROFILES = Path(__file__).parent / "profiles"

# Default ports (override with <ROLE>_PORT).
DEFAULT_PORTS = {"COORDINATOR": 8101, "TRANSPORT": 8102, "DESTINATION": 8103, "CALAMITY": 8104,
                 "MATCHING": 8105, "ESCALATION": 8106, "POSTCALAMITY": 8107, "NEWS": 8108, "ROUTE": 8109,
                 "NETWORK": 8110}


def seed_for(env_name: str) -> str:
    seed = os.getenv(env_name, "").strip()
    if not seed:
        raise SystemExit(f"{env_name} is not set. Copy .env.example to .env and fill it in.")
    return seed


def address_for(role: str) -> str:
    """Address of a Doorstep agent by role (COORDINATOR, MATCHING, ...): explicit
    <ROLE>_AGENT_ADDRESS, else derived from <ROLE>_SEED."""
    role = role.upper()
    explicit = os.getenv(f"{role}_AGENT_ADDRESS", "").strip()
    if explicit:
        return explicit
    return Identity.from_seed(seed_for(f"{role}_SEED"), 0).address


def build_agent(name: str, seed: str, port: int, profile: str, b_role: str | None = None,
                description: str = "") -> Agent:
    """Mailbox agent on Agentverse when an API key is configured (PROVIDER_USE_MAILBOX=false
    forces local-only endpoints for fast development). `b_role` registers the agent's
    address with B at startup (`PUT /agents/{role}`, contract v2.1)."""
    agent = _build(name, seed, port, profile, description)
    if b_role:
        register_with_backend(agent, b_role)
    return agent


def register_with_backend(agent: Agent, b_role: str) -> None:
    @agent.on_event("startup")
    async def publish_address(ctx: Context):
        from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2  # avoid import cycle
        try:
            await DoorstepBackendV2().register_agent(b_role, ctx.agent.address, f"corr_register_{b_role}")
            ctx.logger.info(f"registered address with backend as {b_role}")
        except (BackendError, OSError) as err:  # backend down: agents still run; B lacks the address
            ctx.logger.warning(f"could not register with backend as {b_role}: {type(err).__name__}")


def _build(name: str, seed: str, port: int, profile: str, description: str) -> Agent:
    use_mailbox = os.getenv("PROVIDER_USE_MAILBOX", "true" if agentverse_api_key() else "false").lower() == "true"
    # Agentverse plans cap the number of agents per account; agents listed here run on a
    # local endpoint instead (still Fetch.ai agents on the Almanac, reachable on this machine).
    local_only = {n.strip() for n in os.getenv("LOCAL_ONLY_AGENTS", "").split(",") if n.strip()}
    if use_mailbox and name not in local_only:
        agent = Agent(name=name, seed=seed, port=port, mailbox=True, publish_agent_details=True,
                      readme_path=str(PROFILES / profile), description=description)
        enable_auto_mailbox(agent, port)
        return agent
    return Agent(name=name, seed=seed, port=port, endpoint=[f"http://127.0.0.1:{port}/submit"])


def role_port(role: str) -> int:
    return int(os.getenv(f"{role.upper()}_PORT", str(DEFAULT_PORTS[role.upper()])))

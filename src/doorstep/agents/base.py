"""Shared construction for Doorstep uAgents: seed + port from env, Agentverse mailbox
(automatic when AGENTVERSE_API_KEY is set), profile README, and address lookup."""

import os
from pathlib import Path

from uagents import Agent
from uagents.crypto import Identity

from doorstep.integrations.agentverse_setup import agentverse_api_key, enable_auto_mailbox

PROFILES = Path(__file__).parent / "profiles"

# Default ports (override with <ROLE>_PORT). Org agents use ORG_PORT_BASE + index.
DEFAULT_PORTS = {"COORDINATOR": 8101, "TRANSPORT": 8102, "DESTINATION": 8103, "CALAMITY": 8104,
                 "MATCHING": 8105, "ESCALATION": 8106, "POSTCALAMITY": 8107, "NEWS": 8108, "ROUTE": 8109}
ORG_PORT_BASE = 8111
DEMO_ORGS = ["eastside_rides_demo", "neighbor_sedans_demo", "red_cross_demo", "civic_shelter_demo",
             "recovery_housing_demo"]


def org_env_key(org_id: str) -> str:
    return org_id.upper()


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


def org_address(org_id: str) -> str:
    explicit = os.getenv(f"ORG_AGENT_ADDRESS_{org_env_key(org_id)}", "").strip()
    if explicit:
        return explicit
    return Identity.from_seed(seed_for(f"ORG_SEED_{org_env_key(org_id)}"), 0).address


def build_agent(name: str, seed: str, port: int, profile: str, description: str) -> Agent:
    """Mailbox agent on Agentverse when an API key is configured (PROVIDER_USE_MAILBOX=false
    forces local-only endpoints for fast development)."""
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

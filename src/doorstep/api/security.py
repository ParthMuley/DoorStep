"""Demo authorization: ``Authorization: Bearer <DEMO_AUTH_TOKEN>`` on write endpoints.

Demo gating only, not production auth. Set DEMO_AUTH_TOKEN in .env.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException

DEFAULT_DEMO_TOKEN = "change-me-local-demo-token"  # matches .env.example


def expected_token() -> str:
    return os.environ.get("DEMO_AUTH_TOKEN") or DEFAULT_DEMO_TOKEN


def require_demo_token(authorization: str | None = Header(default=None)) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token, expected_token()):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization: Bearer token")


def correlation_header(x_correlation_id: str | None = Header(default=None)) -> str | None:
    return x_correlation_id


DEFAULT_NETWORK_TOKEN = "change-me-network-agent-token"  # never commit a real value


def network_token() -> str:
    return os.environ.get("NETWORK_AGENT_TOKEN") or DEFAULT_NETWORK_TOKEN


def require_agent_token(x_agent_token: str | None = Header(default=None)) -> None:
    """Network-acting routes (contract v2.1 §1): only the Volunteer Network agent holds this token."""
    if not x_agent_token or not hmac.compare_digest(x_agent_token, network_token()):
        raise HTTPException(status_code=403, detail="Missing or invalid X-Agent-Token")


# Contract v2.2 (plan rev 4 §0.5): one token per agent role. Never commit real values.
AGENT_TOKEN_DEFAULTS = {
    "DOORSTEP": ("DOORSTEP_AGENT_TOKEN", "change-me-doorstep-agent-token"),
    "ROUTE": ("ROUTE_AGENT_TOKEN", "change-me-route-agent-token"),
    "CALAMITY": ("CALAMITY_AGENT_TOKEN", "change-me-calamity-agent-token"),
    "NETWORK": ("NETWORK_AGENT_TOKEN", DEFAULT_NETWORK_TOKEN),
}


def agent_token(role: str) -> str:
    env, default = AGENT_TOKEN_DEFAULTS[role]
    return os.environ.get(env) or default


def is_agent(role: str, presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(presented, agent_token(role))


def agent_role(presented: str | None) -> str | None:
    """Which agent presented this X-Agent-Token (None if none or unknown)."""
    return next((r for r in AGENT_TOKEN_DEFAULTS if is_agent(r, presented)), None)


def require_agent(*roles: str):
    def dep(x_agent_token: str | None = Header(default=None)) -> str:
        role = agent_role(x_agent_token)
        if role not in roles:
            raise HTTPException(status_code=401, detail=f"Missing or invalid X-Agent-Token ({'/'.join(roles)} agent)")
        return role
    return dep

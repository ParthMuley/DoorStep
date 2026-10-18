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


def require_org_agent(org_id: str, x_org_agent: str | None = Header(default=None)) -> str:
    """Org-scoped routes: the caller must identify as the org in the path (contract v2.0 §1)."""
    if not x_org_agent or not hmac.compare_digest(x_org_agent, org_id):
        raise HTTPException(status_code=403, detail="X-Org-Agent must match the organization in the path")
    return org_id

"""Demo authorization: a shared token in the X-Demo-Token header.

Default token works only for local simulation. Set DOORSTEP_DEMO_TOKEN in
.env for anything shared. This is demo gating, not production auth.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException

DEFAULT_DEMO_TOKEN = "doorstep-local-demo-token"


def expected_token() -> str:
    return os.environ.get("DOORSTEP_DEMO_TOKEN", DEFAULT_DEMO_TOKEN)


def require_demo_token(x_demo_token: str | None = Header(default=None)) -> None:
    if not x_demo_token or not hmac.compare_digest(x_demo_token, expected_token()):
        raise HTTPException(status_code=401, detail={"code": "demo_auth_required",
                                                     "message": "Missing or invalid X-Demo-Token"})

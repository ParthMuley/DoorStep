"""DEV ONLY - run B's backend plus A's contract-v2 test-double routes on :8000, so the
V2 agents can be exercised live (ASI:One / Agentverse) before B's v2 routes land.
In-memory Mongo (mongomock); restart = reset. Delete when B ships contract v2.0.

Usage (repo root):  .venv/Scripts/python scripts/dev_backend_v2.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ.setdefault("SIMULATION_MODE", "true")

import uvicorn  # noqa: E402

from doorstep.agents.base import DEMO_ORGS, org_address  # noqa: E402
from tests.integration.fake_v2_backend import build_v2_app  # noqa: E402

if __name__ == "__main__":
    addresses = {org: org_address(org) for org in DEMO_ORGS}
    app, _ = build_v2_app(addresses)
    print("DEV backend (B's app + v2 test double) - SIMULATION ONLY")
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("DOORSTEP_API_PORT", "8000")))

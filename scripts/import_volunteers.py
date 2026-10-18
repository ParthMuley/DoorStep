"""DOORSTEP DEMO - an organization bulk-imports its volunteer roster (synthetic people only)
and gets one invite code per volunteer to hand out (`LINK <code>` in ASI:One).

Usage (repo root, backend running):
  .venv/Scripts/python scripts/import_volunteers.py scripts/rosters/eastside_rides_demo.csv \
      --org eastside_rides_demo --region la_county:east_valley
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from doorstep.workflows.roster_import import import_roster  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--org", required=True)
    ap.add_argument("--region", required=True)
    args = ap.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    base = os.getenv("DOORSTEP_API_URL") or "http://127.0.0.1:8000"
    token = os.getenv("DEMO_AUTH_TOKEN", "change-me-local-demo-token")
    async with httpx.AsyncClient(base_url=base, timeout=20) as client:
        results = await import_roster(client, args.org, args.region, Path(args.csv).read_text(encoding="utf-8"), token)
    print(f"DOORSTEP DEMO - roster import for {args.org} in {args.region}")
    for r in results:
        print(f"  line {r.line:>2}  {r.volunteer_id:<22} {r.status:<9} {r.invite_code or '':<15} {r.detail}")
    imported = [r for r in results if r.status == "IMPORTED"]
    print(f"{len(imported)} imported, {len(results) - len(imported)} not. Hand each volunteer their code: "
          "they type LINK <code> to the Doorstep agent in ASI:One. Codes work once.")
    return 0 if imported else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

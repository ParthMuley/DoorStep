"""Calamity Checker agent - DOORSTEP DEMO.

Every ALERT_POLL_INTERVAL_SECONDS (default 120) it fetches the evacuation feed (Cal OES
shape: B's synthetic feed by default, or the live Cal OES layer, which is display-only),
posts what it got to B's `/alerts/ingest` (failed fetches too, so B can mark data
STALE/UNKNOWN), and sends an `AlertNotification` to the Doorstep agent when B reports
new/changed/canceled simulated alerts. It never interprets a status itself; B does.

Run:  python -m doorstep.agents.calamity_checker
"""

import os
from typing import Any, Awaitable, Callable

import httpx
from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import address_for, build_agent, role_port, seed_for
from doorstep.integrations.fetch_messages import AlertNotification, PollNow, utc_now
from doorstep.integrations.fetch_adapter import new_correlation_id
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()

MAX_BACKOFF_TICKS = 8
FeedFetcher = Callable[[str], Awaitable[tuple[bool, int | None, dict[str, Any] | None, str | None]]]


def feed_url() -> str:
    explicit = os.getenv("ALERT_FEED_URL", "").strip()
    return explicit or f"{os.getenv('DOORSTEP_API_URL', 'http://127.0.0.1:8000').rstrip('/')}/demo/feeds/caloes"


def source_for(url: str) -> dict[str, str]:
    """Honest provenance: only B's synthetic feed may trigger check-ins (B enforces it too)."""
    synthetic = "/demo/feeds/caloes" in url
    return {"source_id": "SYNTHETIC_CALOES" if synthetic else "CALOES_LIVE",
            "source_type": "OFFICIAL_SIMULATION" if synthetic else "REAL_WORLD", "url": url}


async def http_fetch(url: str) -> tuple[bool, int | None, dict[str, Any] | None, str | None]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return False, resp.status_code, None, f"HTTP {resp.status_code}"
        return True, 200, resp.json(), None
    except (httpx.HTTPError, ValueError) as err:
        return False, None, None, type(err).__name__


class CalamityChecker:
    def __init__(self, get_backend: Callable[[], DoorstepBackendV2], fetch: FeedFetcher = http_fetch,
                 coordinator_address: Callable[[], str] = lambda: address_for("COORDINATOR")):
        self.get_backend, self.fetch, self.coordinator_address = get_backend, fetch, coordinator_address
        self.failures = 0
        self.skip_ticks = 0

    async def poll_once(self, ctx: Context, correlation_id: str | None = None) -> dict[str, Any] | None:
        corr = correlation_id or new_correlation_id()
        url = feed_url()
        fetched_at = utc_now()
        ok, status, payload, error = await self.fetch(url)
        source = {**source_for(url), "fetched_at": fetched_at}
        try:
            result = await self.get_backend().ingest_alerts(source, ok, status, error, payload,
                                                            f"{source['source_id']}:{fetched_at}", corr)
        except (BackendError, OSError) as err:
            self._failed(ctx, corr, f"ingest {type(err).__name__}")
            return None
        if not ok:
            self._failed(ctx, corr, f"feed {error}")
        else:
            self.failures, self.skip_ticks = 0, 0
        changed = result.get("new_alerts") or result.get("changed_alerts") or result.get("canceled_alerts")
        ctx.logger.info(f"[{corr}] ingest {result.get('ingest_id')}: freshness {result.get('feed_freshness')}, "
                        f"new {len(result.get('new_alerts', []))}")
        if result.get("notify_coordinator") and changed:
            await ctx.send(self.coordinator_address(), AlertNotification(
                correlation_id=corr, created_at=utc_now(), ingest_id=result["ingest_id"],
                feed_freshness=result.get("feed_freshness", "UNKNOWN"),
                new_alerts=result.get("new_alerts", []), changed_alerts=result.get("changed_alerts", []),
                canceled_alerts=result.get("canceled_alerts", []), affected_cases=result.get("affected_cases", []),
                outreach_orgs=result.get("outreach_orgs", [])))
        return result

    def _failed(self, ctx: Context, corr: str, why: str) -> None:
        self.failures += 1
        self.skip_ticks = min(2 ** (self.failures - 1), MAX_BACKOFF_TICKS) - 1
        ctx.logger.warning(f"[{corr}] poll failed ({why}); backing off {self.skip_ticks} tick(s)")

    async def tick(self, ctx: Context) -> None:
        if self.skip_ticks > 0:
            self.skip_ticks -= 1
            return
        await self.poll_once(ctx)

    def protocol(self, interval_seconds: float) -> Protocol:
        proto = Protocol(name="doorstep_calamity_checker", version="2.0")

        @proto.on_interval(period=interval_seconds)
        async def scheduled(ctx: Context):
            await self.tick(ctx)

        @proto.on_message(PollNow)
        async def poll_now(ctx: Context, sender: str, msg: PollNow):
            await self.poll_once(ctx, msg.correlation_id)

        return proto


def main() -> None:
    agent = build_agent("doorstep_calamity_checker", seed_for("CALAMITY_SEED"), role_port("CALAMITY"),
                        "calamity_checker.md",
                        "DOORSTEP DEMO: polls a Cal OES-shaped evacuation feed every 2 minutes and reports "
                        "simulated official alerts to the Doorstep coordinator.")
    checker = CalamityChecker(lambda: DoorstepBackendV2())
    agent.include(checker.protocol(float(os.getenv("ALERT_POLL_INTERVAL_SECONDS", "120"))), publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

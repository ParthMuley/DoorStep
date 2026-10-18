"""News / Road-closure agent - DOORSTEP DEMO.

Every NEWS_POLL_INTERVAL_SECONDS (default 120) it reads two synthetic feeds from B:
  * the (simulated) **official** closure feed -> posted with source_type OFFICIAL_SIMULATION;
  * synthetic **news** articles -> ASI:One extracts the *claim* each makes about a road
    (keyword fallback), posted with source_type NEWS.
B's deterministic rules set every record's state (OFFICIAL_CONFIRMED / UNVERIFIED_REPORT /
CONFLICTING / EXPIRED); only official closures can block routes. This agent never labels
anything official, never decides a report is true, and never treats "no reports" as open.
New records are sent to the Doorstep agent as a `ClosureNotification`.

Run:  python -m doorstep.agents.news
"""

import os
from typing import Any, Callable

from dotenv import load_dotenv
from uagents import Context, Protocol

from doorstep.agents.base import address_for, build_agent, role_port, seed_for
from doorstep.integrations.closure_extraction import ClosureExtractor
from doorstep.integrations.fetch_adapter import new_correlation_id
from doorstep.integrations.fetch_messages import ClosureNotification, PollNow, utc_now
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

load_dotenv()


class NewsAgent:
    def __init__(self, get_backend: Callable[[], DoorstepBackendV2], extractor: ClosureExtractor | None = None,
                 coordinator_address: Callable[[], str] = lambda: address_for("COORDINATOR")):
        self.get_backend, self.coordinator_address = get_backend, coordinator_address
        self.extractor = extractor or ClosureExtractor()
        self.seen: set[str] = set()  # item IDs already posted (B dedupes too)

    async def poll_once(self, ctx: Context, correlation_id: str | None = None,
                        notify_always: bool = False) -> list[dict[str, Any]]:
        """`notify_always` (on-demand polls): tell Doorstep even when nothing is new, so the
        person who asked always gets the current road conditions."""
        corr = correlation_id or new_correlation_id()
        backend, fetched_at, accepted = self.get_backend(), utc_now(), []
        try:
            official = await backend.official_closures_feed(corr)
            items = [{"source_item_id": c["closure_id"], "published_at": c.get("published_at"),
                      "headline": f"{c.get('issuing_authority', 'SIMULATED authority')}: {c['road_name']} {c['status']}",
                      "raw_text": None, "extraction_method": "STRUCTURED_FEED",
                      "candidate": {"road_name": c["road_name"], "claimed_status": c["status"], "location_text": ""}}
                     for c in official.get("closures", []) if c["closure_id"] not in self.seen]
            if items:
                res = await backend.ingest_closures(
                    {"source_id": "SYNTHETIC_OFFICIAL_CLOSURES", "source_type": "OFFICIAL_SIMULATION",
                     "url": "/demo/feeds/closures", "fetched_at": fetched_at}, items,
                    f"SYNTHETIC_OFFICIAL_CLOSURES:{fetched_at}", corr)
                accepted += res.get("accepted", [])
                self.seen.update(i["source_item_id"] for i in items)

            news = await backend.news_feed(corr)
            items = []
            for n in news.get("items", []):
                if n["item_id"] in self.seen:
                    continue
                text = f"{n.get('headline', '')}\n{n.get('body', '')}"
                candidate, method = await self.extractor.extract(text)
                self.seen.add(n["item_id"])
                if candidate is None:
                    continue  # no road claim in this article
                items.append({"source_item_id": n["item_id"], "published_at": n.get("published_at"),
                              "headline": n.get("headline"), "raw_text": text, "extraction_method": method,
                              "candidate": candidate})
            if items:
                res = await backend.ingest_closures(
                    {"source_id": "SYNTHETIC_NEWS", "source_type": "NEWS", "url": "/demo/feeds/news",
                     "fetched_at": fetched_at}, items, f"SYNTHETIC_NEWS:{fetched_at}", corr)
                accepted += res.get("accepted", [])
        except (BackendError, OSError) as err:
            ctx.logger.warning(f"[{corr}] news poll failed: {getattr(err, 'code', type(err).__name__)}")
            return []
        ctx.logger.info(f"[{corr}] closures ingested: {[(a.get('road_name'), a.get('state')) for a in accepted]}")
        if accepted or notify_always:
            await ctx.send(self.coordinator_address(), ClosureNotification(
                correlation_id=corr, created_at=utc_now(), new_records=accepted))
        return accepted

    def protocol(self, interval_seconds: float) -> Protocol:
        proto = Protocol(name="doorstep_news", version="2.1")

        ticks = {"n": 0}

        @proto.on_interval(period=interval_seconds)
        async def scheduled(ctx: Context):
            ticks["n"] += 1
            if ticks["n"] == 1:  # uagents fires interval handlers at startup; first poll is on demand
                return
            await self.poll_once(ctx)

        @proto.on_message(PollNow)
        async def poll_now(ctx: Context, sender: str, msg: PollNow):
            await self.poll_once(ctx, msg.correlation_id, notify_always=True)

        return proto


def main() -> None:
    agent = build_agent("doorstep_news", seed_for("NEWS_SEED"), role_port("NEWS"), "news.md", "news",
                        "DOORSTEP DEMO: gathers simulated official road closures and news reports; reports are "
                        "labeled unverified, and no report never means a road is open.")
    agent.include(NewsAgent(lambda: DoorstepBackendV2()).protocol(float(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "120"))),
                  publish_manifest=True)
    agent.run()


if __name__ == "__main__":
    main()

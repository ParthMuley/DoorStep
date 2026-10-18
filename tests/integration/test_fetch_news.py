"""News / Road-closure agent: extraction never decides truth; B's rules set the state;
only official closures can block routes; reports are unverified; no report != open."""

import asyncio
from types import SimpleNamespace

from uagents import Context

from doorstep.agents.news import NewsAgent
from doorstep.integrations.closure_extraction import ClosureExtractor, keyword_candidate
from doorstep.integrations.fetch_messages import ClosureNotification, PollNow, utc_now
from tests.integration.conftest import make_agent, run_until
from tests.integration.fake_v2_backend import make_v2_backend


def tool_reply(arguments: str | None = None, error: Exception | None = None):
    async def create(**kwargs):
        if error:
            raise error
        call = SimpleNamespace(function=SimpleNamespace(name="report_road_claim", arguments=arguments))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def keyword_backed_model():
    """Offline stand-in for ASI:One extraction: answers from the article text deterministically."""
    import json as _json

    async def create(**kwargs):
        text = kwargs["messages"][-1]["content"]
        cand = keyword_candidate(text)
        args = ({"mentions_road": True, **cand} if cand else
                {"mentions_road": False, "road_name": "", "claimed_status": "UNKNOWN", "location_text": ""})
        call = SimpleNamespace(function=SimpleNamespace(name="report_road_claim", arguments=_json.dumps(args)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_keyword_candidate():
    assert keyword_candidate("Residents report Canyon Rd blocked by debris") == {
        "road_name": "Canyon Rd", "claimed_status": "CLOSED", "location_text": ""}
    assert keyword_candidate("Crews reopened Ridge Ave late Tuesday")["claimed_status"] == "OPEN"
    assert keyword_candidate("Library bake sale raises funds") is None


async def test_llm_extraction_and_fallbacks():
    ok = ClosureExtractor(client=tool_reply('{"mentions_road": true, "road_name": "Canyon Rd", '
                                            '"claimed_status": "CLOSED", "location_text": "near Zone 3"}'), model="m")
    assert await ok.extract("x") == ({"road_name": "Canyon Rd", "claimed_status": "CLOSED",
                                      "location_text": "near Zone 3"}, "ASI_ONE_EXTRACTION")
    none = ClosureExtractor(client=tool_reply('{"mentions_road": false, "road_name": "", '
                                              '"claimed_status": "UNKNOWN", "location_text": ""}'), model="m")
    assert (await none.extract("bake sale"))[0] is None
    bad = ClosureExtractor(client=tool_reply('{"mentions_road": true, "road_name": "X Rd", '
                                             '"claimed_status": "SAFE", "location_text": ""}'), model="m")  # not in enum
    assert (await bad.extract("x"))[0] is None  # status outside the enum is never accepted
    down = ClosureExtractor(client=tool_reply(error=ConnectionError("down")), model="m")
    assert await down.extract("Canyon Rd blocked by debris") == (
        {"road_name": "Canyon Rd", "claimed_status": "CLOSED", "location_text": ""}, "KEYWORD_EXTRACTION")


async def test_news_agent_ingests_and_notifies_with_honest_states(monkeypatch):
    backend, state = make_v2_backend(monkeypatch)
    news_agent, driver = make_agent("news"), make_agent("doorstep_driver")
    news = NewsAgent(lambda: backend, ClosureExtractor(client=keyword_backed_model(), model="m"),
                     coordinator_address=lambda: driver.address)
    news_agent.include(news.protocol(3600))
    notes: list[ClosureNotification] = []
    records: dict = {}
    done = asyncio.Event()

    @driver.on_message(ClosureNotification)
    async def on_note(ctx: Context, sender: str, msg: ClosureNotification):
        notes.append(msg)

    @driver.on_event("startup")
    async def go(ctx: Context):
        await ctx.send(news_agent.address, PollNow(correlation_id="c1", created_at=utc_now()))
        await asyncio.sleep(1.0)
        await ctx.send(news_agent.address, PollNow(correlation_id="c2", created_at=utc_now()))  # nothing new, still answers
        await asyncio.sleep(1.0)
        await backend.trigger_closure("PUBLISH_NEWS", "c3", road_name="Ridge Ave",
                                      headline="Ridge Ave reopened, residents say (DEMO)",
                                      body="Neighbors say crews reopened Ridge Ave. (DEMO)")
        await ctx.send(news_agent.address, PollNow(correlation_id="c3", created_at=utc_now()))
        await asyncio.sleep(1.0)
        records["all"] = (await backend.closures("c4"))["closures"]  # B's authoritative records
        done.set()

    await run_until([driver, news_agent], done)
    assert len(notes) == 3  # every on-demand poll answers, so the asker always gets current conditions
    assert notes[0].new_records and notes[1].new_records == []  # nothing new is reported as nothing new
    by_road: dict[str, list] = {}
    for c in records["all"]:
        by_road.setdefault(c["road_name"], []).append(c)
    ridge_official = [c for c in by_road["Ridge Ave"] if c["sources"][0]["source_type"] == "OFFICIAL_SIMULATION"]
    assert ridge_official and ridge_official[0]["state"] == "OFFICIAL_CONFIRMED" and ridge_official[0]["used_for_routing"]
    canyon = by_road["Canyon Rd"][0]
    assert canyon["state"] == "UNVERIFIED_REPORT" and not canyon["used_for_routing"]
    assert canyon["sources"][0]["extraction_method"] == "ASI_ONE_EXTRACTION"
    # The "Ridge Ave reopened" news report contradicts the official closure: never official, never routing.
    assert notes[2].new_records
    assert all(c["state"] != "OFFICIAL_CONFIRMED" for recs in by_road.values() for c in recs
               if c["sources"][0]["source_type"] == "NEWS")
    assert any(c["state"] == "CONFLICTING" or c.get("conflicting_reports") for c in by_road["Ridge Ave"])

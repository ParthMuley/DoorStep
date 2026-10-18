"""ASI:One tool-calling intent: the model only picks an allowed tool; everything else
falls back to deterministic keywords, and replies always come from the actions."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from uagents import Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from doorstep.agents import coordinator
from doorstep.agents import coordinator_actions as actions
from doorstep.integrations.asi_one_client import IntentClient, keyword_intent, validate_intent
from tests.integration.backend_fixtures import make_backend
from tests.integration.conftest import make_agent, run_until


def tool_call(name: str, arguments: str):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


class FakeModel:
    """Stands in for AsyncOpenAI: returns preset tool calls or raises."""

    def __init__(self, calls=None, error: Exception | None = None, content: str | None = None):
        self.calls, self.error, self.content = calls, error, content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        message = SimpleNamespace(tool_calls=self.calls, content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_validate_intent_allow_list():
    assert validate_intent("case_status", '{"resident": "maria"}').args == {"resident": "maria"}
    assert validate_intent("start_readiness_check", "{}").name == "start_readiness_check"
    assert validate_intent("dispatch_volunteer", "{}") is None          # unknown tool
    assert validate_intent("case_status", '{"resident": "zoe"}') is None  # not in enum
    assert validate_intent("case_status", "{}") is None                   # missing required
    assert validate_intent("case_status", '{"resident": "maria", "status": "SAFE"}') is None  # extra arg
    assert validate_intent("case_status", "not json") is None


async def test_client_returns_validated_tool_choice():
    fake = FakeModel(calls=[tool_call("case_status", '{"resident": "david"}')])
    intent = await IntentClient(client=fake, model="asi1-mini").choose("how is david?")
    assert (intent.name, intent.args, intent.source) == ("case_status", {"resident": "david"}, "ASI_ONE")
    request = fake.requests[0]
    assert request["model"] == "asi1-mini" and request["temperature"] == 0
    assert {t["function"]["name"] for t in request["tools"]} >= {"case_status", "start_readiness_check"}


@pytest.mark.parametrize("fake", [
    FakeModel(error=TimeoutError("slow")),
    FakeModel(calls=None, content="Maria is safe!"),  # prose instead of a tool: ignored
    FakeModel(calls=[tool_call("case_status", '{"resident":"maria"}'), tool_call("help", "{}")]),
    FakeModel(calls=[tool_call("mark_safe", '{"resident":"maria"}')]),
])
async def test_client_falls_back_to_none(fake):
    assert await IntentClient(client=fake, model="asi1-mini").choose("anything") is None


def test_keyword_fallback():
    assert keyword_intent("Status for David").args == {"resident": "david"}
    assert keyword_intent("Show available suitable providers").name == "find_match"
    assert keyword_intent("approve the arrangement for David").args == {"resident": "david"}
    assert keyword_intent("Start the simulated Zone 3 readiness check").name == "start_readiness_check"
    assert keyword_intent("what's the weather").name == "help"


async def ask(text: str) -> ChatMessage:
    agent = make_agent("coordinator")
    agent.include(coordinator.chat_proto)
    tester = make_agent("asi_one_user")
    replies: list[ChatMessage] = []
    done = asyncio.Event()

    @tester.on_event("startup")
    async def send(ctx: Context):
        await ctx.send(agent.address, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                                  content=[TextContent(type="text", text=text)]))

    @tester.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        replies.append(msg)
        done.set()

    await run_until([agent, tester], done)
    return replies[0]


@pytest.fixture
async def backend(monkeypatch):
    b = make_backend(monkeypatch)
    monkeypatch.setattr(actions, "get_backend", lambda: b)
    await b.start_demo_warning("zone_3", "la_hacks_demo_v1", "corr_setup")
    return b


async def test_llm_picked_tool_runs_action_and_reply_comes_from_backend(monkeypatch, backend):
    fake = FakeModel(calls=[tool_call("case_status", '{"resident": "maria"}')], content="IGNORED MODEL TEXT")
    monkeypatch.setattr(coordinator, "get_intent_client", lambda: IntentClient(client=fake, model="asi1-mini"))
    reply = await ask("hey, how is Maria getting on these days?")
    assert reply.content[1].metadata["card_kind"] == "detail"
    assert "Maria (synthetic)" in reply.content[0].text
    assert "IGNORED MODEL TEXT" not in reply.content[0].text


async def test_llm_down_uses_keyword_fallback(monkeypatch, backend):
    fake = FakeModel(error=ConnectionError("ASI:One unreachable"))
    monkeypatch.setattr(coordinator, "get_intent_client", lambda: IntentClient(client=fake, model="asi1-mini"))
    reply = await ask("Status for Maria")
    assert reply.content[1].metadata["card_kind"] == "detail"
    assert len(fake.requests) == 1


async def test_model_may_not_guess_the_resident(monkeypatch, backend):
    fake = FakeModel(calls=[tool_call("case_status", '{"resident": "maria"}')])
    monkeypatch.setattr(coordinator, "get_intent_client", lambda: IntentClient(client=fake, model="asi1-mini"))
    reply = await ask("how is the lady with the wheelchair doing?")
    assert "Which resident do you mean?" in reply.content[0].text
    assert len(reply.content) == 1  # no case card shown for a guessed person

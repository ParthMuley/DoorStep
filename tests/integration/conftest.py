"""Offline helpers for in-process agent tests: one Bureau, local dispatch only, no
network at all (no Almanac/Agentverse registration, status updates or telemetry), so
the tests are fast and behave the same on every machine and network."""

import asyncio
import os
from itertools import count
from uuid import uuid4

os.environ.setdefault("COORDINATOR_SEED", "doorstep-test-coordinator-seed")

import pytest  # noqa: E402
from uagents import Agent, Bureau  # noqa: E402
from uagents_core.registration import BatchRegistrationPolicy  # noqa: E402

_ports = count(8210)


class NoRegistration(BatchRegistrationPolicy):
    async def register(self):
        return None

    def add_agent(self, agent_info, identity):
        return None


@pytest.fixture(autouse=True)
def offline_agents(monkeypatch):
    """Agent startup always reports its status to the Almanac API before startup handlers
    run (uagents 0.26 `run_startup_tasks`); on a slow or blocked network that alone can
    exceed a test timeout. Stub it out for every test."""

    async def no_status_update(self, active: bool):
        return None

    monkeypatch.setattr(Agent, "_update_agent_status", no_status_update)
    # .env may enable the real ASI:One API; tests inject fake models explicitly instead.
    monkeypatch.setenv("USE_LLM_INTENT", "false")
    monkeypatch.setenv("USE_LLM_EXTRACTION", "false")
    # Rev 4 linking is tested explicitly (test_rev4_linking.py); other tests use open demo mode.
    monkeypatch.setenv("REQUIRE_LINK", "false")
    # One-message-per-part (legacy) unless a test turns coalescing on (test_outbox.py).
    monkeypatch.setenv("PUSH_COALESCE_SECONDS", "0")
    # .env may hold the real (Render) tokens and B's create_app() calls load_dotenv(), which
    # never overrides a variable that is already set: pin the placeholders so both sides match.
    for name, value in (("DEMO_AUTH_TOKEN", "change-me-local-demo-token"),
                        ("NETWORK_AGENT_TOKEN", "change-me-network-agent-token"),
                        ("DOORSTEP_AGENT_TOKEN", "change-me-doorstep-agent-token"),
                        ("ROUTE_AGENT_TOKEN", "change-me-route-agent-token"),
                        ("CALAMITY_AGENT_TOKEN", "change-me-calamity-agent-token")):
        monkeypatch.setenv(name, value)
    for name in ("PUBLIC_BASE_URL", "DOORSTEP_API_URL"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("ROUTE_MAP_IMAGES", "false")  # map rendering is tested on its own (test_route.py)
    monkeypatch.setenv("DRIVE_TIME_RANKING", "false")  # tested on its own (test_drive_time.py)
    monkeypatch.setenv("DEMO_LINK_PER_CHAT", "false")  # demo-only switch; tested on its own (test_outbox.py)


def make_agent(name: str) -> Agent:
    return Agent(name=name, seed=f"doorstep-test-{name}-{uuid4()}",
                 mark_inactive_on_shutdown=False, report_events=False)


async def run_until(agents: list[Agent], done: asyncio.Event, timeout: float = 30) -> None:
    bureau = Bureau(port=next(_ports), registration_policy=NoRegistration())
    for agent in agents:
        bureau.add(agent)
    task = asyncio.create_task(bureau.run_async())
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    finally:
        # Don't await the cancelled Bureau: its shutdown cancels every task on the loop,
        # including the test itself.
        task.cancel()

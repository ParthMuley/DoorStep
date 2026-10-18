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
        task.cancel()

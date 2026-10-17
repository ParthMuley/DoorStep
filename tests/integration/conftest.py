"""Offline helpers for in-process agent tests: one Bureau, local dispatch only, no
Almanac/Agentverse registration (keeps tests fast and independent of the network)."""

import asyncio
import os
from itertools import count
from uuid import uuid4

os.environ.setdefault("COORDINATOR_SEED", "doorstep-test-coordinator-seed")

from uagents import Agent, Bureau  # noqa: E402
from uagents_core.registration import BatchRegistrationPolicy  # noqa: E402

_ports = count(8210)


class NoRegistration(BatchRegistrationPolicy):
    async def register(self):
        return None

    def add_agent(self, agent_info, identity):
        return None


def make_agent(name: str) -> Agent:
    return Agent(name=name, seed=f"doorstep-test-{name}-{uuid4()}", mark_inactive_on_shutdown=False)


async def run_until(agents: list[Agent], done: asyncio.Event, timeout: float = 30) -> None:
    bureau = Bureau(port=next(_ports), registration_policy=NoRegistration())
    for agent in agents:
        bureau.add(agent)
    task = asyncio.create_task(bureau.run_async())
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    finally:
        task.cancel()

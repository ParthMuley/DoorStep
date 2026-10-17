"""Shared behaviour for independent provider agents (Transport, Destination).

Each provider agent owns its own synthetic inventory file and never reads the
coordinator's or Developer B's database. Providers report raw capability and
capacity; eligibility is decided by deterministic matching in B's backend. A provider
only decides whether it accepts a proposed assignment.
"""

import json
import os
from pathlib import Path
from typing import Any

from uagents import Agent, Context, Protocol

from doorstep.integrations.agentverse_setup import agentverse_api_key, enable_auto_mailbox
from doorstep.integrations.fetch_adapter import (
    AcceptRequest,
    AcceptResponse,
    OfferRequest,
    OfferResponse,
    ServiceType,
    utc_now,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_inventory(filename: str, key: str) -> list[dict[str, Any]]:
    with open(FIXTURES / filename, encoding="utf-8") as f:
        return json.load(f)[key]


def declined_providers() -> set[str]:
    """Test/demo hook: provider ids that will decline, e.g. DECLINE_PROVIDERS=transport_org_a."""
    return {p.strip() for p in os.getenv("DECLINE_PROVIDERS", "").split(",") if p.strip()}


def build_provider_protocol(role: ServiceType, inventory: list[dict[str, Any]]) -> Protocol:
    proto = Protocol(name=f"doorstep_{role}", version="1.0")
    by_provider = {item["provider_id"]: item for item in inventory}
    decisions: dict[str, AcceptResponse] = {}

    @proto.on_message(OfferRequest, replies=OfferResponse)
    async def handle_offer_request(ctx: Context, sender: str, msg: OfferRequest):
        if msg.service_type != role:
            offers, note = [], f"This agent only serves {role} requests."
        else:
            offers = [
                {**item, "offer_id": f"offer_{msg.request_id}_{item['provider_id']}", "valid_for_minutes": 30}
                for item in inventory
            ]
            note = "Raw synthetic capacity; eligibility is decided by the coordinator's deterministic matching."
        ctx.logger.info(f"[{msg.correlation_id}] offer request {msg.request_id}: {len(offers)} offers")
        await ctx.send(
            sender,
            OfferResponse(
                case_id=msg.case_id,
                request_id=msg.request_id,
                correlation_id=msg.correlation_id,
                agent_role=role,
                offers=offers,
                note=note,
                created_at=utc_now(),
            ),
        )

    @proto.on_message(AcceptRequest, replies=AcceptResponse)
    async def handle_accept_request(ctx: Context, sender: str, msg: AcceptRequest):
        # Idempotent: a repeated or delayed request gets the original decision back.
        previous = decisions.get(msg.idempotency_key)
        if previous is None:
            item = by_provider.get(msg.provider_id)
            if item is None:
                decision, reason = "DECLINED", "UNKNOWN_PROVIDER"
            elif not item["accepts_requests"] or msg.provider_id in declined_providers():
                decision, reason = "DECLINED", "PROVIDER_DECLINED"
            else:
                decision, reason = "ACCEPTED", "SIMULATED_PROVIDER_ACCEPTED"
            previous = AcceptResponse(
                case_id=msg.case_id,
                assignment_id=msg.assignment_id,
                offer_id=msg.offer_id,
                provider_id=msg.provider_id,
                correlation_id=msg.correlation_id,
                idempotency_key=msg.idempotency_key,
                decision=decision,
                reason=reason,
                created_at=utc_now(),
            )
            decisions[msg.idempotency_key] = previous
        ctx.logger.info(f"[{msg.correlation_id}] {msg.provider_id} -> {previous.decision}")
        await ctx.send(sender, previous)

    return proto


def build_provider_agent(
    name: str, seed_env: str, port_env: str, default_port: int, profile: str, description: str
) -> Agent:
    seed = os.getenv(seed_env, "").strip()
    if not seed:
        raise SystemExit(f"{seed_env} is not set. Copy .env.example to .env and fill it in.")
    port = int(os.getenv(port_env, str(default_port)))
    # With AGENTVERSE_API_KEY set, providers get an Agentverse mailbox + profile page
    # automatically. PROVIDER_USE_MAILBOX=false forces a local-only endpoint for fast dev.
    default_mailbox = "true" if agentverse_api_key() else "false"
    if os.getenv("PROVIDER_USE_MAILBOX", default_mailbox).lower() == "true":
        agent = Agent(
            name=name, seed=seed, port=port, mailbox=True, publish_agent_details=True,
            readme_path=str(Path(__file__).parent / "profiles" / profile), description=description,
        )
        enable_auto_mailbox(agent, port)
        return agent
    return Agent(name=name, seed=seed, port=port, endpoint=[f"http://127.0.0.1:{port}/submit"])

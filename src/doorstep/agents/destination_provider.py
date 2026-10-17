"""Destination Provider agent - DOORSTEP DEMO, fictional destinations only.

Run:  python -m doorstep.agents.destination_provider
"""

from dotenv import load_dotenv

from doorstep.agents.provider_base import build_provider_agent, build_provider_protocol, load_inventory

load_dotenv()

inventory = load_inventory("destination_inventory.json", "destinations")
destination_proto = build_provider_protocol("accessible_destination", inventory)

if __name__ == "__main__":
    agent = build_provider_agent(
        "doorstep_destination_provider", "DESTINATION_SEED", "DESTINATION_PORT", 8103,
        profile="destination_provider.md",
        description="DOORSTEP DEMO: simulated accessible temporary-destination provider with fictional sites.",
    )
    agent.include(destination_proto, publish_manifest=True)
    agent.run()

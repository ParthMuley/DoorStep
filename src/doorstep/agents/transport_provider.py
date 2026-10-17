"""Transport Provider agent - DOORSTEP DEMO, fictional vehicles only.

Run:  python -m doorstep.agents.transport_provider
"""

from dotenv import load_dotenv

from doorstep.agents.provider_base import build_provider_agent, build_provider_protocol, load_inventory

load_dotenv()

inventory = load_inventory("transport_inventory.json", "vehicles")
transport_proto = build_provider_protocol("accessible_transport", inventory)

if __name__ == "__main__":
    agent = build_provider_agent("doorstep_transport_provider", "TRANSPORT_SEED", "TRANSPORT_PORT", 8102)
    agent.include(transport_proto, publish_manifest=True)
    agent.run()

"""Partner-organization provider registry (synthetic).

Provider agents (Developer A) own their own inventories and send raw offers.
Developer B owns this registry: which providers the fictional partner
organization has PREAPPROVED, and where each one is based. Approval is never
taken from an offer's own claims and is never decided by an LLM.
"""

from __future__ import annotations

from typing import Optional

from .common import DoorstepModel, ServiceType


class ProviderRegistration(DoorstepModel):
    provider_id: str
    display_name: str
    service_type: ServiceType
    organization_id: str
    approved: bool = True  # preapproved by the fictional partner org
    # Transport: depot zone (route start). Destination: where it physically sits.
    base_zone: Optional[str] = None
    simulated: bool = True

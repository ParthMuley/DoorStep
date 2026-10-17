"""Consent gate: build the minimum, consent-scoped payload for each service.

Providers never receive the resident's name, contact channel, or full profile.
"""

from __future__ import annotations

from doorstep.models import Case, DestinationRequirements, TransportRequirements

from .errors import ConsentRequired


def transport_requirements(case: Case) -> TransportRequirements:
    if not case.consent.share_transport_needs:
        raise ConsentRequired("Resident has not consented to share transport needs",
                              reasons=["CONSENT_SHARE_TRANSPORT_NEEDS_MISSING"])
    n = case.needs
    return TransportRequirements(
        wheelchair_accessible_vehicle=n.wheelchair_accessible_vehicle,
        transfer_assistance=n.transfer_assistance,
        portable_oxygen_equipment=n.portable_oxygen_equipment,
        pet_count=n.pet_count,
        service_animal=n.service_animal,
    )


def destination_requirements(case: Case) -> DestinationRequirements:
    if not case.consent.share_destination_needs:
        raise ConsentRequired("Resident has not consented to share destination needs",
                              reasons=["CONSENT_SHARE_DESTINATION_NEEDS_MISSING"])
    n = case.needs
    access = set(n.destination_accessibility)
    return DestinationRequirements(
        step_free_entry="step_free_entry" in access or n.wheelchair_accessible_vehicle,
        accessible_restroom="accessible_restroom" in access,
        pets_allowed=n.pet_count > 0,
        service_animal=n.service_animal,
        oxygen_friendly=n.portable_oxygen_equipment,
        capacity_needed=1,
    )


def recovery_payload(case: Case) -> dict:
    """Only the fields a recovery provider needs to find accessible lodging."""
    if not case.consent.share_recovery_needs:
        raise ConsentRequired("Resident has not consented to share recovery needs",
                              reasons=["CONSENT_SHARE_RECOVERY_NEEDS_MISSING"])
    n = case.needs
    return {
        "preferred_language": n.preferred_language,
        "wheelchair_accessible_vehicle": n.wheelchair_accessible_vehicle,
        "destination_accessibility": list(n.destination_accessibility),
        "pet_count": n.pet_count,
        "service_animal": n.service_animal,
    }

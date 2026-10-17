"""Deterministic synthetic seed data. EVERYTHING HERE IS FICTIONAL (DEMO).

Matches docs/interface-contract.md section 5. Names are labels for fictional
people; senders are simulator ids; pickup points and zones do not exist.
No real addresses, diagnoses, or identifiers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from doorstep.models import (
    Caregiver,
    Consent,
    Needs,
    Organization,
    ProviderRegistration,
    Resident,
)

# Deterministic case ids per resident (so reset_demo.sh reproduces state).
CASE_IDS = {
    "resident_001": "case_maria_001",
    "resident_002": "case_david_002",
}

DEMO_ZONE = "zone_3"
SCENARIO_ID = "la_hacks_demo_v1"
MARIA_SENDER = "sim_phone_maria"
DAVID_SENDER = "sim_phone_david"
DAVID_CAREGIVER_SENDER = "sim_phone_david_caregiver"


def organizations() -> list[Organization]:
    return [
        Organization(organization_id="org_community_demo", display_name="Fictional Neighborhood Access Network (DEMO)", role="community_support"),
        Organization(organization_id="org_transport_demo", display_name="Fictional Accessible Transit Partners (DEMO)", role="transport"),
        Organization(organization_id="org_destination_demo", display_name="Fictional Community Centers (DEMO)", role="destination"),
        Organization(organization_id="org_recovery_demo", display_name="Fictional Recovery Support Org (DEMO)", role="recovery"),
    ]


def residents() -> list[Resident]:
    consent = Consent(contact_for_checkins=True, share_transport_needs=True,
                      share_destination_needs=True, share_recovery_needs=False)
    maria = Resident(
        resident_id="resident_001",
        zone_id="zone_3",
        sector_id="zone_3_sector_b",
        display_name="Maria (synthetic)",
        preferred_language="es",
        contact_channel=MARIA_SENDER,
        needs=Needs(wheelchair_accessible_vehicle=True, transfer_assistance=True, pet_count=1,
                    preferred_language="es", destination_accessibility=["step_free_entry"]),
        consent=consent,
        pickup_point="SYNTHETIC: Zone 3 Sector B meeting point 4",
        last_confirmed_at="2026-10-01T17:00:00Z",
    )
    david = Resident(
        resident_id="resident_002",
        zone_id="zone_3",
        sector_id="zone_3_sector_a",
        display_name="David (synthetic)",
        preferred_language="en",
        contact_channel=DAVID_SENDER,
        needs=Needs(wheelchair_accessible_vehicle=True, preferred_language="en",
                    destination_accessibility=["step_free_entry"]),
        consent=consent,
        caregiver=Caregiver(caregiver_id="caregiver_002", display_name="Ana (synthetic caregiver)",
                            contact_channel=DAVID_CAREGIVER_SENDER),
        pickup_point="SYNTHETIC: Zone 3 Sector A meeting point 1",
        last_confirmed_at="2026-10-01T17:00:00Z",
    )
    return [maria, david]


def provider_registry() -> list[ProviderRegistration]:
    """Which providers the fictional partner org has PREAPPROVED, and where they are based."""
    t, d = "accessible_transport", "accessible_destination"
    return [
        ProviderRegistration(provider_id="transport_org_a", display_name="Eastside Accessible Rides (DEMO)",
                             service_type=t, organization_id="org_transport_demo", base_zone="zone_2"),
        ProviderRegistration(provider_id="transport_org_b", display_name="Neighbor Volunteer Sedan (DEMO)",
                             service_type=t, organization_id="org_transport_demo", base_zone="zone_3_sector_b"),
        ProviderRegistration(provider_id="transport_org_c", display_name="Unlisted Van Service (DEMO)",
                             service_type=t, organization_id="org_transport_demo", approved=False, base_zone="zone_2"),
        ProviderRegistration(provider_id="transport_org_d", display_name="Lift Van, No Pets (DEMO)",
                             service_type=t, organization_id="org_transport_demo", base_zone="zone_5"),
        ProviderRegistration(provider_id="transport_org_e", display_name="Westside Paratransit Volunteers (DEMO)",
                             service_type=t, organization_id="org_transport_demo", base_zone="zone_4"),
        ProviderRegistration(provider_id="destination_org_a", display_name="Civic Center Shelter (DEMO)",
                             service_type=d, organization_id="org_destination_demo", base_zone="zone_5"),
        ProviderRegistration(provider_id="destination_org_b", display_name="Library Hall (DEMO)",
                             service_type=d, organization_id="org_destination_demo", base_zone="zone_2"),
        ProviderRegistration(provider_id="destination_org_c", display_name="Partner Hotel Rooms (DEMO)",
                             service_type=d, organization_id="org_destination_demo", base_zone="zone_2"),
    ]


def _valid_until(minutes: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def transport_offers() -> list[dict]:
    """Raw offers as Developer A's Transport agents would send them (contract 3.4).

    Used by the local scenarios and smoke test so B can run without A's agents.
    """
    vu = _valid_until()
    return [
        # Eligible match for Maria.
        {"offer_id": "offer_t_001", "provider_id": "transport_org_a", "vehicle_id": "van_a1",
         "wheelchair_accessible": True, "transfer_assistance": True, "oxygen_handling": False,
         "pets_allowed": True, "seats_available": 2, "wheelchair_spaces_available": 1,
         "service_area_zones": ["zone_2", "zone_3", "zone_4"], "eta_minutes": 18, "valid_until": vu},
        # Closer, NOT wheelchair accessible -> the "closer but unsuitable" rejection.
        {"offer_id": "offer_t_002", "provider_id": "transport_org_b", "vehicle_id": "sedan_b1",
         "wheelchair_accessible": False, "transfer_assistance": False, "oxygen_handling": False,
         "pets_allowed": True, "seats_available": 3, "wheelchair_spaces_available": 0,
         "service_area_zones": ["zone_3"], "eta_minutes": 6, "valid_until": vu},
        # Capable, but NOT approved by the partner org.
        {"offer_id": "offer_t_003", "provider_id": "transport_org_c", "vehicle_id": "van_c1",
         "wheelchair_accessible": True, "transfer_assistance": True, "oxygen_handling": False,
         "pets_allowed": True, "seats_available": 2, "wheelchair_spaces_available": 1,
         "service_area_zones": ["zone_2", "zone_3"], "eta_minutes": 12, "valid_until": vu},
        # Wheelchair + oxygen, but no pets.
        {"offer_id": "offer_t_004", "provider_id": "transport_org_d", "vehicle_id": "van_d1",
         "wheelchair_accessible": True, "transfer_assistance": True, "oxygen_handling": True,
         "pets_allowed": False, "seats_available": 2, "wheelchair_spaces_available": 1,
         "service_area_zones": ["zone_2", "zone_3", "zone_5"], "eta_minutes": 25, "valid_until": vu},
        # Eligible alternate behind a closed road (longer detour), for the decline branch.
        {"offer_id": "offer_t_005", "provider_id": "transport_org_e", "vehicle_id": "van_e1",
         "wheelchair_accessible": True, "transfer_assistance": True, "oxygen_handling": False,
         "pets_allowed": True, "seats_available": 2, "wheelchair_spaces_available": 1,
         "service_area_zones": ["zone_3", "zone_4", "zone_5"], "eta_minutes": 35, "valid_until": vu},
    ]


def destination_offers() -> list[dict]:
    vu = _valid_until()
    return [
        {"offer_id": "offer_d_001", "provider_id": "destination_org_a", "destination_id": "dest_civic_center_sim",
         "step_free_entry": True, "accessible_restroom": True, "pets_allowed": True,
         "service_animals_allowed": True, "beds_available": 12, "oxygen_power_outlets": True, "valid_until": vu},
        # Not step-free -> rejected for Maria.
        {"offer_id": "offer_d_002", "provider_id": "destination_org_b", "destination_id": "dest_library_hall_sim",
         "step_free_entry": False, "accessible_restroom": False, "pets_allowed": True,
         "service_animals_allowed": True, "beds_available": 25, "oxygen_power_outlets": False, "valid_until": vu},
        # Step-free but no pets -> rejected for Maria.
        {"offer_id": "offer_d_003", "provider_id": "destination_org_c", "destination_id": "dest_hotel_sim",
         "step_free_entry": True, "accessible_restroom": True, "pets_allowed": False,
         "service_animals_allowed": True, "beds_available": 2, "oxygen_power_outlets": False, "valid_until": vu},
    ]

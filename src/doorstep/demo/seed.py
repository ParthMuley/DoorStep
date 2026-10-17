"""Deterministic synthetic seed data. EVERYTHING HERE IS FICTIONAL (DEMO).

Names are labels for fictional people; phone numbers use the reserved 555-01xx
fictional range; pickup points and zones do not exist. No real addresses,
diagnoses, or identifiers.
"""

from __future__ import annotations

from doorstep.models import (
    Caregiver,
    Consent,
    Destination,
    Needs,
    Organization,
    Resident,
    TransportProvider,
    VehicleCapability,
)

# Deterministic case ids per resident (so reset_demo.sh reproduces state).
CASE_IDS = {
    "resident_001": "case_maria_001",
    "resident_002": "case_david_002",
}

DEMO_ZONE = "zone_3"
SCENARIO_A = "scenario_a_maria"
SCENARIO_B = "scenario_b_david"


def organizations() -> list[Organization]:
    return [
        Organization(organization_id="org_community_demo", display_name="Fictional Neighborhood Access Network (DEMO)", role="community_support"),
        Organization(organization_id="org_transport_demo", display_name="Fictional Accessible Transit Partners (DEMO)", role="transport"),
        Organization(organization_id="org_destination_demo", display_name="Fictional Community Centers (DEMO)", role="destination"),
        Organization(organization_id="org_recovery_demo", display_name="Fictional Recovery Support Org (DEMO)", role="recovery"),
    ]


def residents() -> list[Resident]:
    maria = Resident(
        resident_id="resident_001",
        zone_id="zone_3",
        display_name="Maria (DEMO resident)",
        preferred_language="es",
        contact_channel="sms:+15555550101",
        needs=Needs(
            wheelchair_accessible_vehicle=True,
            transfer_assistance=True,
            pet_count=1,
            preferred_language="es",
            destination_accessibility=["step_free_entry"],
        ),
        consent=Consent(
            contact_for_checkins=True,
            share_transport_needs=True,
            share_destination_needs=True,
            share_recovery_needs=False,
        ),
        pickup_point="DEMO pickup point Z3-A (fictional)",
        last_confirmed_at="2026-10-01T17:00:00Z",
    )
    david = Resident(
        resident_id="resident_002",
        zone_id="zone_3n",
        display_name="David (DEMO resident)",
        preferred_language="en",
        contact_channel="sms:+15555550102",
        needs=Needs(
            transfer_assistance=True,
            portable_oxygen_equipment=True,
            preferred_language="en",
            destination_accessibility=["step_free_entry"],
        ),
        consent=Consent(
            contact_for_checkins=True,
            share_transport_needs=True,
            share_destination_needs=True,
            share_recovery_needs=False,
        ),
        caregiver=Caregiver(
            caregiver_id="caregiver_002",
            display_name="Ana (DEMO caregiver)",
            contact_channel="sms:+15555550103",
        ),
        pickup_point="DEMO pickup point Z3N-B (fictional)",
        last_confirmed_at="2026-10-01T17:00:00Z",
    )
    return [maria, david]


def transport_providers() -> list[TransportProvider]:
    return [
        # The eligible match for Maria.
        TransportProvider(
            provider_id="transport_org_a",
            display_name="Eastside Accessible Rides (DEMO)",
            service_area_zones=["zone_2", "zone_3", "zone_3n", "zone_5"],
            base_zone="zone_2",
            vehicle=VehicleCapability(wheelchair_accessible=True, transfer_assistance=True,
                                      seating_capacity=2, pet_capacity=1, service_animal_ok=True),
        ),
        # Closer, but NOT wheelchair accessible -> must be rejected for Maria.
        TransportProvider(
            provider_id="transport_org_b",
            display_name="Neighbor Volunteer Sedan (DEMO)",
            service_area_zones=["zone_3", "zone_3n", "zone_4"],
            base_zone="zone_3",
            vehicle=VehicleCapability(seating_capacity=3, pet_capacity=1, service_animal_ok=True),
        ),
        # Capable vehicle but NOT approved by the partner org -> rejected.
        TransportProvider(
            provider_id="transport_org_c",
            display_name="Unlisted Van Service (DEMO)",
            approved=False,
            service_area_zones=["zone_2", "zone_3", "zone_5"],
            base_zone="zone_2",
            vehicle=VehicleCapability(wheelchair_accessible=True, transfer_assistance=True,
                                      seating_capacity=2, pet_capacity=2, service_animal_ok=True),
        ),
        # Wheelchair + oxygen capable, but no pets -> rejected for Maria's dog.
        TransportProvider(
            provider_id="transport_org_d",
            display_name="Lift Van, No Pets (DEMO)",
            service_area_zones=["zone_2", "zone_3", "zone_3n", "zone_5"],
            base_zone="zone_5",
            vehicle=VehicleCapability(wheelchair_accessible=True, transfer_assistance=True,
                                      oxygen_equipment_handling=True, seating_capacity=2,
                                      pet_capacity=0, service_animal_ok=True),
        ),
        # Eligible alternate. Its direct road is CLOSED, so the planner takes
        # a longer fictional detour (used for the provider-decline branch).
        TransportProvider(
            provider_id="transport_org_e",
            display_name="Westside Paratransit Volunteers (DEMO)",
            service_area_zones=["zone_3", "zone_4", "zone_5"],
            base_zone="zone_4",
            vehicle=VehicleCapability(wheelchair_accessible=True, transfer_assistance=True,
                                      seating_capacity=2, pet_capacity=1, service_animal_ok=True),
        ),
    ]


def destinations() -> list[Destination]:
    return [
        Destination(
            provider_id="dest_center_a",
            display_name="Zone 5 Community Center (DEMO)",
            zone_id="zone_5",
            step_free_entry=True,
            accessible_restroom=True,
            pets_allowed=True,
            oxygen_friendly=True,
            total_capacity=20,
            available_capacity=12,
        ),
        # Closer, but not step-free -> rejected for Maria.
        Destination(
            provider_id="dest_library_b",
            display_name="Zone 2 Library Hall (DEMO)",
            zone_id="zone_2",
            pets_allowed=True,
            total_capacity=30,
            available_capacity=25,
        ),
        # Step-free but no pets -> rejected for Maria.
        Destination(
            provider_id="dest_hotel_c",
            display_name="Partner Hotel Rooms (DEMO)",
            zone_id="zone_2",
            step_free_entry=True,
            accessible_restroom=True,
            pets_allowed=False,
            total_capacity=4,
            available_capacity=2,
        ),
    ]

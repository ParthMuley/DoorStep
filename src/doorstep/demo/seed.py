"""Deterministic synthetic seed data. EVERYTHING HERE IS FICTIONAL (DEMO).

Matches docs/interface-contract.md section 5. Names are labels for fictional
people; senders are simulator ids; pickup points and zones do not exist.
No real addresses, diagnoses, or identifiers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from doorstep.models import (
    Address,
    EmergencyContact,
    Location,
    Organization,
    ProviderRegistration,
    ResidentProfile,
    ShelterSite,
    Volunteer,
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

# v1 zone-graph node per seeded resident (temporary; replaced by polygon geofencing in B3).
LEGACY_SECTORS = {"resident_001": "zone_3_sector_b", "resident_002": "zone_3_sector_a"}

REGISTERED_AT = "2026-10-01T17:00:00Z"


def residents() -> list[ResidentProfile]:
    """Contract v2.0 §10. Fictional people at fictional LA-area coordinates."""
    consents = {"CHECKIN": True, "TRANSPORT": True, "DESTINATION": True, "RECOVERY": False}
    return [
        ResidentProfile(
            resident_id="resident_001", name="Maria (synthetic)", phone=MARIA_SENDER, language="es",
            address=Address(label="SYNTHETIC: Zone 3 Sector B meeting point 4", lat=34.1012, lon=-118.0964),
            emergency_contacts=[EmergencyContact(contact_id="contact_ana_001", name="Ana (synthetic)",
                                                 phone="sim_phone_ana", relationship="daughter")],
            needs=[1, 2, 4, 6], pet_count=1, wants_help_contact=True, consents=consents,
            registered_at=REGISTERED_AT,
        ),
        ResidentProfile(
            resident_id="resident_002", name="David (synthetic)", phone=DAVID_SENDER, language="en",
            address=Address(label="SYNTHETIC: Zone 3 Sector A meeting point 1", lat=34.1062, lon=-118.0951),
            emergency_contacts=[EmergencyContact(contact_id="caregiver_002", name="Ana (synthetic caregiver)",
                                                 phone=DAVID_CAREGIVER_SENDER, relationship="caregiver")],
            needs=[1], pet_count=0, wants_help_contact=True, consents=consents,
            registered_at=REGISTERED_AT,
        ),
    ]


def _vol(vid, name, phone, label, lat, lon, vehicle, seats, wc, pets, caps, approved=True) -> Volunteer:
    return Volunteer(volunteer_id=vid, name=name, phone=phone, address=Address(label=label, lat=lat, lon=lon),
                     vehicle_type=vehicle, vehicle_seats=seats, wheelchair_spaces=wc, pet_capacity=pets,
                     needs_they_can_cater=caps, approved=approved)


def organizations() -> list[Organization]:
    """Contract v2.0 §10: each org carries its own volunteers (the team's document shape)."""
    return [
        Organization(
            org_id="eastside_rides_demo", name="Eastside Accessible Rides (fictional)",
            location=Location(label="SYNTHETIC: Zone 2 depot", lat=34.0950, lon=-118.1100),
            calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=True, service_radius_km=20,
            volunteers=[_vol("volunteer_sarah", "Sarah (synthetic)", "sim_phone_sarah", "SYNTHETIC: Zone 2",
                             34.0950, -118.1100, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4, 7])],
        ),
        Organization(
            org_id="neighbor_sedans_demo", name="Neighborhood Sedan Volunteers (fictional)",
            location=Location(label="SYNTHETIC: Zone 3 Sector B", lat=34.1005, lon=-118.0970),
            calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=True, service_radius_km=10,
            # Closest to Maria, but a sedan with no wheelchair space: the "closer but unsuitable" rejection.
            volunteers=[_vol("volunteer_joe", "Joe (synthetic)", "sim_phone_joe", "SYNTHETIC: Zone 3 Sector B",
                             34.1005, -118.0970, "SEDAN", 3, 0, 1, [4, 7])],
        ),
        Organization(
            org_id="red_cross_demo", name="Red Cross (fictional demo chapter)",
            location=Location(label="SYNTHETIC: Culver City", lat=34.0210, lon=-118.3960),
            calamity_types=["WILDFIRE", "FLOOD", "EARTHQUAKE"],
            services=["TRANSPORT", "SHELTER", "RECOVERY_HOUSING", "INSURANCE_GUIDANCE"],
            approved=True, service_radius_km=40,
            volunteers=[
                _vol("volunteer_maya", "Maya (synthetic)", "sim_phone_maya", "SYNTHETIC: Zone 4",
                     34.0800, -118.1200, "MINIVAN", 4, 0, 1, [2, 4, 7, 8]),
                # Eligible alternate for Maria if Sarah declines.
                _vol("volunteer_lee", "Lee (synthetic)", "sim_phone_lee", "SYNTHETIC: Zone 5",
                     34.0700, -118.1400, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4, 5]),
            ],
            shelter_sites=[ShelterSite(site_id="rc_shelter_1", name="Red Cross Shelter (fictional)",
                                       lat=34.0300, lon=-118.3800, beds_available=30, features=[6, 4, 5])],
            recovery_services=["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"],
        ),
        Organization(
            org_id="unlisted_vans_demo", name="Unlisted Van Group (fictional)",
            location=Location(label="SYNTHETIC: Zone 2", lat=34.0980, lon=-118.1050),
            calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=False, service_radius_km=20,
            volunteers=[_vol("volunteer_tom", "Tom (synthetic)", "sim_phone_tom", "SYNTHETIC: Zone 2",
                             34.0980, -118.1050, "WHEELCHAIR_VAN", 2, 1, 2, [1, 2, 4], approved=False)],
        ),
        Organization(
            org_id="flood_only_demo", name="Flood Boats Collective (fictional)",
            location=Location(label="SYNTHETIC: Zone 4", lat=34.0900, lon=-118.1000),
            calamity_types=["FLOOD"], services=["TRANSPORT"], approved=True, service_radius_km=20,
            volunteers=[_vol("volunteer_rina", "Rina (synthetic)", "sim_phone_rina", "SYNTHETIC: Zone 4",
                             34.0900, -118.1000, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4])],
        ),
        Organization(
            org_id="civic_shelter_demo", name="Civic Center Shelter (fictional)",
            location=Location(label="SYNTHETIC: Zone 5 civic center", lat=34.0890, lon=-118.0700),
            calamity_types=["ANY"], services=["SHELTER"], approved=True, service_radius_km=30,
            shelter_sites=[ShelterSite(site_id="dest_center_a", name="Civic Center (fictional)",
                                       lat=34.0890, lon=-118.0700, beds_available=12, features=[3, 4, 5, 6])],
        ),
        Organization(
            org_id="recovery_housing_demo", name="Recovery Housing Partners (fictional)",
            location=Location(label="SYNTHETIC: Zone 6", lat=34.0600, lon=-118.0800),
            calamity_types=["ANY"], services=["RECOVERY_HOUSING"], approved=True, service_radius_km=50,
            recovery_services=["TEMPORARY_HOUSING"],
        ),
    ]


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

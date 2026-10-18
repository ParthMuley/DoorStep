"""Deterministic synthetic seed data. EVERYTHING HERE IS FICTIONAL (DEMO).

Matches docs/interface-contract.md section 5. Names are labels for fictional
people; senders are simulator ids; pickup points and zones do not exist.
No real addresses, diagnoses, or identifiers.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from doorstep.models import (
    Address,
    EmergencyContact,
    Organization,
    ProviderRegistration,
    Region,
    RegionOrg,
    ResidentProfile,
    ShelterSite,
    Volunteer,
    point,
)

# Deterministic case ids per resident (so reset_demo.sh reproduces state).
CASE_IDS = {
    "resident_001": "case_maria_001",
    "resident_002": "case_david_002",
    # "full" demo dataset only (see FULL DATASET below)
    "resident_ruth": "case_ruth_003",
    "resident_carlos": "case_carlos_004",
    "resident_kenji": "case_kenji_005",
    "resident_grace": "case_grace_006",
    "resident_harold": "case_harold_007",
    "resident_beatriz": "case_beatriz_008",
    "resident_omar": "case_omar_009",
    "resident_dolores": "case_dolores_010",
}

DEMO_ZONE = "zone_3"
SCENARIO_ID = "la_hacks_demo_v1"
MARIA_SENDER = "sim_phone_maria"
DAVID_SENDER = "sim_phone_david"
DAVID_CAREGIVER_SENDER = "sim_phone_david_caregiver"

# One-time ASI:One link codes (contract v2.2, plan rev 4 §0.1). PUBLIC: they are in the repo,
# acceptable only because every person is synthetic (plan §0.5.2). Reissued by /demo/reset.
LINK_CODES = {
    "MARIA-4821": {"role": "RESIDENT", "resident_id": "resident_001", "case_id": "case_maria_001",
                   "display_name": "Maria (synthetic)"},
    "DAVID-5932": {"role": "RESIDENT", "resident_id": "resident_002", "case_id": "case_david_002",
                   "display_name": "David (synthetic)"},
    "SARAH-7310": {"role": "VOLUNTEER", "volunteer_id": "volunteer_sarah", "org_id": "eastside_rides_demo",
                   "display_name": "Sarah (synthetic)"},
    "LEE-6624": {"role": "VOLUNTEER", "volunteer_id": "volunteer_lee", "org_id": "red_cross_demo",
                 "display_name": "Lee (synthetic)"},
    "COORD-1150": {"role": "COORDINATOR", "coordinator_id": "coordinator_demo",
                   "display_name": "Coordinator (synthetic)"},
}

# v1 zone-graph node per seeded resident (temporary; replaced by polygon geofencing in B3).
LEGACY_SECTORS = {"resident_001": "zone_3_sector_b", "resident_002": "zone_3_sector_a"}

REGISTERED_AT = "2026-10-01T17:00:00Z"


def _core_residents() -> list[ResidentProfile]:
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


def _rect(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat],
                                                [min_lon, max_lat], [min_lon, min_lat]]]}


def _vol(vid, name, phone, lat, lon, vehicle, seats, wc, pets, caps, approved=True) -> Volunteer:
    return Volunteer(volunteer_id=vid, name=name, phone=phone, location=point(lat, lon), vehicle_type=vehicle,
                     vehicle_seats=seats, wheelchair_spaces=wc, pet_capacity=pets, needs_they_can_cater=caps,
                     approved=approved)


def _core_organizations() -> list[Organization]:
    """Canonical org records (contract v2.1 §10). Volunteers live in regions()."""
    return [
        Organization(org_id="eastside_rides_demo", name="Eastside Accessible Rides (fictional)",
                     calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=True, service_radius_km=20),
        Organization(org_id="neighbor_sedans_demo", name="Neighborhood Sedan Volunteers (fictional)",
                     calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=True, service_radius_km=10),
        Organization(org_id="red_cross_demo", name="Red Cross (fictional demo chapter)",
                     calamity_types=["WILDFIRE", "FLOOD", "EARTHQUAKE"],
                     services=["TRANSPORT", "SHELTER", "RECOVERY_HOUSING", "INSURANCE_GUIDANCE"],
                     approved=True, service_radius_km=40, recovery_services=["TEMPORARY_HOUSING", "INSURANCE_GUIDANCE"]),
        Organization(org_id="unlisted_vans_demo", name="Unlisted Van Group (fictional)",
                     calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=False, service_radius_km=20),
        Organization(org_id="flood_only_demo", name="Flood Boats Collective (fictional)",
                     calamity_types=["FLOOD"], services=["TRANSPORT"], approved=True, service_radius_km=20),
        Organization(org_id="civic_shelter_demo", name="Civic Center Shelter (fictional)",
                     calamity_types=["ANY"], services=["SHELTER"], approved=True, service_radius_km=30),
        Organization(org_id="recovery_housing_demo", name="Recovery Housing Partners (fictional)",
                     calamity_types=["ANY"], services=["RECOVERY_HOUSING"], approved=True, service_radius_km=50,
                     recovery_services=["TEMPORARY_HOUSING"]),
    ]


def _core_regions() -> list[Region]:
    """Location-first partner data (plan rev 3): area -> orgs -> only their local volunteers/sites."""
    orgs = {o.org_id: o for o in _core_organizations()}

    def entry(org_id: str, volunteers=(), sites=()) -> RegionOrg:
        return RegionOrg.from_org(orgs[org_id]).model_copy(
            update={"volunteers": list(volunteers), "shelter_sites": list(sites)})

    return [
        Region(region_id="la_county:east_valley", label="East Valley (synthetic)", center=point(34.098, -118.095),
               area=_rect(-118.130, 34.075, -118.060, 34.120), orgs=[
                   entry("eastside_rides_demo", [_vol("volunteer_sarah", "Sarah (synthetic)", "sim_phone_sarah",
                                                      34.0950, -118.1100, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4, 7])]),
                   # Closest to Maria, but a sedan with no wheelchair space: the "closer but unsuitable" rejection.
                   entry("neighbor_sedans_demo", [_vol("volunteer_joe", "Joe (synthetic)", "sim_phone_joe",
                                                       34.1005, -118.0970, "SEDAN", 3, 0, 1, [4, 7])]),
                   entry("red_cross_demo", [_vol("volunteer_maya", "Maya (synthetic)", "sim_phone_maya",
                                                 34.0800, -118.1200, "MINIVAN", 4, 0, 1, [2, 4, 7, 8])]),
                   entry("unlisted_vans_demo", [_vol("volunteer_tom", "Tom (synthetic)", "sim_phone_tom",
                                                     34.0980, -118.1050, "WHEELCHAIR_VAN", 2, 1, 2, [1, 2, 4],
                                                     approved=False)]),
                   entry("flood_only_demo", [_vol("volunteer_rina", "Rina (synthetic)", "sim_phone_rina",
                                                  34.0900, -118.1000, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4])]),
                   entry("civic_shelter_demo", sites=[ShelterSite(site_id="dest_center_a", name="Civic Center (fictional)",
                                                                  location=point(34.0890, -118.0700), beds_available=12,
                                                                  features=[3, 4, 5, 6])]),
               ]),
        Region(region_id="la_county:south_valley", label="South Valley (synthetic)", center=point(34.058, -118.110),
               area=_rect(-118.160, 34.040, -118.060, 34.075), orgs=[
                   # Eligible alternate for Maria if Sarah declines.
                   entry("red_cross_demo", [_vol("volunteer_lee", "Lee (synthetic)", "sim_phone_lee",
                                                 34.0700, -118.1400, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4, 5])]),
                   entry("recovery_housing_demo"),
               ]),
        Region(region_id="la_county:westside", label="Westside (synthetic)", center=point(34.020, -118.400),
               area=_rect(-118.450, 33.980, -118.350, 34.060), orgs=[
                   entry("red_cross_demo", sites=[ShelterSite(site_id="rc_shelter_1", name="Red Cross Shelter (fictional)",
                                                              location=point(34.0300, -118.3800), beds_available=30,
                                                              features=[4, 5, 6])]),
               ]),
        # San Francisco: an org's far-away volunteers are never contacted for an LA fire.
        Region(region_id="sf:mission", label="SF Mission (synthetic)", center=point(37.755, -122.420),
               area=_rect(-122.440, 37.740, -122.400, 37.770), orgs=[
                   entry("red_cross_demo", [_vol("volunteer_sam", "Sam (synthetic)", "sim_phone_sam",
                                                 37.7600, -122.4200, "WHEELCHAIR_VAN", 2, 1, 1, [1, 2, 4])]),
               ]),
    ]


# ===================================================================== FULL DATASET
# Two demo datasets (decision B-45):
#   core  Maria, David, Sarah, Joe, ... Small and stable: every unit test, A's integration tests and the
#         scenario runner assert against it. Never add people here.
#   full  core + more residents, volunteers, orgs, shelters and a flood use case, for the live demo.
#         Chosen by POST /demo/reset {"dataset": "full"} or DEMO_DATASET=full (Render).
# Core stories stay the same in full: Sarah + Civic Center for Maria, David escalated.
# The cast and the expected outcome for each person are in docs/demo-cast.md.
DATASETS = ("core", "full")
FULL_OUTREACH_MAX_ORGS = 6  # full has 5 wildfire transport orgs; core keeps 3


def dataset_name(name: str | None = None) -> str:
    ds = (name or os.environ.get("DEMO_DATASET") or "core").strip().lower()
    if ds not in DATASETS:
        raise ValueError(f"Unknown demo dataset {ds!r}; options: {list(DATASETS)}")
    return ds


def _resident(rid, name, lang, label, lat, lon, needs, pets=0, wants=True, recovery=False, contact=None):
    consents = {"CHECKIN": True, "TRANSPORT": True, "DESTINATION": True, "RECOVERY": recovery}
    short = rid.removeprefix("resident_")
    contacts = [EmergencyContact(contact_id=f"contact_{short}", name=contact[0], phone=f"sim_phone_{short}_contact",
                                 relationship=contact[1])] if contact else []
    return ResidentProfile(resident_id=rid, name=name, phone=f"sim_phone_{short}", language=lang,
                           address=Address(label=f"SYNTHETIC: {label}", lat=lat, lon=lon), emergency_contacts=contacts,
                           needs=needs, pet_count=pets, wants_help_contact=wants, consents=consents,
                           registered_at=REGISTERED_AT)


def _full_extra_residents() -> list[ResidentProfile]:
    return [
        # Wildfire WARNING zone (zone_3 sector B)
        _resident("resident_ruth", "Ruth (synthetic)", "en", "Zone 3 Sector B meeting point 2", 34.0995, -118.0935,
                  [3, 9, 10], recovery=True, contact=("Paul (synthetic caregiver)", "caregiver")),
        _resident("resident_carlos", "Carlos (synthetic)", "es", "Zone 3 Sector B meeting point 6", 34.1025, -118.0920,
                  [8], pets=2, contact=("Lucia (synthetic)", "wife")),
        _resident("resident_kenji", "Kenji (synthetic)", "en", "Zone 3 Sector B meeting point 3", 34.0985, -118.0975,
                  [5, 8]),
        _resident("resident_grace", "Grace (synthetic)", "en", "Zone 3 Sector B meeting point 5", 34.1000, -118.0950,
                  [1], wants=False),  # opted out: never contacted
        # Wildfire ORDER zone (zone_3 sector A): escalation, like David
        _resident("resident_harold", "Harold (synthetic)", "en", "Zone 3 Sector A meeting point 2", 34.1080, -118.0940,
                  [3], contact=("June (synthetic)", "daughter")),
        # Outside every zone: not contacted
        _resident("resident_beatriz", "Beatriz (synthetic)", "es", "East Valley meeting point 9", 34.0870, -118.1150,
                  [1, 2]),
        # Flood WARNING zone (SOUTH_VALLEY_FLOOD preset)
        _resident("resident_omar", "Omar (synthetic)", "en", "South Valley meeting point 1", 34.0580, -118.1300,
                  [1, 2], recovery=True),
        _resident("resident_dolores", "Dolores (synthetic)", "es", "South Valley meeting point 4", 34.0560, -118.1260,
                  [], pets=3),
    ]


def _full_extra_organizations() -> list[Organization]:
    return [
        Organization(org_id="valley_paratransit_demo", name="Valley Paratransit Co-op (fictional)",
                     calamity_types=["WILDFIRE", "FLOOD"], services=["TRANSPORT"], approved=True, service_radius_km=25),
        Organization(org_id="hillside_drivers_demo", name="Hillside Community Drivers (fictional)",
                     calamity_types=["WILDFIRE"], services=["TRANSPORT"], approved=True, service_radius_km=15),
        Organization(org_id="insurance_help_desk_demo", name="Insurance Help Desk (fictional)",
                     calamity_types=["ANY"], services=["INSURANCE_GUIDANCE"], approved=True, service_radius_km=40,
                     recovery_services=["INSURANCE_GUIDANCE"]),
        Organization(org_id="community_supplies_demo", name="Community Supplies Bank (fictional)",
                     calamity_types=["ANY"], services=["SUPPLIES", "MEDICAL_EQUIPMENT_REPLACEMENT"], approved=True,
                     service_radius_km=40, recovery_services=["SUPPLIES", "MEDICAL_EQUIPMENT_REPLACEMENT"]),
    ]


def _full_extra_partners() -> dict[str, dict[str, dict]]:
    """region_id -> org_id -> {"volunteers": [...], "sites": [...]}, merged into the core regions."""
    return {
        "la_county:east_valley": {
            # Oxygen-ready van for Ruth (no pet space, so never Maria's match).
            "eastside_rides_demo": {"volunteers": [_vol("volunteer_nadia", "Nadia (synthetic)", "sim_phone_nadia",
                                                        34.0920, -118.1150, "WHEELCHAIR_VAN", 3, 1, 0, [1, 2, 3, 9, 10])]},
            # SUV with room for 2 pets: Carlos's match (Joe is closer but has room for 1 pet and no walker space).
            "neighbor_sedans_demo": {"volunteers": [_vol("volunteer_marcus", "Marcus (synthetic)", "sim_phone_marcus",
                                                         34.0930, -118.0850, "SUV", 4, 0, 2, [4, 7, 8])]},
            # Minivan that takes service animals: Kenji's match.
            "red_cross_demo": {"volunteers": [_vol("volunteer_fatima", "Fatima (synthetic)", "sim_phone_fatima",
                                                   34.0850, -118.1050, "MINIVAN", 5, 0, 1, [2, 4, 5, 7, 8])]},
            "valley_paratransit_demo": {"volunteers": [_vol("volunteer_mei", "Mei (synthetic)", "sim_phone_mei",
                                                            34.0960, -118.0880, "SEDAN", 3, 0, 0, [7, 8])]},
            # Beth waits for her coordinator's approval (GET /volunteers/pending?org_id=hillside_drivers_demo).
            "hillside_drivers_demo": {"volunteers": [
                _vol("volunteer_raj", "Raj (synthetic)", "sim_phone_raj", 34.0900, -118.0750, "SEDAN", 3, 0, 0, [7]),
                _vol("volunteer_beth", "Beth (synthetic)", "sim_phone_beth", 34.0910, -118.0780, "MINIVAN", 5, 0, 1,
                     [4, 8], approved=False)]},
            # Pet-friendly gym without oxygen support: Ruth's shelter must be the Civic Center.
            "civic_shelter_demo": {"sites": [ShelterSite(site_id="dest_gym_b", name="Eastside High Gym (fictional)",
                                                         location=point(34.0720, -118.0880), beds_available=40,
                                                         features=[4, 5, 6])]},
            "insurance_help_desk_demo": {},
            "community_supplies_demo": {},
        },
        "la_county:south_valley": {
            # Two wheelchair spaces and oxygen: closest match for Omar in the flood.
            "valley_paratransit_demo": {"volunteers": [_vol("volunteer_hector", "Hector (synthetic)", "sim_phone_hector",
                                                            34.0650, -118.1250, "HIGH_ROOF_VAN", 4, 2, 1,
                                                            [1, 2, 3, 8, 9, 10])]},
            # High-clearance truck with room for 3 pets: Dolores's match in the flood.
            "flood_only_demo": {"volunteers": [_vol("volunteer_diego", "Diego (synthetic)", "sim_phone_diego",
                                                    34.0620, -118.1350, "HIGH_CLEARANCE_TRUCK", 2, 0, 3, [4, 7, 8])]},
            "red_cross_demo": {"sites": [ShelterSite(site_id="dest_library_c", name="South Valley Library Hall (fictional)",
                                                     location=point(34.0680, -118.1100), beds_available=15,
                                                     features=[4, 6])]},
        },
    }


FULL_LINK_CODES = {
    "RUTH-2417": {"role": "RESIDENT", "resident_id": "resident_ruth", "case_id": "case_ruth_003",
                  "display_name": "Ruth (synthetic)"},
    "CARLOS-3851": {"role": "RESIDENT", "resident_id": "resident_carlos", "case_id": "case_carlos_004",
                    "display_name": "Carlos (synthetic)"},
    "KENJI-4962": {"role": "RESIDENT", "resident_id": "resident_kenji", "case_id": "case_kenji_005",
                   "display_name": "Kenji (synthetic)"},
    "HAROLD-5073": {"role": "RESIDENT", "resident_id": "resident_harold", "case_id": "case_harold_007",
                    "display_name": "Harold (synthetic)"},
    "OMAR-4093": {"role": "RESIDENT", "resident_id": "resident_omar", "case_id": "case_omar_009",
                  "display_name": "Omar (synthetic)"},
    "DOLORES-6184": {"role": "RESIDENT", "resident_id": "resident_dolores", "case_id": "case_dolores_010",
                     "display_name": "Dolores (synthetic)"},
    "NADIA-5162": {"role": "VOLUNTEER", "volunteer_id": "volunteer_nadia", "org_id": "eastside_rides_demo",
                   "display_name": "Nadia (synthetic)"},
    "MARCUS-6274": {"role": "VOLUNTEER", "volunteer_id": "volunteer_marcus", "org_id": "neighbor_sedans_demo",
                    "display_name": "Marcus (synthetic)"},
    "FATIMA-7395": {"role": "VOLUNTEER", "volunteer_id": "volunteer_fatima", "org_id": "red_cross_demo",
                    "display_name": "Fatima (synthetic)"},
    "HECTOR-7385": {"role": "VOLUNTEER", "volunteer_id": "volunteer_hector", "org_id": "valley_paratransit_demo",
                    "display_name": "Hector (synthetic)"},
    "MEI-8406": {"role": "VOLUNTEER", "volunteer_id": "volunteer_mei", "org_id": "valley_paratransit_demo",
                 "display_name": "Mei (synthetic)"},
    "DIEGO-8517": {"role": "VOLUNTEER", "volunteer_id": "volunteer_diego", "org_id": "flood_only_demo",
                   "display_name": "Diego (synthetic)"},
    "RAJ-9628": {"role": "VOLUNTEER", "volunteer_id": "volunteer_raj", "org_id": "hillside_drivers_demo",
                 "display_name": "Raj (synthetic)"},
    "BETH-9739": {"role": "VOLUNTEER", "volunteer_id": "volunteer_beth", "org_id": "hillside_drivers_demo",
                  "display_name": "Beth (synthetic)"},
}


def residents(dataset: str = "core") -> list[ResidentProfile]:
    core = _core_residents()
    return core + _full_extra_residents() if dataset_name(dataset) == "full" else core


def organizations(dataset: str = "core") -> list[Organization]:
    core = _core_organizations()
    return core + _full_extra_organizations() if dataset_name(dataset) == "full" else core


def regions(dataset: str = "core") -> list[Region]:
    core = _core_regions()
    if dataset_name(dataset) != "full":
        return core
    orgs = {o.org_id: o for o in organizations("full")}
    out = []
    for region in core:
        extra = _full_extra_partners().get(region.region_id, {})
        entries = []
        for e in region.orgs:
            add = extra.get(e.org_id, {})
            entries.append(e.model_copy(update={"volunteers": e.volunteers + add.get("volunteers", []),
                                                "shelter_sites": e.shelter_sites + add.get("sites", [])}))
        have = {e.org_id for e in region.orgs}
        for org_id, add in extra.items():
            if org_id not in have:
                entries.append(RegionOrg.from_org(orgs[org_id]).model_copy(
                    update={"volunteers": add.get("volunteers", []), "shelter_sites": add.get("sites", [])}))
        out.append(region.model_copy(update={"orgs": entries}))
    return out


def link_codes(dataset: str = "core") -> dict[str, dict]:
    return {**LINK_CODES, **FULL_LINK_CODES} if dataset_name(dataset) == "full" else dict(LINK_CODES)


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

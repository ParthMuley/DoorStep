"""TEMPORARY adapter: contract-v2 ResidentProfile -> the v1 ``Resident`` the
current engine still uses. Removed at the v2 switch-over (plan §6.2), when the
engine reads profiles and geofenced zones directly.

``legacy_sector`` (graph node for the v1 zone rule) is set only for seeded demo
residents; residents registered through the API have none, so the v1 engine
treats their zone as UNVERIFIED (fails closed).
"""

from __future__ import annotations

from typing import Optional

from doorstep.models import Caregiver, Consent, NeedCode, Needs, Resident, ResidentProfile


def to_legacy_resident(p: ResidentProfile, legacy_sector: Optional[str] = None) -> Resident:
    codes = set(p.needs)
    caregiver = None
    if p.emergency_contacts:
        c = p.emergency_contacts[0]
        caregiver = Caregiver(caregiver_id=c.contact_id or f"{p.resident_id}_contact_1",
                              display_name=c.name, contact_channel=c.phone)
    return Resident(
        resident_id=p.resident_id,
        zone_id="zone_3" if legacy_sector and legacy_sector.startswith("zone_3") else (legacy_sector or "unknown"),
        sector_id=legacy_sector,
        display_name=p.name,
        preferred_language=p.language,
        contact_channel=p.phone,
        needs=Needs(
            wheelchair_accessible_vehicle=NeedCode.WHEELCHAIR in codes,
            transfer_assistance=NeedCode.TRANSFER_ASSIST in codes,
            portable_oxygen_equipment=NeedCode.OXYGEN_EQUIPMENT in codes,
            pet_count=p.pet_count if NeedCode.PET in codes else 0,
            service_animal=NeedCode.SERVICE_ANIMAL in codes,
            preferred_language=p.language,
            destination_accessibility=["step_free_entry"] if NeedCode.STEP_FREE_DESTINATION in codes else [],
        ),
        consent=Consent(
            contact_for_checkins=p.consents.get("CHECKIN", False),
            share_transport_needs=p.consents.get("TRANSPORT", False),
            share_destination_needs=p.consents.get("DESTINATION", False),
            share_recovery_needs=p.consents.get("RECOVERY", False),
        ),
        caregiver=caregiver,
        pickup_point=p.address.label,
        last_confirmed_at=p.registered_at,
    )

"""Shared needs codes (contract v2.0 §2).

A resident's ``needs`` and a volunteer's ``needs_they_can_cater`` (and a shelter
site's ``features``) use the same integers, so matching is code-to-code:
resident needs ⊆ volunteer capabilities. Codes never change meaning; new codes
need a contract bump.
"""

from __future__ import annotations

from enum import IntEnum


class NeedCode(IntEnum):
    WHEELCHAIR = 1               # wheelchair-accessible vehicle (+ wheelchair_spaces >= 1)
    TRANSFER_ASSIST = 2          # help getting into the vehicle
    OXYGEN_EQUIPMENT = 3         # oxygen equipment handling
    PET = 4                      # pet space (+ pet_capacity >= pet_count)
    SERVICE_ANIMAL = 5
    STEP_FREE_DESTINATION = 6    # checked against the shelter site, not the vehicle
    SPANISH_SPEAKER = 7          # communication preference; NEVER a reason to reject
    MOBILITY_AID = 8             # walker / cane space
    MEDICAL_EQUIPMENT_SPACE = 9
    CAREGIVER_RIDES_ALONG = 10   # needs vehicle_seats >= 2


VALID_CODES = frozenset(int(c) for c in NeedCode)
# Codes that are preferences, not hard constraints.
PREFERENCE_CODES = frozenset({NeedCode.SPANISH_SPEAKER})
# Codes checked against the destination/shelter instead of the vehicle.
DESTINATION_CODES = frozenset({NeedCode.STEP_FREE_DESTINATION})


def validate_codes(codes: list[int]) -> list[int]:
    """Sorted, de-duplicated codes. Raises ValueError on unknown codes."""
    unknown = sorted({c for c in codes if c not in VALID_CODES})
    if unknown:
        raise ValueError(f"Unknown need codes {unknown}; valid codes are 1-{max(VALID_CODES)}")
    return sorted(set(codes))


def labels(codes: list[int]) -> list[str]:
    return [NeedCode(c).name for c in codes]

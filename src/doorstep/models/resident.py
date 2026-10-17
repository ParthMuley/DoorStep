"""Resident, caregiver, consent, and needs models (all synthetic)."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .common import DoorstepModel, Language


class Needs(DoorstepModel):
    """Accessibility / transport needs. No diagnoses or sensitive identifiers."""

    wheelchair_accessible_vehicle: bool = False
    transfer_assistance: bool = False
    portable_oxygen_equipment: bool = False
    pet_count: int = 0
    service_animal: bool = False
    preferred_language: Language = Language.EN
    destination_accessibility: list[str] = Field(default_factory=list)


class Consent(DoorstepModel):
    """Resident-controlled consent flags. Fixed-code gate, never inferred."""

    contact_for_checkins: bool = False
    share_transport_needs: bool = False
    share_destination_needs: bool = False
    share_recovery_needs: bool = False


class Caregiver(DoorstepModel):
    caregiver_id: str
    display_name: str
    contact_channel: str  # synthetic, e.g. "sms:+1555..."


class Resident(DoorstepModel):
    """Pseudonymous enrolled resident record."""

    resident_id: str
    zone_id: str
    display_name: str  # synthetic label, not a real identity
    preferred_language: Language = Language.EN
    contact_channel: str  # synthetic phone/channel
    needs: Needs = Field(default_factory=Needs)
    consent: Consent = Field(default_factory=Consent)
    caregiver: Optional[Caregiver] = None
    # Synthetic, fictional pickup point label. Shared only with an approved,
    # accepted transport provider when transport consent is granted.
    pickup_point: str = ""
    last_confirmed_at: Optional[str] = None
    simulated: bool = True


class ConsentGrant(DoorstepModel):
    """One recorded consent decision (audit trail for the Consent flags)."""

    case_id: str
    scope: str  # e.g. "share_recovery_needs"
    granted: bool
    granted_by: str  # resident_id or caregiver_id
    created_at: str

"""Pickup / arrival evidence rules (contract v1.0 evidence + optional party ids).

Pickup: provider confirmed AND (resident OR authorized caregiver) confirmed.
Arrival: a DESTINATION_CHECKIN by the accepted destination provider, OR the
resident/caregiver plus the transport provider both confirming.
When identified ``confirmations`` are supplied, every party id must match the
case's real participants; otherwise the evidence is rejected.
"""

from __future__ import annotations

from typing import Optional

from doorstep.models import Assignment, EvidenceParty as P, Evidence, Resident

from .errors import InsufficientEvidence


def _verify_party_ids(evidence: Evidence, resident: Resident, transport: Assignment,
                      destination: Optional[Assignment]) -> bool:
    if not evidence.confirmations:
        return False
    known = {P.RESIDENT.value: resident.resident_id, P.TRANSPORT_PROVIDER.value: transport.provider_id}
    if transport.volunteer_id:
        known[P.VOLUNTEER.value] = transport.volunteer_id
    if resident.caregiver:
        known[P.CAREGIVER.value] = resident.caregiver.caregiver_id
    if destination:
        known[P.DESTINATION_PROVIDER.value] = destination.provider_id
        known[P.SHELTER.value] = destination.provider_id
    for c in evidence.confirmations:
        if known.get(c.party) != c.party_id:
            raise InsufficientEvidence(f"Confirmation from unknown or mismatched party {c.party}:{c.party_id}",
                                       reasons=["UNKNOWN_CONFIRMING_PARTY"])
    return True


def _parties(evidence: Evidence) -> set[str]:
    """Union of the boolean flags and any identified confirmations.
    v2 parties map onto v1 roles: volunteer = transport provider, shelter = destination provider."""
    parties = {c.party for c in evidence.confirmations}
    if P.VOLUNTEER.value in parties or evidence.volunteer_confirmed:
        parties.add(P.TRANSPORT_PROVIDER.value)
    if P.SHELTER.value in parties:
        parties.add(P.DESTINATION_PROVIDER.value)
    if evidence.resident_confirmed:
        parties.add(P.RESIDENT.value)
    if evidence.caregiver_confirmed:
        parties.add(P.CAREGIVER.value)
    return parties


def check_pickup_evidence(evidence: Evidence, resident: Resident, transport: Assignment) -> bool:
    """Raise unless sufficient. Returns whether party ids were verified."""
    verified = _verify_party_ids(evidence, resident, transport, None)
    parties = _parties(evidence)
    if transport.resident_pickup_confirmed_at:  # resident/caregiver already confirmed by SMS
        parties.add(P.RESIDENT.value)
    if evidence.provider_confirmed:
        parties.add(P.TRANSPORT_PROVIDER.value)
    missing = []
    if P.TRANSPORT_PROVIDER.value not in parties:
        missing.append("PROVIDER_CONFIRMATION_MISSING")
    if not parties & {P.RESIDENT.value, P.CAREGIVER.value}:
        missing.append("RESIDENT_OR_CAREGIVER_CONFIRMATION_MISSING")
    if missing:
        raise InsufficientEvidence("Pickup evidence incomplete", reasons=missing)
    return verified


def check_arrival_evidence(evidence: Evidence, resident: Resident, transport: Assignment,
                           destination: Assignment) -> bool:
    verified = _verify_party_ids(evidence, resident, transport, destination)
    if evidence.destination_provider_id and evidence.destination_provider_id != destination.provider_id:
        raise InsufficientEvidence("Check-in is not from the agreed destination provider",
                                   reasons=["WRONG_DESTINATION_PROVIDER"])
    if evidence.shelter_org_id and evidence.shelter_org_id != destination.provider_id:
        raise InsufficientEvidence("Check-in is not from the agreed shelter", reasons=["WRONG_SHELTER"])
    if evidence.site_id and destination.site_id and evidence.site_id != destination.site_id:
        raise InsufficientEvidence("Check-in is not at the agreed shelter site", reasons=["WRONG_SHELTER_SITE"])
    parties = _parties(evidence)
    if evidence.type == "SHELTER_CHECKIN" and evidence.shelter_confirmed and evidence.shelter_org_id:
        parties.add(P.DESTINATION_PROVIDER.value)
    if evidence.provider_confirmed:
        if evidence.type == "DESTINATION_CHECKIN" and evidence.destination_provider_id:
            parties.add(P.DESTINATION_PROVIDER.value)
        elif evidence.type != "DESTINATION_CHECKIN":
            parties.add(P.TRANSPORT_PROVIDER.value)
    destination_checkin = P.DESTINATION_PROVIDER.value in parties
    resident_plus_driver = (bool(parties & {P.RESIDENT.value, P.CAREGIVER.value})
                            and P.TRANSPORT_PROVIDER.value in parties)
    if not (destination_checkin or resident_plus_driver):
        raise InsufficientEvidence(
            "Arrival needs a check-in by the agreed destination provider, or resident + transport provider",
            reasons=["ARRIVAL_CONFIRMATION_MISSING"])
    return verified

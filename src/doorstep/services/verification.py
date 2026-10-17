"""Pickup / arrival evidence rules.

Pickup: the transport provider AND the resident (or their authorized caregiver).
Arrival: the resident/caregiver AND either the destination provider or the
transport provider. Every party id must match the case's real participants.
"""

from __future__ import annotations

from typing import Optional

from doorstep.models import Assignment, EvidenceParty as P, Evidence, Resident

from .errors import InsufficientEvidence


def _known_parties(resident: Resident, transport: Assignment, destination: Optional[Assignment]) -> dict[str, str]:
    known = {P.RESIDENT.value: resident.resident_id, P.TRANSPORT_PROVIDER.value: transport.provider_id}
    if resident.caregiver:
        known[P.CAREGIVER.value] = resident.caregiver.caregiver_id
    if destination:
        known[P.DESTINATION_PROVIDER.value] = destination.provider_id
    return known


def validated_parties(evidence: Evidence, resident: Resident, transport: Assignment,
                      destination: Optional[Assignment]) -> set[str]:
    known = _known_parties(resident, transport, destination)
    parties = set()
    for c in evidence.confirmations:
        if known.get(c.party) != c.party_id:
            raise InsufficientEvidence(f"Confirmation from unknown or mismatched party {c.party}:{c.party_id}",
                                       reasons=["UNKNOWN_CONFIRMING_PARTY"])
        parties.add(c.party)
    return parties


def check_pickup_evidence(evidence: Evidence, resident: Resident, transport: Assignment) -> None:
    parties = validated_parties(evidence, resident, transport, None)
    missing = []
    if P.TRANSPORT_PROVIDER.value not in parties:
        missing.append("TRANSPORT_PROVIDER_CONFIRMATION_MISSING")
    if not parties & {P.RESIDENT.value, P.CAREGIVER.value}:
        missing.append("RESIDENT_OR_CAREGIVER_CONFIRMATION_MISSING")
    if missing:
        raise InsufficientEvidence("Pickup evidence incomplete", reasons=missing)


def check_arrival_evidence(evidence: Evidence, resident: Resident, transport: Assignment,
                           destination: Assignment) -> None:
    parties = validated_parties(evidence, resident, transport, destination)
    missing = []
    if not parties & {P.RESIDENT.value, P.CAREGIVER.value}:
        missing.append("RESIDENT_OR_CAREGIVER_CONFIRMATION_MISSING")
    if not parties & {P.DESTINATION_PROVIDER.value, P.TRANSPORT_PROVIDER.value}:
        missing.append("PROVIDER_CONFIRMATION_MISSING")
    if missing:
        raise InsufficientEvidence("Arrival evidence incomplete", reasons=missing)

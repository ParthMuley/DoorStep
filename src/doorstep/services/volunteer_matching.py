"""Deterministic resident ↔ volunteer / shelter matching (contract v2.0 §5.6,
plan decision 7). Plain code, no LLM, no ranking of people.

Volunteer is eligible only if ALL hold:
* org approved and offers TRANSPORT; volunteer approved; org handles the calamity type;
* volunteer answered AVAILABLE for THIS alert and is not reserved for another case;
* resident needs ⊆ needs_they_can_cater (code 7 SPANISH_SPEAKER never blocks; code 6 is
  checked on the shelter); wheelchair space, pet capacity and seats fit;
* resident zone is not ORDER / STALE / UNKNOWN (checked by the caller);
* within the org's service radius; the straight line volunteer → resident does not
  pass through an active ORDER polygon (illustrative check; real routing is B6).
Ranking: distance volunteer → resident, then volunteer_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from doorstep.models import NeedCode, Organization, ResidentProfile

from . import geo
from .db import Database  # noqa: F401  (type hints only)

TRANSPORT_EXCLUDED = {int(NeedCode.SPANISH_SPEAKER), int(NeedCode.STEP_FREE_DESTINATION)}
SHELTER_RELEVANT = {int(NeedCode.OXYGEN_EQUIPMENT), int(NeedCode.PET), int(NeedCode.SERVICE_ANIMAL),
                    int(NeedCode.STEP_FREE_DESTINATION)}
POSITIVE = {1: "WHEELCHAIR_OK", 2: "TRANSFER_OK", 3: "OXYGEN_OK", 4: "PET_OK", 5: "SERVICE_ANIMAL_OK"}
AVAILABILITY_CODES = {"ASKED": "AWAITING_REPLY", "UNAVAILABLE": "UNAVAILABLE", "NO_REPLY": "NO_REPLY",
                      "UNASKED": "NOT_ASKED_YET"}


@dataclass
class Candidate:
    org_id: str
    entity_id: str  # volunteer_id or site_id
    distance_km: float
    eligible: bool
    reason_codes: list[str]
    missing_needs: list[int] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    rank: Optional[int] = None

    def view(self, kind: str) -> dict[str, Any]:
        key = "volunteer_id" if kind == "volunteer" else "site_id"
        out = {"org_id": self.org_id, key: self.entity_id, "distance_km": self.distance_km,
               "reason_codes": self.reason_codes, **self.extra}
        if self.eligible:
            out["rank"] = self.rank
        if self.missing_needs:
            out["missing_needs"] = self.missing_needs
        return out


def _handles(org: Organization, calamity_type: str) -> bool:
    return calamity_type in ("UNKNOWN", "", None) or "ANY" in org.calamity_types or calamity_type in org.calamity_types


def _crosses(line: LineString, polygons: list[BaseGeometry]) -> bool:
    return any(line.intersects(p) and not line.touches(p) for p in polygons)


def _rank(cands: list[Candidate]) -> list[Candidate]:
    ordered = sorted(cands, key=lambda c: (not c.eligible, c.distance_km, c.entity_id))
    n = 0
    for c in ordered:
        if c.eligible:
            n += 1
            c.rank = n
    return ordered


def evaluate_volunteers(profile: ResidentProfile, case_id: str, alert_ids: set[str], calamity_type: str,
                        orgs: list[Organization], order_polygons: list[BaseGeometry],
                        declined: set[str]) -> list[Candidate]:
    """``alert_ids``: active alerts of the current event; availability for any of them counts."""
    needs = set(profile.needs)
    required = needs - TRANSPORT_EXCLUDED
    seats_needed = 1 + (1 if int(NeedCode.CAREGIVER_RIDES_ALONG) in needs else 0)
    lat, lon = profile.address.lat, profile.address.lon
    out: list[Candidate] = []
    for org in orgs:
        if "TRANSPORT" not in org.services:
            continue
        for v in org.volunteers:
            reasons: list[str] = []
            missing: list[int] = []
            km = round(geo.haversine_km(v.address.lat, v.address.lon, lat, lon), 1)
            if not org.approved:
                reasons.append("ORG_NOT_APPROVED")
            if not v.approved:
                reasons.append("VOLUNTEER_NOT_APPROVED")
            if not _handles(org, calamity_type):
                reasons.append("CALAMITY_TYPE_NOT_SUPPORTED")
            if v.volunteer_id in declined:
                reasons.append("ALREADY_DECLINED")
            a = v.availability
            if a is None or not alert_ids:
                reasons.append("NOT_ASKED_YET")
            elif a.alert_id not in alert_ids:
                reasons.append("AVAILABILITY_FROM_OLD_ALERT")
            elif a.state != "AVAILABLE":
                reasons.append(AVAILABILITY_CODES.get(a.state, "UNAVAILABLE"))
            if v.reserved_case_id and v.reserved_case_id != case_id:
                reasons.append("ALREADY_RESERVED")
            missing = sorted(required - set(v.needs_they_can_cater))
            if missing:
                reasons.append("NEEDS_NOT_COVERED")
            if int(NeedCode.WHEELCHAIR) in needs and v.wheelchair_spaces < 1:
                reasons.append("NO_WHEELCHAIR_SPACE")
            if profile.pet_count > v.pet_capacity:
                reasons.append("INSUFFICIENT_PET_CAPACITY")
            if v.vehicle_seats < seats_needed:
                reasons.append("NO_SEATS")
            if km > org.service_radius_km:
                reasons.append("OUTSIDE_SERVICE_RADIUS")
            if _crosses(LineString([(v.address.lon, v.address.lat), (lon, lat)]), order_polygons):
                reasons.append("ROUTE_THROUGH_ORDER_ZONE")
            eligible = not reasons
            if eligible:
                reasons = (["ORG_APPROVED", "VOLUNTEER_APPROVED", "CALAMITY_TYPE_SUPPORTED", "WITHIN_SERVICE_RADIUS",
                            "AVAILABLE_FOR_THIS_ALERT", "NEEDS_COVERED"]
                           + [POSITIVE[c] for c in sorted(required) if c in POSITIVE]
                           + ["SEATS_OK", "OUTSIDE_ORDER_ZONE", "ROUTE_AVOIDS_ORDER_ZONES"])
            out.append(Candidate(org_id=org.org_id, entity_id=v.volunteer_id, distance_km=km, eligible=eligible,
                                 reason_codes=reasons, missing_needs=missing if not eligible else [],
                                 extra={"vehicle_type": v.vehicle_type, "org_agent_address": org.agent_address}))
    return _rank(out)


def evaluate_shelters(profile: ResidentProfile, calamity_type: str, orgs: list[Organization],
                      order_polygons: list[BaseGeometry]) -> list[Candidate]:
    needs = set(profile.needs)
    required = needs & SHELTER_RELEVANT
    if int(NeedCode.WHEELCHAIR) in needs:
        required.add(int(NeedCode.STEP_FREE_DESTINATION))  # a wheelchair user needs step-free entry
    out: list[Candidate] = []
    for org in orgs:
        if "SHELTER" not in org.services:
            continue
        for s in org.shelter_sites:
            reasons: list[str] = []
            km = round(geo.haversine_km(profile.address.lat, profile.address.lon, s.lat, s.lon), 1)
            if not org.approved:
                reasons.append("ORG_NOT_APPROVED")
            if not _handles(org, calamity_type):
                reasons.append("CALAMITY_TYPE_NOT_SUPPORTED")
            missing = sorted(required - set(s.features))
            if missing:
                reasons.append("NEEDS_NOT_COVERED")
            if s.beds_available < 1:
                reasons.append("NO_BEDS")
            if any(geo.covers(p, s.lat, s.lon) for p in order_polygons):
                reasons.append("SHELTER_IN_ORDER_ZONE")
            eligible = not reasons
            if eligible:
                reasons = ["ORG_APPROVED", "NEEDS_COVERED"] + (
                    ["STEP_FREE_OK"] if int(NeedCode.STEP_FREE_DESTINATION) in required else []) + (
                    ["PET_OK"] if int(NeedCode.PET) in required else []) + ["BEDS_OK", "OUTSIDE_ORDER_ZONE"]
            out.append(Candidate(org_id=org.org_id, entity_id=s.site_id, distance_km=km, eligible=eligible,
                                 reason_codes=reasons, missing_needs=missing if not eligible else [],
                                 extra={"site_name": s.name, "shelter_agent_address": org.agent_address}))
    return _rank(out)


def eta_minutes(distance_km: float) -> int:
    """Illustrative estimate only (30 km/h average + 3 min), never a guarantee."""
    return max(3, round(distance_km / 30 * 60) + 3)

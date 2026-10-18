"""Registration and organization-scoped volunteer operations (contract v2.0 §5.2, §5.4).

Residents register into ``doorstep_users``; organizations register themselves and
their volunteers into ``doorstep_orgs``. An Organization agent only ever sees and
changes its own org (enforced by the API's ``X-Org-Agent`` check and by every
lookup here being keyed on ``org_id``).
"""

from __future__ import annotations

from typing import Any, Optional

from doorstep.models import (
    AvailabilityState,
    Organization,
    ResidentProfile,
    Volunteer,
    VolunteerAvailability,
    utc_now_iso,
)

from .db import Database
from .errors import Conflict, NotFound
from .event_log import EventLog
from .store import Store


def zone_status_for(profile: ResidentProfile) -> str:
    """Fallback before the alert service is wired in: no feed data -> UNKNOWN (never 'safe')."""
    return "UNKNOWN"


class RegistryService:
    def __init__(self, db: Database, store: Store, events: EventLog):
        self.db = db
        self.store = store
        self.events = events
        self.zone_lookup = zone_status_for  # replaced by AlertService.zone_status_label (polygon geofence)

    # ------------------------------------------------------------- residents
    def _new_resident_id(self) -> str:
        while True:
            rid = self.db.next_id("resident")
            if not self.store.find_resident_profile(rid):
                return rid

    def register_resident(self, profile: ResidentProfile, correlation_id: str = "") -> dict[str, Any]:
        if profile.resident_id and self.store.find_resident_profile(profile.resident_id):
            raise Conflict(f"Resident {profile.resident_id!r} already registered", code="ALREADY_REGISTERED")
        rid = profile.resident_id or self._new_resident_id()
        contacts = [c.model_copy(update={"contact_id": c.contact_id or f"{rid}_contact_{i}"})
                    for i, c in enumerate(profile.emergency_contacts, start=1)]
        profile = profile.model_copy(update={"resident_id": rid, "emergency_contacts": contacts,
                                             "registered_at": profile.registered_at or utc_now_iso()})
        with self.db.tx():
            self.store.save_resident_profile(profile)
            self.events.append("RESIDENT_REGISTERED", case_id=None, correlation_id=correlation_id,
                               data={"resident_id": rid, "needs": profile.needs})
        return {"resident_id": rid, "zone_status": self.zone_lookup(profile), "consents": profile.consents,
                "needs": profile.needs, "created_at": profile.registered_at}

    # --------------------------------------------------------- organizations
    @staticmethod
    def _fresh_volunteer(v: Volunteer) -> Volunteer:
        # Availability and reservations are set only by outreach/matching, never at registration.
        return v.model_copy(update={"availability": None, "reserved_case_id": None})

    def register_organization(self, org: Organization, correlation_id: str = "") -> dict[str, Any]:
        if self.store.find_organization(org.org_id):
            raise Conflict(f"Organization {org.org_id!r} already registered", code="ALREADY_REGISTERED")
        org = org.model_copy(update={"volunteers": [self._fresh_volunteer(v) for v in org.volunteers]})
        with self.db.tx():
            self.store.save_organization(org)
            self.events.append("ORGANIZATION_REGISTERED", case_id=None, correlation_id=correlation_id,
                               data={"org_id": org.org_id, "approved": org.approved,
                                     "volunteers": len(org.volunteers)})
        return {"org_id": org.org_id, "approved": org.approved,
                "volunteers": [v.volunteer_id for v in org.volunteers],
                "shelter_sites": [s.site_id for s in org.shelter_sites]}

    def add_volunteer(self, org_id: str, volunteer: Volunteer, correlation_id: str = "") -> dict[str, Any]:
        org = self.store.get_organization(org_id)
        if any(v.volunteer_id == volunteer.volunteer_id for v in org.volunteers):
            raise Conflict(f"Volunteer {volunteer.volunteer_id!r} already in {org_id}", code="ALREADY_REGISTERED")
        with self.db.tx():
            if not self.store.add_volunteer(org_id, self._fresh_volunteer(volunteer)):
                raise Conflict("Volunteer could not be added", code="ALREADY_REGISTERED")
            self.events.append("VOLUNTEER_REGISTERED", case_id=None, correlation_id=correlation_id,
                               data={"org_id": org_id, "volunteer_id": volunteer.volunteer_id,
                                     "approved": volunteer.approved})
        return {"org_id": org_id, "volunteer_id": volunteer.volunteer_id, "approved": volunteer.approved}

    def list_organizations(self) -> list[dict[str, Any]]:
        """Sanitized registry for cards: no volunteer addresses or phones."""
        return [{
            "org_id": o.org_id, "name": o.name, "location": {"label": o.location.label},
            "calamity_types": o.calamity_types, "services": o.services, "approved": o.approved,
            "service_radius_km": o.service_radius_km, "volunteer_count": len(o.volunteers),
            "approved_volunteer_count": sum(1 for v in o.volunteers if v.approved),
            "shelter_sites": [{"site_id": s.site_id, "name": s.name, "beds_available": s.beds_available,
                               "features": s.features} for s in o.shelter_sites],
            "recovery_services": o.recovery_services, "simulated": True,
        } for o in self.store.list_organizations()]

    # ------------------------------------------------- org-scoped volunteers
    @staticmethod
    def _availability_view(v: Volunteer, alert_id: Optional[str]) -> dict[str, Any]:
        a = v.availability
        if a is None or (alert_id and a.alert_id != alert_id):
            return {"alert_id": alert_id, "state": AvailabilityState.UNASKED.value, "responded_at": None}
        return a.model_dump()

    def org_volunteers(self, org_id: str, alert_id: Optional[str] = None) -> dict[str, Any]:
        """Full volunteer records for ONE org (its agent needs phones to message them)."""
        org = self.store.get_organization(org_id)
        return {"org_id": org_id, "alert_id": alert_id, "volunteers": [
            {**v.model_dump(exclude={"availability"}), "availability": self._availability_view(v, alert_id)}
            for v in org.volunteers]}

    def record_availability(self, org_id: str, volunteer_id: str, *, alert_id: str, available: bool,
                            responded_at: Optional[str] = None, idempotency_key: Optional[str] = None,
                            correlation_id: str = "") -> dict[str, Any]:
        org = self.store.get_organization(org_id)
        volunteer = next((v for v in org.volunteers if v.volunteer_id == volunteer_id), None)
        if volunteer is None:
            raise NotFound(f"Volunteer {volunteer_id!r} not found in {org_id}")
        if not volunteer.approved:
            raise Conflict("Volunteer is not approved by the partner organization", code="VOLUNTEER_NOT_APPROVED")
        current = volunteer.availability
        if current is not None and current.alert_id != alert_id:
            # Outreach for a different alert is current: an answer for another alert is stale
            # (checked before idempotency, so a replayed old answer is refused, not echoed).
            raise Conflict(f"Availability is being collected for {current.alert_id}, not {alert_id}",
                           code="STALE_AVAILABILITY")
        key = idempotency_key or f"{alert_id}:avail:{volunteer_id}:{'yes' if available else 'no'}"
        existing = self.db.coll("provider_events").find_one({"_id": key})
        if existing:
            return {"volunteer_id": volunteer_id, "alert_id": existing["alert_id"],
                    "availability": existing["state"], "duplicate": True}
        state = AvailabilityState.AVAILABLE if available else AvailabilityState.UNAVAILABLE
        record = VolunteerAvailability(alert_id=alert_id, state=state, responded_at=responded_at or utc_now_iso())
        with self.db.tx():
            self.store.set_volunteer_availability(org_id, volunteer_id, record)
            self.store.record_provider_event(key, {"type": "VOLUNTEER_AVAILABILITY", "org_id": org_id,
                                                   "volunteer_id": volunteer_id, "alert_id": alert_id,
                                                   "state": state.value, "at": record.responded_at})
            self.events.append("VOLUNTEER_AVAILABILITY_RECORDED", case_id=None, correlation_id=correlation_id,
                               data={"org_id": org_id, "volunteer_id": volunteer_id, "alert_id": alert_id,
                                     "state": state.value})
        return {"volunteer_id": volunteer_id, "alert_id": alert_id, "availability": state.value, "duplicate": False}

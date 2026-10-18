"""Registration and volunteer availability (contract v2.1 §5.2, §5.4).

Residents register into ``doorstep_users``. Organizations register a canonical
record; their volunteers and shelter sites are registered *where they are*, in the
location-first ``doorstep_partners.regions`` (plan rev 3). Every network write
names an ``org_id`` and B checks the volunteer belongs to it.
"""

from __future__ import annotations

from typing import Any, Optional

from doorstep.models import (
    AvailabilityState,
    Organization,
    Region,
    RegionOrg,
    ResidentProfile,
    ShelterSite,
    Volunteer,
    VolunteerAvailability,
    utc_now_iso,
)
from doorstep.models.registry import ORG_FACT_FIELDS

from . import geo

from .db import Database
from .errors import Conflict, NotFound, Unauthorized
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
    def register_organization(self, org: Organization, correlation_id: str = "") -> tuple[dict[str, Any], bool]:
        """Create or update the canonical org record; copies its facts into every region it appears in."""
        partners = self.store.partners
        created = partners.find_org(org.org_id) is None
        with self.db.tx():
            partners.save_org(org)
            region_ids = []
            for region in partners.regions_of_org(org.org_id):
                region_ids.append(region.region_id)

                def fn(r: Region):
                    entry = next(o for o in r.orgs if o.org_id == org.org_id)
                    for f in ORG_FACT_FIELDS:
                        setattr(entry, f, getattr(org, f))
                    return True, None
                partners.mutate_region(region.region_id, fn)
            self.events.append("ORGANIZATION_REGISTERED" if created else "ORGANIZATION_UPDATED", case_id=None,
                               correlation_id=correlation_id,
                               data={"org_id": org.org_id, "approved": org.approved, "regions": region_ids})
        return {"org_id": org.org_id, "approved": org.approved, "region_ids": region_ids}, created

    def create_region(self, region: Region, correlation_id: str = "") -> dict[str, Any]:
        partners = self.store.partners
        if partners.find_region(region.region_id):
            raise Conflict(f"Region {region.region_id!r} already exists", code="ALREADY_REGISTERED")
        if geo.polygon(region.area) is None:
            raise Conflict("Region area must be a valid polygon", code="VALIDATION_ERROR")
        clash = partners.overlapping_region(region.area)
        if clash:
            raise Conflict(f"Region area overlaps {clash}", code="REGION_OVERLAP", reasons=[clash])
        with self.db.tx():
            partners.save_region(region.model_copy(update={"orgs": []}))
            self.events.append("REGION_CREATED", case_id=None, correlation_id=correlation_id,
                               data={"region_id": region.region_id})
        return {"region_id": region.region_id, "label": region.label}

    def _ensure_presence(self, region: Region, org: Organization) -> None:
        if not any(o.org_id == org.org_id for o in region.orgs):
            region.orgs.append(RegionOrg.from_org(org))

    def add_presence(self, region_id: str, org_id: str, correlation_id: str = "") -> dict[str, Any]:
        partners = self.store.partners
        org = partners.get_org(org_id)
        partners.get_region(region_id)

        def fn(r: Region):
            if any(o.org_id == org_id for o in r.orgs):
                return False, False
            self._ensure_presence(r, org)
            return True, True
        added = partners.mutate_region(region_id, fn)
        if added:
            self.events.append("ORG_PRESENCE_ADDED", case_id=None, correlation_id=correlation_id,
                               data={"region_id": region_id, "org_id": org_id})
        return {"region_id": region_id, "org_id": org_id, "added": added}

    def _check_location(self, region_id: str, lat: float, lon: float) -> None:
        home = self.store.partners.region_for_point(lat, lon)
        if home is None:
            raise Conflict("Location is not inside any registered region", code="WRONG_REGION", reasons=["NO_REGION"])
        if home.region_id != region_id:
            raise Conflict(f"Location is inside {home.region_id}, not {region_id}", code="WRONG_REGION",
                           reasons=[f"CORRECT_REGION:{home.region_id}"])

    def add_volunteer(self, region_id: str, org_id: str, volunteer: Volunteer,
                      correlation_id: str = "") -> dict[str, Any]:
        """Register a volunteer where they are. Each volunteer: one org, one region."""
        partners = self.store.partners
        org = partners.get_org(org_id)
        partners.get_region(region_id)
        self._check_location(region_id, volunteer.location.lat, volunteer.location.lon)
        if partners.locate_volunteer(volunteer.volunteer_id):
            raise Conflict(f"Volunteer {volunteer.volunteer_id!r} already registered", code="ALREADY_REGISTERED")
        fresh = volunteer.model_copy(update={"availability": None, "reserved_case_id": None})

        def fn(r: Region):
            self._ensure_presence(r, org)
            next(o for o in r.orgs if o.org_id == org_id).volunteers.append(fresh)
            return True, None
        with self.db.tx():
            partners.mutate_region(region_id, fn)
            self.events.append("VOLUNTEER_REGISTERED", case_id=None, correlation_id=correlation_id,
                               data={"region_id": region_id, "org_id": org_id, "volunteer_id": volunteer.volunteer_id,
                                     "approved": volunteer.approved})
        return {"region_id": region_id, "org_id": org_id, "volunteer_id": volunteer.volunteer_id,
                "approved": volunteer.approved}

    def add_site(self, region_id: str, org_id: str, site: ShelterSite, correlation_id: str = "") -> dict[str, Any]:
        partners = self.store.partners
        org = partners.get_org(org_id)
        partners.get_region(region_id)
        self._check_location(region_id, site.location.lat, site.location.lon)
        if partners.locate_site(site.site_id):
            raise Conflict(f"Shelter site {site.site_id!r} already registered", code="ALREADY_REGISTERED")

        def fn(r: Region):
            self._ensure_presence(r, org)
            next(o for o in r.orgs if o.org_id == org_id).shelter_sites.append(site)
            return True, None
        with self.db.tx():
            partners.mutate_region(region_id, fn)
            self.events.append("SHELTER_SITE_REGISTERED", case_id=None, correlation_id=correlation_id,
                               data={"region_id": region_id, "org_id": org_id, "site_id": site.site_id})
        return {"region_id": region_id, "org_id": org_id, "site_id": site.site_id}

    def list_organizations(self) -> list[dict[str, Any]]:
        """Sanitized canonical records for cards: no phones, no locations."""
        partners = self.store.partners
        out = []
        for org in partners.list_orgs():
            regions = partners.regions_of_org(org.org_id)
            entries = [o for r in regions for o in r.orgs if o.org_id == org.org_id]
            out.append({
                "org_id": org.org_id, "name": org.name, "calamity_types": org.calamity_types,
                "services": org.services, "approved": org.approved, "service_radius_km": org.service_radius_km,
                "recovery_services": org.recovery_services, "region_ids": [r.region_id for r in regions],
                "volunteer_count": sum(len(e.volunteers) for e in entries),
                "approved_volunteer_count": sum(1 for e in entries for v in e.volunteers if v.approved),
                "shelter_sites": [{"site_id": s.site_id, "name": s.name, "beds_available": s.beds_available,
                                   "features": s.features} for e in entries for s in e.shelter_sites],
                "simulated": True,
            })
        return out

    # ----------------------------------------------------- availability
    def record_availability(self, alert_id: str, volunteer_id: str, *, org_id: str, available: bool,
                            responded_at: Optional[str] = None, idempotency_key: Optional[str] = None,
                            correlation_id: str = "") -> dict[str, Any]:
        partners = self.store.partners
        found = partners.locate_volunteer(volunteer_id)
        if found is None:
            raise NotFound(f"Volunteer {volunteer_id!r} not found")
        region, entry, volunteer = found
        if entry.org_id != org_id:
            raise Unauthorized("Volunteer does not belong to this organization", reasons=["WRONG_ORG"])
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
            return {"volunteer_id": volunteer_id, "org_id": org_id, "alert_id": existing["alert_id"],
                    "availability": existing["state"], "duplicate": True}
        state = AvailabilityState.AVAILABLE if available else AvailabilityState.UNAVAILABLE
        record = VolunteerAvailability(alert_id=alert_id, state=state, responded_at=responded_at or utc_now_iso())
        with self.db.tx():
            partners.set_availability(volunteer_id, record)
            self.store.record_provider_event(key, {"type": "VOLUNTEER_AVAILABILITY", "org_id": org_id,
                                                   "region_id": region.region_id, "volunteer_id": volunteer_id,
                                                   "alert_id": alert_id, "state": state.value,
                                                   "at": record.responded_at})
            self.events.append("VOLUNTEER_AVAILABILITY_RECORDED", case_id=None, correlation_id=correlation_id,
                               data={"org_id": org_id, "region_id": region.region_id, "volunteer_id": volunteer_id,
                                     "alert_id": alert_id, "state": state.value})
        return {"volunteer_id": volunteer_id, "org_id": org_id, "alert_id": alert_id, "availability": state.value,
                "duplicate": False}

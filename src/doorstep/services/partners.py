"""Location-first partner database (plan rev 3, contract v2.1 §9).

``doorstep_partners.organizations``: canonical org records (no volunteers).
``doorstep_partners.regions``: one document per area → orgs → only their local
volunteers and shelter sites. Each volunteer belongs to one org and one region.

Nested edits use optimistic compare-and-swap on the region document (``_rev``):
read, change in Python, write only if ``_rev`` is unchanged, retry otherwise. That
makes reservations, availability and beds atomic on mongomock and real MongoDB.
Geo: real MongoDB pre-filters with ``2dsphere`` (``$geoIntersects``); mongomock
has no geo operators, so the fallback scans. Both then use the same exact Shapely
distance, so results are identical.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Optional

from pymongo import GEOSPHERE
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from doorstep.models import (
    AvailabilityState,
    Organization,
    Region,
    RegionOrg,
    Volunteer,
    VolunteerAvailability,
)

from . import geo
from .db import Database
from .errors import Conflict, NotFound

MAX_CAS_RETRIES = 10
AGENT_ROLES = ("doorstep", "calamity_checker", "matching", "volunteer_network", "escalation",
               "post_calamity", "news", "route")


def _strip(doc: Optional[dict]) -> dict:
    return {k: v for k, v in (doc or {}).items() if not k.startswith("_")}


class PartnerStore:
    def __init__(self, db: Database):
        self.db = db
        self.is_mock = type(db.client).__module__.startswith("mongomock")
        regions = self.db.coll("regions")
        if not self.is_mock:
            existing = regions.index_information()
            for field in ("center", "area"):
                if f"regions__{field}_2dsphere" not in existing:
                    regions.create_index([(field, GEOSPHERE)], name=f"regions__{field}_2dsphere")

    # ------------------------------------------------------- organizations
    def save_org(self, o: Organization) -> None:
        self.db.coll("organizations").update_one({"_id": o.org_id}, {"$set": o.model_dump(mode="json")}, upsert=True)

    def find_org(self, org_id: str) -> Optional[Organization]:
        d = self.db.coll("organizations").find_one({"_id": org_id})
        return Organization.model_validate(_strip(d)) if d else None

    def get_org(self, org_id: str) -> Organization:
        org = self.find_org(org_id)
        if org is None:
            raise NotFound(f"Organization {org_id!r} not found")
        return org

    def list_orgs(self) -> list[Organization]:
        return [Organization.model_validate(_strip(d)) for d in self.db.coll("organizations").find({}).sort("_id", 1)]

    # ------------------------------------------------------------- regions
    def _region(self, doc: dict) -> Region:
        return Region.model_validate(_strip(doc))

    def save_region(self, r: Region) -> None:
        self.db.coll("regions").update_one({"_id": r.region_id},
                                           {"$set": r.model_dump(mode="json"), "$inc": {"_rev": 1}}, upsert=True)

    def find_region(self, region_id: str) -> Optional[Region]:
        d = self.db.coll("regions").find_one({"_id": region_id})
        return self._region(d) if d else None

    def get_region(self, region_id: str) -> Region:
        r = self.find_region(region_id)
        if r is None:
            raise NotFound(f"Region {region_id!r} not found")
        return r

    def list_regions(self) -> list[Region]:
        return [self._region(d) for d in self.db.coll("regions").find({}).sort("_id", 1)]

    def mutate_region(self, region_id: str, fn: Callable[[Region], tuple[bool, Any]]) -> Any:
        """Compare-and-swap: ``fn`` edits the Region and returns (changed, result)."""
        coll = self.db.coll("regions")
        for _ in range(MAX_CAS_RETRIES):
            doc = coll.find_one({"_id": region_id})
            if doc is None:
                raise NotFound(f"Region {region_id!r} not found")
            region = self._region(doc)
            changed, result = fn(region)
            if not changed:
                return result
            region = Region.model_validate(region.model_dump())  # re-validate invariants (unique ids)
            done = coll.update_one({"_id": region_id, "_rev": doc.get("_rev", 0)},
                                   {"$set": region.model_dump(mode="json"), "$inc": {"_rev": 1}})
            if done.modified_count == 1:
                return result
        raise Conflict("Region was updated concurrently; please retry", code="CONCURRENT_UPDATE")

    def entries(self) -> Iterator[tuple[Region, RegionOrg]]:
        for region in self.list_regions():
            for org in region.orgs:
                yield region, org

    def regions_of_org(self, org_id: str) -> list[Region]:
        return [self._region(d) for d in self.db.coll("regions").find({"orgs.org_id": org_id}).sort("_id", 1)]

    # --------------------------------------------------------------- geo
    def region_for_point(self, lat: float, lon: float) -> Optional[Region]:
        pt = Point(lon, lat)
        if self.is_mock:
            candidates = self.list_regions()
        else:
            candidates = [self._region(d) for d in self.db.coll("regions").find(
                {"area": {"$geoIntersects": {"$geometry": {"type": "Point", "coordinates": [lon, lat]}}}})]
        hits = [r for r in candidates if shape(r.area).covers(pt)]
        return sorted(hits, key=lambda r: r.region_id)[0] if hits else None

    def regions_near(self, origin: BaseGeometry, max_km: float) -> list[tuple[Region, float]]:
        """Regions within ``max_km`` of ``origin`` (a zone polygon or point), nearest first."""
        if self.is_mock:
            candidates = self.list_regions()
        else:
            probe = origin.buffer(geo.km_to_degrees(max_km))
            candidates = [self._region(d) for d in self.db.coll("regions").find(
                {"area": {"$geoIntersects": {"$geometry": probe.__geo_interface__}}})]
        out = []
        for r in candidates:
            km = round(geo.geometry_distance_km(origin, shape(r.area)), 1)
            if km <= max_km:
                out.append((r, km))
        return sorted(out, key=lambda x: (x[1], x[0].region_id))

    def overlapping_region(self, area: dict) -> Optional[str]:
        new = shape(area)
        for r in self.list_regions():
            if new.intersection(shape(r.area)).area > 1e-12:  # touching edges is fine
                return r.region_id
        return None

    # -------------------------------------------------- volunteer / site lookup
    def locate_volunteer(self, volunteer_id: str) -> Optional[tuple[Region, RegionOrg, Volunteer]]:
        d = self.db.coll("regions").find_one({"orgs.volunteers.volunteer_id": volunteer_id})
        if not d:
            return None
        region = self._region(d)
        for org in region.orgs:
            for v in org.volunteers:
                if v.volunteer_id == volunteer_id:
                    return region, org, v
        return None

    def locate_volunteer_by_phone(self, phone: str) -> Optional[tuple[Region, RegionOrg, Volunteer]]:
        d = self.db.coll("regions").find_one({"orgs.volunteers.phone": phone})
        if not d:
            return None
        for org in self._region(d).orgs:
            for v in org.volunteers:
                if v.phone == phone:
                    return self.locate_volunteer(v.volunteer_id)
        return None

    def locate_site(self, site_id: str) -> Optional[tuple[Region, RegionOrg, Any]]:
        d = self.db.coll("regions").find_one({"orgs.shelter_sites.site_id": site_id})
        if not d:
            return None
        region = self._region(d)
        for org in region.orgs:
            for s in org.shelter_sites:
                if s.site_id == site_id:
                    return region, org, s
        return None

    @staticmethod
    def _find_volunteer(region: Region, volunteer_id: str) -> Optional[Volunteer]:
        return next((v for o in region.orgs for v in o.volunteers if v.volunteer_id == volunteer_id), None)

    # ------------------------------------------------- atomic volunteer edits
    def set_availability(self, volunteer_id: str, availability: VolunteerAvailability) -> bool:
        found = self.locate_volunteer(volunteer_id)
        if not found:
            return False

        def fn(region: Region):
            v = self._find_volunteer(region, volunteer_id)
            v.availability = availability
            return True, True
        return self.mutate_region(found[0].region_id, fn)

    def reserve_volunteer(self, volunteer_id: str, case_id: str, alert_ids) -> bool:
        """Atomic: reserve only if AVAILABLE for one of ``alert_ids`` and not reserved by another case."""
        ids = {alert_ids} if isinstance(alert_ids, str) else set(alert_ids)
        found = self.locate_volunteer(volunteer_id)
        if not found:
            return False

        def fn(region: Region):
            v = self._find_volunteer(region, volunteer_id)
            if v.reserved_case_id == case_id:
                return False, True
            a = v.availability
            if v.reserved_case_id or a is None or a.state != AvailabilityState.AVAILABLE.value or a.alert_id not in ids:
                return False, False
            v.reserved_case_id = case_id
            return True, True
        return self.mutate_region(found[0].region_id, fn)

    def release_volunteer(self, volunteer_id: str, case_id: str) -> bool:
        found = self.locate_volunteer(volunteer_id)
        if not found:
            return False

        def fn(region: Region):
            v = self._find_volunteer(region, volunteer_id)
            if v.reserved_case_id != case_id:
                return False, False
            v.reserved_case_id = None
            return True, True
        return self.mutate_region(found[0].region_id, fn)

    def take_bed(self, site_id: str) -> bool:
        found = self.locate_site(site_id)
        if not found:
            return False

        def fn(region: Region):
            site = next(s for o in region.orgs for s in o.shelter_sites if s.site_id == site_id)
            if site.beds_available < 1:
                return False, False
            site.beds_available -= 1
            return True, True
        return self.mutate_region(found[0].region_id, fn)

    def return_bed(self, site_id: str) -> None:
        found = self.locate_site(site_id)
        if found:
            def fn(region: Region):
                site = next(s for o in region.orgs for s in o.shelter_sites if s.site_id == site_id)
                site.beds_available += 1
                return True, None
            self.mutate_region(found[0].region_id, fn)

    # ----------------------------------------------------------- agents
    def set_agent(self, role: str, address: str) -> None:
        if role not in AGENT_ROLES:
            raise NotFound(f"Unknown agent role {role!r}; roles: {list(AGENT_ROLES)}")
        self.db.coll("agents").update_one({"_id": role}, {"$set": {"role": role, "agent_address": address}},
                                          upsert=True)

    def agent_address(self, role: str) -> Optional[str]:
        d = self.db.coll("agents").find_one({"_id": role})
        return d["agent_address"] if d else None

    def list_agents(self) -> dict[str, str]:
        return {d["_id"]: d["agent_address"] for d in self.db.coll("agents").find({})}

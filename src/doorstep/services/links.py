"""ASI:One account linking, self-registration and volunteer invites (contract v2.2,
plan rev 4 §0.1/§0.5, rev 5 §00, rev 6 §000.3). DOORSTEP DEMO.

* Only the Doorstep agent calls /link and /register (checked by the API with its token).
  The ASI:One address is the message envelope's sender, never typed text.
* A code works once, even from the same address. The seeded demo codes are PUBLIC
  (they are in the repo): acceptable for synthetic data only (plan §0.5.2).
* One ASI:One address links to one person; one person links to one address.
* Links live in the users DB (`links`, `link_codes`); partner documents are not changed.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any, Optional

from doorstep.demo import seed
from doorstep.models import utc_now_iso
from doorstep.models.registry import ResidentProfile, Volunteer

from .errors import Conflict, NotFound

if TYPE_CHECKING:  # pragma: no cover
    from .engine import DoorstepService

ROLES = ("RESIDENT", "VOLUNTEER", "COORDINATOR")
SELF_REGISTERED_LABEL = "SELF-REGISTERED (demo)"


def _strip(doc: Optional[dict]) -> dict:
    return {k: v for k, v in (doc or {}).items() if not k.startswith("_")}


class LinkService:
    def __init__(self, engine: "DoorstepService"):
        self.engine = engine
        self.db = engine.db
        self.store = engine.store
        self.events = engine.events

    # ------------------------------------------------------------- seeding
    def seed_codes(self) -> None:
        for code, entry in seed.LINK_CODES.items():
            self.db.coll("link_codes").update_one(
                {"_id": code}, {"$set": {**entry, "code": code, "source": "SEED", "spent_by": None}}, upsert=True)

    # ------------------------------------------------------------- lookups
    def by_address(self, address: Optional[str]) -> Optional[dict[str, Any]]:
        d = self.db.coll("links").find_one({"_id": address}) if address else None
        return _strip(d) if d else None

    def for_person(self, role: str, person_id: str) -> Optional[dict[str, Any]]:
        d = self.db.coll("links").find_one({"role": role, "person_id": person_id})
        return _strip(d) if d else None

    def contact(self, role: str, person_id: str) -> dict[str, Any]:
        """Contact view: never returns the address itself to GET callers."""
        link = self.for_person(role, person_id)
        if link:
            return {"channel": "ASI_ONE", "linked": True, "linked_at": link["linked_at"]}
        return {"channel": "SIM", "linked": False, "linked_at": None}

    def reachability(self, role: str, person_id: str, phone: Optional[str]) -> str:
        if self.for_person(role, person_id):
            return "LINKED_ASI_ONE"
        return "SIM_ONLY" if phone else "NOT_REACHABLE"

    # --------------------------------------------------------------- link
    def link(self, code: str, address: str, correlation_id: str = "") -> dict[str, Any]:
        code = (code or "").strip().upper()
        address = (address or "").strip()
        if not address:
            raise Conflict("asi_one_address is required", code="VALIDATION_ERROR")
        entry = self.db.coll("link_codes").find_one({"_id": code})
        if entry is None:
            raise Conflict("Unknown link code", code="UNKNOWN_CODE")
        if entry.get("spent_by"):
            raise Conflict("Link code already used", code="CODE_SPENT")
        role = entry["role"]
        person_id = entry.get("resident_id") or entry.get("volunteer_id") or entry.get("coordinator_id")
        self._check_free(address, role, person_id)
        with self.db.tx():
            # Spend atomically: a concurrent second use finds spent_by set and fails.
            res = self.db.coll("link_codes").update_one({"_id": code, "spent_by": None},
                                                        {"$set": {"spent_by": address, "spent_at": utc_now_iso()}})
            if res.modified_count != 1:
                raise Conflict("Link code already used", code="CODE_SPENT")
            view = self._save_link(address, role, person_id, entry, via="CODE")
        self.events.append("ASI_ONE_LINKED", case_id=view.get("case_id"), correlation_id=correlation_id,
                           data={"role": role, "person_id": person_id, "via": "CODE"})
        return view

    def _check_free(self, address: str, role: str, person_id: str) -> None:
        if self.db.coll("links").find_one({"_id": address}):
            raise Conflict("This ASI:One account is already linked; send UNLINK first", code="ADDRESS_ALREADY_LINKED")
        if self.for_person(role, person_id):
            raise Conflict("This person is already linked to another ASI:One account", code="PERSON_ALREADY_LINKED")

    def _save_link(self, address: str, role: str, person_id: str, entry: dict[str, Any], via: str) -> dict[str, Any]:
        view = {"role": role, "display_name": entry.get("display_name") or person_id}
        if role == "RESIDENT":
            view |= {"resident_id": person_id, "case_id": entry.get("case_id") or self._case_id(person_id)}
        elif role == "VOLUNTEER":
            view |= {"volunteer_id": person_id, "org_id": entry.get("org_id")}
        else:
            view |= {"coordinator_id": person_id}
        doc = {"_id": address, "address": address, "person_id": person_id, "linked_at": utc_now_iso(),
               "via": via, **view}
        self.db.coll("links").replace_one({"_id": address}, doc, upsert=True)
        return {"schema_version": "2.0", "asi_one_address": address, **view, "linked_at": doc["linked_at"]}

    @staticmethod
    def _case_id(resident_id: str) -> str:
        return seed.CASE_IDS.get(resident_id, f"case_{resident_id}")

    def unlink(self, address: str, correlation_id: str = "") -> dict[str, Any]:
        link = self.by_address(address)
        if not link:
            raise NotFound("This ASI:One account is not linked")
        self.db.coll("links").delete_one({"_id": address})
        self.events.append("ASI_ONE_UNLINKED", case_id=link.get("case_id"), correlation_id=correlation_id,
                           data={"role": link["role"], "person_id": link["person_id"]})
        return {"schema_version": "2.0", "unlinked": True, "role": link["role"]}

    # -------------------------------------------------------------- invites
    def invite(self, org_id: str, volunteer_id: str, display_name: Optional[str] = None,
               correlation_id: str = "") -> dict[str, Any]:
        found = self.store.partners.locate_volunteer(volunteer_id)
        if found is None:
            raise NotFound(f"Volunteer {volunteer_id!r} not found")
        if found[1].org_id != org_id:
            raise Conflict("Volunteer does not belong to this organization", code="WRONG_ORG")
        prefix = (org_id.split("_")[0].upper()[:12]) or "ORG"
        for _ in range(50):
            code = f"{prefix}-{secrets.randbelow(9000) + 1000}"
            if not self.db.coll("link_codes").find_one({"_id": code}):
                break
        else:  # pragma: no cover
            raise Conflict("Could not issue a unique code", code="CODE_SPACE_EXHAUSTED")
        entry = {"role": "VOLUNTEER", "volunteer_id": volunteer_id, "org_id": org_id,
                 "display_name": display_name or found[2].name}
        self.db.coll("link_codes").insert_one({"_id": code, **entry, "code": code, "source": "INVITE",
                                               "spent_by": None, "issued_at": utc_now_iso()})
        self.events.append("VOLUNTEER_INVITE_ISSUED", case_id=None, correlation_id=correlation_id,
                           data={"org_id": org_id, "volunteer_id": volunteer_id})
        return {"schema_version": "2.0", "code": code, **entry}

    # ------------------------------------------------------------- register
    def register(self, role: str, address: str, profile: dict[str, Any], org_id: Optional[str],
                 correlation_id: str = "") -> dict[str, Any]:
        role = (role or "").upper()
        if role not in ("RESIDENT", "VOLUNTEER"):
            raise Conflict("role must be RESIDENT or VOLUNTEER", code="VALIDATION_ERROR")
        if not address:
            raise Conflict("asi_one_address is required", code="VALIDATION_ERROR")
        if self.db.coll("links").find_one({"_id": address}):
            raise Conflict("This ASI:One account is already linked; send UNLINK first", code="ADDRESS_ALREADY_LINKED")
        if role == "RESIDENT":
            return self._register_resident(address, profile, correlation_id)
        return self._register_volunteer(address, profile, org_id, correlation_id)

    def _register_resident(self, address: str, profile: dict[str, Any], corr: str) -> dict[str, Any]:
        data = {k: v for k, v in profile.items() if k != "resident_id"}
        addr = dict(data.get("address") or {})
        addr["label"] = SELF_REGISTERED_LABEL  # never store the typed street address (plan rev 5)
        data["address"] = addr
        data.setdefault("phone", f"asi_one_{secrets.token_hex(4)}")  # placeholder; contact is the ASI:One link
        try:
            resident = ResidentProfile.model_validate(data)
        except ValueError as err:
            raise Conflict(f"Invalid resident profile: {err.__class__.__name__}", code="VALIDATION_ERROR")
        out = self.engine.registry.register_resident(resident, corr)
        rid = out["resident_id"]
        view = self._save_link(address, "RESIDENT", rid, {"display_name": resident.name}, via="REGISTER")
        self.events.append("ASI_ONE_LINKED", case_id=view["case_id"], correlation_id=corr,
                           data={"role": "RESIDENT", "person_id": rid, "via": "REGISTER"})
        return {**view, "zone_status": out["zone_status"]}

    def _register_volunteer(self, address: str, profile: dict[str, Any], org_id: Optional[str],
                            corr: str) -> dict[str, Any]:
        partners = self.store.partners
        org = partners.find_org(org_id or "")
        if org is None:
            raise NotFound(f"Organization {org_id!r} not found")
        if not org.approved:
            raise Conflict("Organization is not approved", code="ORG_NOT_APPROVED")
        vid = f"volunteer_self_{self.db.next_seq('volunteer_self'):03d}"
        data = {**{k: v for k, v in profile.items() if k not in ("volunteer_id", "approved")},
                "volunteer_id": vid, "approved": False}  # never matched until the org approves
        data.setdefault("phone", f"asi_one_{secrets.token_hex(4)}")
        try:
            volunteer = Volunteer.model_validate(data)
        except ValueError as err:
            raise Conflict(f"Invalid volunteer profile: {err.__class__.__name__}", code="VALIDATION_ERROR")
        region = partners.region_for_point(volunteer.location.lat, volunteer.location.lon)
        if region is None:
            raise Conflict("No partner region covers this location", code="NO_REGION", reasons=["NO_REGION"])
        if org_id not in {o.org_id for o in region.orgs}:
            self.engine.registry.add_presence(region.region_id, org_id, corr)
        self.engine.registry.add_volunteer(region.region_id, org_id, volunteer, corr)
        view = self._save_link(address, "VOLUNTEER", vid, {"display_name": volunteer.name, "org_id": org_id},
                               via="REGISTER")
        self.events.append("ASI_ONE_LINKED", case_id=None, correlation_id=corr,
                           data={"role": "VOLUNTEER", "person_id": vid, "via": "REGISTER"})
        return {**view, "region_id": region.region_id, "approved": False}

    # -------------------------------------------------------------- approve
    def approve_volunteer(self, org_id: str, volunteer_id: str, approved: bool = True,
                          correlation_id: str = "") -> dict[str, Any]:
        partners = self.store.partners
        found = partners.locate_volunteer(volunteer_id)
        if found is None:
            raise NotFound(f"Volunteer {volunteer_id!r} not found")
        region, entry, _ = found
        if entry.org_id != org_id:
            raise Conflict("Volunteer does not belong to this organization", code="WRONG_ORG")

        def fn(r):
            e = next(o for o in r.orgs if o.org_id == org_id)
            v = next(x for x in e.volunteers if x.volunteer_id == volunteer_id)
            changed = v.approved != approved
            v.approved = approved
            return changed, changed
        changed = partners.mutate_region(region.region_id, fn)
        self.events.append("VOLUNTEER_APPROVED" if approved else "VOLUNTEER_APPROVAL_REVOKED", case_id=None,
                           correlation_id=correlation_id, data={"org_id": org_id, "volunteer_id": volunteer_id})
        return {"schema_version": "2.0", "org_id": org_id, "volunteer_id": volunteer_id, "approved": approved,
                "changed": bool(changed)}

    def pending_volunteers(self, org_id: Optional[str] = None) -> list[dict[str, Any]]:
        out = []
        for region in self.store.partners.list_regions():
            for e in region.orgs:
                if org_id and e.org_id != org_id:
                    continue
                for v in e.volunteers:
                    if not v.approved:
                        out.append({"org_id": e.org_id, "region_id": region.region_id, "volunteer_id": v.volunteer_id,
                                    "name": v.name, "vehicle_type": v.vehicle_type,
                                    "needs_they_can_cater": v.needs_they_can_cater,
                                    "linked": bool(self.for_person("VOLUNTEER", v.volunteer_id))})
        return out

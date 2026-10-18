"""Self-registration in ASI:One (team plan rev 5). DOORSTEP DEMO.

Unlinked person -> form card (resident or volunteer) -> address geocoded with HERE ->
confirm card -> B registers and links the sender's ASI:One address (envelope sender,
never typed text). Nothing is stored before Confirm; the typed address is kept only in
memory until then and never logged. Self-registered volunteers start unapproved and are
never matched until their organization approves them (B's rule).
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from doorstep.agents.links import Link, link_from_backend
from doorstep.integrations.asi_cards import SIM_PREFIX, Card, _footer, _row, _rows_text
from doorstep.integrations.geocoder import Geocoder, GeocodeResult
from doorstep.workflows.backend_v2 import BackendError, DoorstepBackendV2

NEEDS = {1: "Wheelchair-accessible vehicle", 2: "Help getting in (transfer)", 3: "Oxygen equipment",
         4: "Pet", 5: "Service animal", 6: "Step-free destination", 7: "Spanish speaker",
         8: "Mobility aid (walker, cane)", 9: "Medical equipment space", 10: "Caregiver rides along"}
VEHICLES = ["WHEELCHAIR_VAN", "MINIVAN", "SEDAN", "SUV", "BUS"]
ADDRESS_HINT = "Address (DEMO: use a fictional or public-place address)"


def truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "on", "yes", "1", "checked")


def _int(v: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return default


@dataclass
class Pending:
    role: str
    form: dict[str, Any]
    geo: GeocodeResult
    extras: dict[str, Any] = field(default_factory=dict)


def choice_card() -> Card:
    rows = [_row("New here?", "Register yourself before a disaster, or link an existing demo record with a code."),
            _footer(None, "Doorstep registration")]
    payload = {"title": f"{SIM_PREFIX} · Register", "summary_rows": rows,
               "ctas": [{"label": "Register as resident", "primary": True,
                         "selection": {"action": "register_start", "role": "RESIDENT"}},
                        {"label": "Register as volunteer", "selection": {"action": "register_start", "role": "VOLUNTEER"}}]}
    return Card("detail", payload, "Reply 'register as resident' or 'register as volunteer', or LINK <code>.")


def resident_form(error: str = "") -> Card:
    fields = [{"name": "name", "kind": "text", "label": "Name (a nickname is fine)", "required": True},
              {"name": "language", "kind": "select", "label": "Preferred language (for check-ins)",
               "options": [{"value": "en", "label": "English"}, {"value": "es", "label": "Español"}]},
              {"name": "address", "kind": "text", "label": ADDRESS_HINT, "required": True}]
    fields += [{"name": f"need_{c}", "kind": "checkbox", "label": label} for c, label in NEEDS.items()]
    fields += [{"name": "pet_count", "kind": "number", "label": "Number of pets"},
               {"name": "consent_checkin", "kind": "checkbox", "label": "Contact me with check-ins during a disaster"},
               {"name": "consent_transport", "kind": "checkbox", "label": "Share my transport needs with a volunteer"},
               {"name": "consent_destination", "kind": "checkbox", "label": "Share my needs with a shelter"}]
    payload = {"title": f"{SIM_PREFIX} · Register as resident", "fields": fields,
               "submit_cta": {"label": "Continue", "selection": {"action": "register_submit", "role": "RESIDENT"}}}
    return Card("form", payload, (f"{error} " if error else "") + "Fill in the resident registration form.")


def volunteer_form(orgs: list[dict[str, Any]], error: str = "") -> Card:
    fields = [{"name": "name", "kind": "text", "label": "Name (a nickname is fine)", "required": True},
              {"name": "org_id", "kind": "select", "label": "Organization",
               "options": [{"value": o["org_id"], "label": o.get("name", o["org_id"])} for o in orgs]
               or [{"value": "", "label": "No organizations available"}]},
              {"name": "address", "kind": "text", "label": ADDRESS_HINT, "required": True},
              {"name": "vehicle_type", "kind": "select", "label": "Vehicle",
               "options": [{"value": v, "label": v.replace("_", " ").title()} for v in VEHICLES]},
              {"name": "vehicle_seats", "kind": "number", "label": "Free seats"},
              {"name": "wheelchair_spaces", "kind": "number", "label": "Wheelchair spaces"},
              {"name": "pet_capacity", "kind": "number", "label": "Pets you can take"}]
    fields += [{"name": f"can_{c}", "kind": "checkbox", "label": f"I can handle: {label}"} for c, label in NEEDS.items()]
    payload = {"title": f"{SIM_PREFIX} · Register as volunteer", "fields": fields,
               "submit_cta": {"label": "Continue", "selection": {"action": "register_submit", "role": "VOLUNTEER"}}}
    return Card("form", payload, (f"{error} " if error else "") + "Fill in the volunteer registration form.")


def confirm_card(p: Pending) -> Card:
    rows = [_row("Role", p.role.title()), _row("Name", p.form.get("name")),
            _row("We found", p.geo.label), _row("Coordinates", f"{p.geo.lat:.3f}, {p.geo.lon:.3f} (rounded)")]
    if p.role == "RESIDENT":
        rows.append(_row("Needs", ", ".join(NEEDS[c] for c in p.extras["needs"]) or "none"))
    else:
        rows += [_row("Organization", p.extras["org_id"]),
                 _row("Note", "You can't be matched until your organization approves you.")]
    rows += [_row("Privacy", "Only the coordinates are stored, not the address text."),
             _footer(None, "HERE geocoding · Doorstep registration")]
    payload = {"title": f"{SIM_PREFIX} · Confirm registration", "summary_rows": rows,
               "approve_cta": {"label": "Confirm", "primary": True, "selection": {"action": "register_confirm"}},
               "reject_cta": {"label": "Change", "selection": {"action": "register_start", "role": p.role}}}
    return Card("review", payload, "Is this the right place? Reply 'confirm' or press Change." + chr(10) + _rows_text(rows))


class Registration:
    def __init__(self, get_backend: Callable[[], DoorstepBackendV2], geocoder: Geocoder | None = None):
        self.get_backend = get_backend
        self.geocoder = geocoder or Geocoder()
        self.pending: dict[str, Pending] = {}

    async def transport_orgs(self, corr: str) -> list[dict[str, Any]]:
        try:
            res = await self.get_backend()._request("GET", "/organizations", corr)
        except (BackendError, OSError):
            return []
        return [o for o in res.get("organizations", []) if o.get("approved") and "TRANSPORT" in o.get("services", [])]

    async def start(self, role: str, corr: str) -> Card:
        return volunteer_form(await self.transport_orgs(corr)) if role == "VOLUNTEER" else resident_form()

    async def submit(self, sender: str, sel: dict[str, Any], corr: str) -> Card | str:
        role = sel.get("role", "RESIDENT")
        retry = (lambda e: volunteer_form([], e)) if role == "VOLUNTEER" else resident_form
        if not str(sel.get("name", "")).strip() or not str(sel.get("address", "")).strip():
            return retry("Name and address are required.")
        geo = await self.geocoder.geocode(str(sel["address"]))
        if geo.confidence != "HIGH":
            msg = {"FAILED": "I couldn't find that address.",
                   "LOW": "That address is too vague or ambiguous; please add a house number, street and city."}
            return retry(f"{msg.get(geo.confidence, '')} ({geo.reason})")
        if role == "VOLUNTEER":
            extras = {"org_id": sel.get("org_id"), "caps": [c for c in NEEDS if truthy(sel.get(f"can_{c}"))]}
            if not extras["org_id"]:
                return volunteer_form(await self.transport_orgs(corr), "Please choose your organization.")
        else:
            extras = {"needs": [c for c in NEEDS if truthy(sel.get(f"need_{c}"))]}
        form = {k: v for k, v in sel.items() if k != "address"}  # the address text is dropped here
        self.pending[sender] = Pending(role, form, geo, extras)
        return confirm_card(self.pending[sender])

    async def confirm(self, sender: str, corr: str) -> tuple[Link | None, str]:
        p = self.pending.get(sender)
        if p is None:
            return None, "There is no registration waiting for confirmation."
        f, phone = p.form, f"asi_one:{sender}"
        address = {"label": "SELF-REGISTERED (demo)", "lat": p.geo.lat, "lon": p.geo.lon, "geocode_confidence": "HIGH"}
        if p.role == "RESIDENT":
            profile = {"name": str(f["name"]).strip(), "phone": phone, "language": f.get("language") or "en",
                       "address": address, "needs": p.extras["needs"], "pet_count": _int(f.get("pet_count")),
                       "wants_help_contact": truthy(f.get("consent_checkin")),
                       "consents": {"CHECKIN": truthy(f.get("consent_checkin")),
                                    "TRANSPORT": truthy(f.get("consent_transport")),
                                    "DESTINATION": truthy(f.get("consent_destination")), "RECOVERY": False}}
            org_id = None
        else:
            profile = {"name": str(f["name"]).strip(), "phone": phone,
                       "location": {"type": "Point", "coordinates": [p.geo.lon, p.geo.lat]},
                       "vehicle_type": f.get("vehicle_type") or "SEDAN", "vehicle_seats": _int(f.get("vehicle_seats"), 1),
                       "wheelchair_spaces": _int(f.get("wheelchair_spaces")), "pet_capacity": _int(f.get("pet_capacity")),
                       "needs_they_can_cater": p.extras["caps"], "approved": False}
            org_id = p.extras["org_id"]
        try:
            res = await self.get_backend().register(p.role, sender, profile, org_id, corr)
            link = link_from_backend(sender, res)
        except BackendError as err:
            return None, f"Registration was refused ({err.code}: {err.detail}). Nothing was stored."
        except (OSError, ValueError):
            return None, "Registration is unavailable right now. Nothing was stored."
        if p.role == "RESIDENT":
            link.language = f.get("language") or "en"  # the check-in card speaks it
        del self.pending[sender]
        return link, ""

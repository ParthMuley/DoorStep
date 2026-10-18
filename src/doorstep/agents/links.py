"""Linked ASI:One accounts (team plan rev 4 §0.1, §0.5). DOORSTEP DEMO.

The sender address always comes from the ASI:One message envelope (the `sender` the
Doorstep agent receives), never from text the user typed. B is the authority (`POST
/link` spends a one-time code and returns the person); this registry only remembers the
result so the Doorstep agent can route cards and check roles. It is persisted in the
agent's storage so a restart doesn't unlink anyone.
"""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

ROLES = ("RESIDENT", "VOLUNTEER", "COORDINATOR")
LINK_TEXT = re.compile(r"^\s*link\s+([A-Za-z0-9-]{4,32})\s*$", re.IGNORECASE)


@dataclass
class Link:
    address: str
    role: str
    person_id: str
    display_name: str = ""
    case_id: str | None = None        # residents
    volunteer_id: str | None = None   # volunteers
    org_id: str | None = None         # volunteers
    backend_sender: str | None = None  # what B accepts as `sender` for this person's answers


MENTION = re.compile(r"^\s*(?:@\S+\s*)+")  # ASI:One prefixes messages with "@agent1q..." mentions


def link_code_from_text(text: str) -> str | None:
    m = LINK_TEXT.match(MENTION.sub("", text))
    return m.group(1).upper() if m else None


def link_from_backend(address: str, res: dict[str, Any]) -> Link:
    role = str(res.get("role", "")).upper()
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    person = res.get("resident_id") or res.get("volunteer_id") or res.get("coordinator_id") or ""
    return Link(address=address, role=role, person_id=person, display_name=res.get("display_name", person),
                case_id=res.get("case_id"), volunteer_id=res.get("volunteer_id"), org_id=res.get("org_id"),
                backend_sender=res.get("sender_for_backend") or address)


class LinkRegistry:
    def __init__(self):
        self._by_address: dict[str, Link] = {}

    def get(self, ctx: Any, address: str) -> Link | None:
        if address in self._by_address:
            return self._by_address[address]
        raw = ctx.storage.get(f"link:{address}") if ctx is not None else None
        if raw:
            self._by_address[address] = Link(**json.loads(raw))
        return self._by_address.get(address)

    def put(self, ctx: Any, link: Link) -> None:
        self._by_address[link.address] = link
        if ctx is not None:
            ctx.storage.set(f"link:{link.address}", json.dumps(asdict(link)))

    def remove(self, ctx: Any, address: str) -> bool:
        """Demo control: forget this chat's link locally (B's record is unchanged)."""
        existed = self._by_address.pop(address, None) is not None
        if ctx is not None and ctx.storage.get(f"link:{address}"):
            ctx.storage.remove(f"link:{address}")
            existed = True
        return existed

    def all(self) -> list[Link]:
        return list(self._by_address.values())

    def by_role(self, role: str) -> list[Link]:
        return [link for link in self._by_address.values() if link.role == role]

    def resident_for_case(self, case_id: str) -> Link | None:
        return next((l for l in self._by_address.values() if l.role == "RESIDENT" and l.case_id == case_id), None)

    def volunteer(self, volunteer_id: str) -> Link | None:
        return next((l for l in self._by_address.values()
                     if l.role == "VOLUNTEER" and l.volunteer_id == volunteer_id), None)

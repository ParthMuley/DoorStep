"""Bulk volunteer roster import for an organization. DOORSTEP DEMO, synthetic people only.

An org uploads its vetted roster as CSV -> each row becomes a volunteer in B's location-first
DB (region -> org -> volunteers) via B's real `POST /regions/{region}/orgs/{org}/volunteers`
-> each volunteer gets a one-time invite code (`POST /organizations/{org}/invites`, a dev
stand-in until B ships it) to type as `LINK <code>` in their own ASI:One chat.

Imported volunteers are approved by default (the org vouches for its own roster); a row can
set `approved=no`. Rows are validated before anything is sent; a bad row never stops the
others, and an existing volunteer is reported, not overwritten.

CSV columns: volunteer_id, name, lat, lon, vehicle_type, vehicle_seats, wheelchair_spaces,
pet_capacity, needs_they_can_cater (codes 1-10 separated by ';'), approved (optional).
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Any

import httpx

REQUIRED = ("volunteer_id", "name", "lat", "lon")


@dataclass
class RowResult:
    line: int
    volunteer_id: str
    status: str  # IMPORTED | EXISTS | INVALID | REFUSED
    detail: str = ""
    invite_code: str | None = None
    volunteer: dict[str, Any] = field(default_factory=dict)


def _yes(v: str | None, default: bool = True) -> bool:
    return default if v is None or not v.strip() else v.strip().lower() in ("yes", "y", "true", "1")


def parse_row(row: dict[str, str]) -> dict[str, Any]:
    """CSV row -> B's Volunteer shape. Raises ValueError with a readable reason."""
    missing = [c for c in REQUIRED if not (row.get(c) or "").strip()]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    lat, lon = float(row["lat"]), float(row["lon"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat/lon out of range")
    caps = [int(c) for c in (row.get("needs_they_can_cater") or "").replace(",", ";").split(";") if c.strip()]
    if any(not 1 <= c <= 10 for c in caps):
        raise ValueError("needs codes must be 1-10")
    vid = row["volunteer_id"].strip()
    return {"volunteer_id": vid, "name": row["name"].strip(), "phone": f"sim_phone_{vid}",
            "location": {"type": "Point", "coordinates": [lon, lat]},
            "vehicle_type": (row.get("vehicle_type") or "SEDAN").strip().upper(),
            "vehicle_seats": int(row.get("vehicle_seats") or 1), "wheelchair_spaces": int(row.get("wheelchair_spaces") or 0),
            "pet_capacity": int(row.get("pet_capacity") or 0), "needs_they_can_cater": sorted(set(caps)),
            "approved": _yes(row.get("approved")), "simulated": True}


async def import_roster(client: httpx.AsyncClient, org_id: str, region_id: str, csv_text: str,
                        token: str, correlation_id: str = "roster_import") -> list[RowResult]:
    headers = {"Authorization": f"Bearer {token}", "X-Correlation-ID": correlation_id}
    out: list[RowResult] = []
    for line, row in enumerate(csv.DictReader(io.StringIO(csv_text)), start=2):  # line 1 is the header
        vid = (row.get("volunteer_id") or "").strip() or f"(line {line})"
        try:
            volunteer = parse_row(row)
        except (ValueError, TypeError) as err:
            out.append(RowResult(line, vid, "INVALID", str(err)))
            continue
        res = await client.post(f"/regions/{region_id}/orgs/{org_id}/volunteers", headers=headers,
                                json={"volunteer": volunteer})
        if res.status_code == 409:
            out.append(RowResult(line, vid, "EXISTS", "already on the roster; not changed", volunteer=volunteer))
            continue
        if res.status_code >= 400:
            out.append(RowResult(line, vid, "REFUSED", f"{res.status_code} {res.text[:160]}", volunteer=volunteer))
            continue
        inv = await client.post(f"/organizations/{org_id}/invites", headers=headers,
                                json={"volunteer_id": vid, "display_name": volunteer["name"]})
        code = inv.json().get("code") if inv.status_code < 400 else None
        out.append(RowResult(line, vid, "IMPORTED", "" if code else f"no invite ({inv.status_code})", code, volunteer))
    return out

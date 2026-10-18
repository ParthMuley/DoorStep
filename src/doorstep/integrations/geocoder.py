"""HERE Geocoding (`/v1/geocode`) for self-registration (team plan rev 5). DOORSTEP DEMO.

Rules:
- HIGH only when the top result is a house number or street, its `scoring.queryScore`
  is >= 0.9, and there's no near-tie with a second result; otherwise LOW (ask the person
  to rephrase; nothing is registered) or FAILED (no result).
- The address text is never logged. Only coordinates + confidence leave this module
  for storage; HERE's label is shown back to the person once, to confirm.
- Free tier: a daily cap (HERE_MAX_GEOCODES_PER_DAY, default 50); past it -> FAILED.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

GEOCODE_URL = "https://geocode.search.hereapi.com/v1/geocode"
PRECISE_TYPES = {"houseNumber", "street"}
MIN_SCORE = 0.9
TIE_MARGIN = 0.05


@dataclass
class GeocodeResult:
    confidence: str  # HIGH | LOW | FAILED
    lat: float | None = None
    lon: float | None = None
    label: str | None = None  # HERE's label, shown once for confirmation; never logged or stored
    reason: str = ""


def classify(items: list[dict[str, Any]]) -> GeocodeResult:
    if not items:
        return GeocodeResult("FAILED", reason="NO_RESULT")
    top = items[0]
    score = float((top.get("scoring") or {}).get("queryScore", 0))
    pos = top.get("position") or {}
    result = GeocodeResult("LOW", pos.get("lat"), pos.get("lng"), top.get("title"))
    if top.get("resultType") not in PRECISE_TYPES:
        result.reason = f"NOT_PRECISE:{top.get('resultType')}"
    elif score < MIN_SCORE:
        result.reason = f"LOW_SCORE:{score:.2f}"
    elif len(items) > 1 and float((items[1].get("scoring") or {}).get("queryScore", 0)) >= score - TIE_MARGIN:
        result.reason = "AMBIGUOUS"
    else:
        result.confidence = "HIGH"
    return result


class Geocoder:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("HERE_API_KEY", "").strip()
        self._transport = transport
        self._calls: dict[str, int] = {}

    def _budget_ok(self) -> bool:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._calls.get(day, 0) >= int(os.getenv("HERE_MAX_GEOCODES_PER_DAY", "50")):
            return False
        self._calls[day] = self._calls.get(day, 0) + 1
        return True

    async def geocode(self, address: str) -> GeocodeResult:
        if not self.api_key:
            return GeocodeResult("FAILED", reason="HERE_NOT_CONFIGURED")
        if not address.strip():
            return GeocodeResult("FAILED", reason="EMPTY_ADDRESS")
        if not self._budget_ok():
            return GeocodeResult("FAILED", reason="HERE_DAILY_CAP_REACHED")
        params = {"q": address, "in": "countryCode:USA", "limit": 2, "lang": "en-US", "apiKey": self.api_key}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=15) as client:
                resp = await client.get(GEOCODE_URL, params=params)
        except httpx.HTTPError:
            return GeocodeResult("FAILED", reason="HERE_UNREACHABLE")
        if resp.status_code != 200:
            return GeocodeResult("FAILED", reason=f"HERE_HTTP_{resp.status_code}")
        return classify(resp.json().get("items") or [])

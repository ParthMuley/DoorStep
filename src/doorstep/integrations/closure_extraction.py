"""Extract the *claim* a news item makes about a road (ASI:One structured tool output,
with a deterministic keyword fallback). DOORSTEP DEMO.

This never decides whether a report is true or official: the News agent only sends a
candidate `{road_name, claimed_status, location_text}` with an honest source type, and
Developer B's deterministic rules set the closure state (only OFFICIAL_SIMULATION
sources can become OFFICIAL_CONFIRMED and block routes).
"""

import json
import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI

from doorstep.integrations.asi_one_client import ASI_ONE_BASE_URL, DEFAULT_MODEL, TIMEOUT_SECONDS

log = logging.getLogger("doorstep.closure_extraction")

STATUSES = ["CLOSED", "OPEN", "RESTRICTED", "UNCLEAR"]
EXTRACT_TOOL = {"type": "function", "function": {
    "name": "report_road_claim",
    "description": "Record what the article CLAIMS about a road, if anything. Do not judge whether it is true.",
    "parameters": {"type": "object", "properties": {
        "mentions_road": {"type": "boolean"},
        "road_name": {"type": "string", "description": "Road name exactly as written; empty if none"},
        "claimed_status": {"type": "string", "enum": STATUSES},
        "location_text": {"type": "string", "description": "Where, as written; empty if not stated"}},
        "required": ["mentions_road", "road_name", "claimed_status", "location_text"]}}}
SYSTEM_PROMPT = ("You extract claims from DOORSTEP DEMO news items about roads. Report only what the text claims. "
                 "Never decide whether it is true, official, or safe.")

ROAD = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)* (?:Rd|Road|Ave|Avenue|St|Street|Blvd|Hwy|Highway|Dr|Drive|Way|Ln))\b")
CLOSED_WORDS = ("closed", "blocked", "shut", "impassable", "debris", "fallen tree", "flooded")
OPEN_WORDS = ("reopened", "re-opened", "open again", "is open", "cleared")


def extraction_enabled() -> bool:
    return bool(os.getenv("ASI_ONE_API_KEY", "").strip()) and os.getenv("USE_LLM_EXTRACTION", "true").lower() == "true"


def keyword_candidate(text: str) -> dict[str, Any] | None:
    """Deterministic fallback: first road-like name + simple status words."""
    match = ROAD.search(text)
    if not match:
        return None
    lowered = text.lower()
    status = ("OPEN" if any(w in lowered for w in OPEN_WORDS)
              else "CLOSED" if any(w in lowered for w in CLOSED_WORDS) else "UNCLEAR")
    return {"road_name": match.group(1), "claimed_status": status, "location_text": ""}


def _valid(args: dict[str, Any]) -> dict[str, Any] | None:
    if not args.get("mentions_road") or not str(args.get("road_name", "")).strip():
        return None
    if args.get("claimed_status") not in STATUSES:
        return None
    return {"road_name": args["road_name"].strip(), "claimed_status": args["claimed_status"],
            "location_text": str(args.get("location_text", "")).strip()}


class ClosureExtractor:
    def __init__(self, client: Any | None = None, model: str | None = None):
        self._client = client
        self._model = model or os.getenv("ASI_ONE_MODEL", DEFAULT_MODEL)

    def _llm(self):
        if self._client is None and extraction_enabled():
            self._client = AsyncOpenAI(base_url=ASI_ONE_BASE_URL, api_key=os.getenv("ASI_ONE_API_KEY"),
                                       timeout=TIMEOUT_SECONDS, max_retries=0)
        return self._client

    async def extract(self, text: str) -> tuple[dict[str, Any] | None, str]:
        """Returns (candidate or None, extraction_method)."""
        client = self._llm()
        if client is not None:
            try:
                resp = await client.chat.completions.create(
                    model=self._model, temperature=0, tools=[EXTRACT_TOOL],
                    tool_choice={"type": "function", "function": {"name": "report_road_claim"}},
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}])
                calls = resp.choices[0].message.tool_calls or []
                if len(calls) == 1 and calls[0].function.name == "report_road_claim":
                    return _valid(json.loads(calls[0].function.arguments or "{}")), "ASI_ONE_EXTRACTION"
            except Exception as err:  # network/auth/malformed: fall back, never guess
                log.warning("ASI:One extraction unavailable (%s); using keyword fallback", type(err).__name__)
        return keyword_candidate(text), "KEYWORD_EXTRACTION"

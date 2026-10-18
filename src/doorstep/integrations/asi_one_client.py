"""ASI:One API intent: map an ASI:One chat message to ONE known coordinator tool.

The model only *chooses* a tool and its arguments (validated against an allow-list with
enums). It never writes the reply, and never decides eligibility, zones, consent or
status: every answer comes from the coordinator actions and Developer B's fields.
Any error, timeout, unknown tool or bad argument returns None so the caller falls back
to the deterministic keyword router.

Endpoint: OpenAI-compatible https://api.asi1.ai/v1 (models seen: asi1-mini, asi1, asi1-ultra).
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

log = logging.getLogger("doorstep.asi_one")

ASI_ONE_BASE_URL = "https://api.asi1.ai/v1"
DEFAULT_MODEL = "asi1-mini"
TIMEOUT_SECONDS = 8.0
RESIDENTS = ["maria", "david"]


@dataclass
class Intent:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    source: str = "KEYWORD"  # KEYWORD | ASI_ONE | CARD


def _tool(name: str, description: str, properties: dict[str, Any] | None = None,
          required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


_RESIDENT = {"resident": {"type": "string", "enum": RESIDENTS, "description": "Which fictional resident"}}

# Only tools the coordinator can actually run today. New tools are added as actions land.
TOOLS: list[dict[str, Any]] = [
    _tool("start_readiness_check", "Start the simulated Zone 3 readiness check (simulated official warning; "
          "sends simulated check-ins to enrolled residents)."),
    _tool("case_status", "Show the evidence-backed status card for one resident's case.", _RESIDENT, ["resident"]),
    _tool("show_suitable_volunteers", "Show suitable providers/volunteers for one resident and why each "
          "matches or is rejected (deterministic matching).", _RESIDENT, ["resident"]),
    _tool("test_push", "Developer check: send a delayed follow-up message to test unsolicited updates."),
    _tool("help", "Explain what this demo coordinator can do. Use when no other tool fits."),
]
ALLOWED = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}

SYSTEM_PROMPT = (
    "You route messages for DOORSTEP DEMO, a simulation that coordinates accessible transport for "
    "fictional residents. Call exactly one tool that matches the user's request. Never answer in text. "
    "If nothing fits, call `help`. Never invent residents: only maria or david."
)


def intent_enabled() -> bool:
    return os.getenv("USE_LLM_INTENT", "false").lower() == "true" and bool(os.getenv("ASI_ONE_API_KEY", "").strip())


def validate_intent(name: str, raw_args: str | None) -> Intent | None:
    params = ALLOWED.get(name)
    if params is None:
        return None
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None
    props = params["properties"]
    if set(args) - set(props) or any(r not in args for r in params["required"]):
        return None
    for key, value in args.items():
        allowed = props[key].get("enum")
        if allowed is not None and value not in allowed:
            return None
    return Intent(name, args, source="ASI_ONE")


class IntentClient:
    def __init__(self, client: Any | None = None, model: str | None = None):
        self._client = client or AsyncOpenAI(base_url=ASI_ONE_BASE_URL, api_key=os.getenv("ASI_ONE_API_KEY"),
                                             timeout=TIMEOUT_SECONDS, max_retries=0)
        self._model = model or os.getenv("ASI_ONE_MODEL", DEFAULT_MODEL)

    async def choose(self, text: str, correlation_id: str = "") -> Intent | None:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
                tools=TOOLS, tool_choice="auto", temperature=0)
            calls = resp.choices[0].message.tool_calls or []
        except Exception as err:  # network, auth, rate limit, malformed response
            log.warning("[%s] ASI:One intent unavailable (%s); using keyword fallback", correlation_id,
                        type(err).__name__)
            return None
        if len(calls) != 1:
            return None
        intent = validate_intent(calls[0].function.name, calls[0].function.arguments)
        log.info("[%s] ASI:One intent: %s", correlation_id, intent.name if intent else "rejected")
        return intent


def keyword_intent(text: str) -> Intent:
    """Deterministic fallback; always returns an intent (help when nothing matches)."""
    lowered = text.lower()
    resident = next((r for r in RESIDENTS if r in lowered), "maria")
    if "test push" in lowered:
        return Intent("test_push")
    if "provider" in lowered or "offer" in lowered or "volunteer" in lowered or "match" in lowered:
        return Intent("show_suitable_volunteers", {"resident": resident})
    if "start" in lowered and ("check" in lowered or "warning" in lowered):
        return Intent("start_readiness_check")
    if "status" in lowered:
        return Intent("case_status", {"resident": resident})
    return Intent("help")

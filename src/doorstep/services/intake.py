"""Deterministic parsing of resident replies (English + Spanish keywords).

Produces *candidate* needs only; nothing is used until the resident confirms.
The original text is always preserved alongside the parsed fields. An LLM
extractor can be plugged in later behind ``extract`` but must keep the
same confirm-before-use contract.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from doorstep.models import ResponseIntent


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", stripped.lower()).strip()


_INTENT_NUMBERS = {"1": ResponseIntent.NEED_HELP, "2": ResponseIntent.HAS_PLAN,
                   "3": ResponseIntent.ALREADY_LEFT, "4": ResponseIntent.CALL_ME}

_PICKUP_PHRASES = ["picked up", "pickup done", "recogido", "recogida", "ya me recogieron", "me recogieron"]

_INTENT_PHRASES = [
    (ResponseIntent.CALL_ME, ["call me", "llamame", "llamenme", "llamar"]),
    (ResponseIntent.ALREADY_LEFT, ["already left", "ya sali", "ya me fui", "ya me sali"]),
    (ResponseIntent.HAS_PLAN, ["have a plan", "tengo un plan", "i have a plan"]),
    (ResponseIntent.NEED_HELP, ["need help", "help", "necesito ayuda", "ayuda", "ayudenme"]),
]

_YES = {"yes", "y", "si", "correct", "correcto", "confirmo", "confirm"}
_NO = {"no", "n", "incorrect", "incorrecto"}

_NEED_PATTERNS = {
    "wheelchair_accessible_vehicle": [r"wheelchair", r"silla de ruedas"],
    "transfer_assistance": [r"help getting (in|into)", r"transfer", r"ayuda para subir", r"subir a(l| la)",
                            r"help me get in", r"\blift\b"],
    "portable_oxygen_equipment": [r"oxygen", r"oxigeno"],
    "service_animal": [r"service (dog|animal)", r"(perro|animal) de servicio"],
}
_PET_PATTERN = r"\b(dog|dogs|cat|cats|pet|pets|perr\w*|gat\w*|mascota\w*)\b"


@dataclass
class ParsedResponse:
    original_text: str
    language: str
    intent: ResponseIntent
    candidate_needs: dict = field(default_factory=dict)
    method: str = "deterministic_keywords"
    requires_confirmation: bool = True


def extract(text: str, language: str = "en") -> ParsedResponse:
    norm = normalize(text)
    words = set(re.findall(r"[a-z0-9]+", norm))

    candidates: dict = {}
    for key, patterns in _NEED_PATTERNS.items():
        if any(re.search(p, norm) for p in patterns):
            candidates[key] = True
    pet_hits = [m for m in re.findall(_PET_PATTERN, norm)]
    if pet_hits and not candidates.get("service_animal"):
        candidates["pet_count"] = 1
    if candidates:
        candidates["preferred_language"] = language

    intent = ResponseIntent.UNPARSED
    first = norm.split(" ")[0] if norm else ""
    first = re.sub(r"[^a-z0-9]", "", first)
    if any(re.search(rf"\b{re.escape(p)}\b", norm) for p in _PICKUP_PHRASES):
        intent = ResponseIntent.PICKUP_CONFIRMED
    elif first in _INTENT_NUMBERS:
        intent = _INTENT_NUMBERS[first]
    elif norm.rstrip(".!") in _YES or (words and words <= _YES):
        intent = ResponseIntent.CONFIRM_YES
    elif norm.rstrip(".!") in _NO:
        intent = ResponseIntent.CONFIRM_NO
    else:
        for candidate_intent, phrases in _INTENT_PHRASES:
            if any(re.search(rf"\b{re.escape(p)}\b", norm) for p in phrases):
                intent = candidate_intent
                break
        if intent == ResponseIntent.UNPARSED and candidates:
            # Describing transport needs implies a request for help.
            intent = ResponseIntent.NEED_HELP

    return ParsedResponse(original_text=text, language=language, intent=intent,
                          candidate_needs=candidates,
                          requires_confirmation=bool(candidates))

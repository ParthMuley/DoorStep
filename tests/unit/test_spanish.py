"""Spanish replies and templates (DOORSTEP DEMO). Review sheet: docs/spanish-review.md."""

import re

import pytest

from doorstep.models import ResponseIntent
from doorstep.services import templates
from doorstep.services.intake import extract


@pytest.mark.parametrize("text,intent", [
    ("1 NECESITO AYUDA", ResponseIntent.NEED_HELP),
    ("necesito ayuda", ResponseIntent.NEED_HELP),
    ("2 TENGO UN PLAN", ResponseIntent.HAS_PLAN),
    ("3 YA SALÍ", ResponseIntent.ALREADY_LEFT),
    ("ya sali", ResponseIntent.ALREADY_LEFT),
    ("4 LLÁMENME", ResponseIntent.CALL_ME),
    ("Llámeme por favor", ResponseIntent.CALL_ME),
    ("llámame", ResponseIntent.CALL_ME),
    ("SÍ", ResponseIntent.CONFIRM_YES),
    ("si", ResponseIntent.CONFIRM_YES),
    ("Sí, correcto", ResponseIntent.CONFIRM_YES),
    ("NO", ResponseIntent.CONFIRM_NO),
    ("RECOGIDO", ResponseIntent.PICKUP_CONFIRMED),
    ("Ya me recogieron", ResponseIntent.PICKUP_CONFIRMED),
])
def test_spanish_replies_understood(text, intent):
    assert extract(text, "es").intent == intent


def test_every_spanish_template_is_demo_labeled_and_fills():
    for tid, langs in templates.TEMPLATES.items():
        es = langs["es"]
        assert es.startswith("DOORSTEP DEMO") and "simulación" in es, tid
        # Same placeholders as the English version, so render() never breaks in one language.
        assert set(re.findall(r"{(\w+)}", es)) == set(re.findall(r"{(\w+)}", langs["en"])), tid


def test_spanish_never_promises_safety_or_dispatch():
    banned = ["seguro", "a salvo", "garantizado", "despachad", "ambulancia en camino"]
    for tid, langs in templates.TEMPLATES.items():
        low = langs["es"].lower()
        for word in banned:
            assert word not in low, (tid, word)

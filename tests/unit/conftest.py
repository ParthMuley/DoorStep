import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doorstep.demo import seed  # noqa: E402
from doorstep.models import Confirmation, Evidence  # noqa: E402
from doorstep.services.db import Database  # noqa: E402
from doorstep.services.engine import DoorstepService  # noqa: E402

MARIA = "case_maria_001"
DAVID = "case_david_002"
MARIA_PHONE = "sms:+15555550101"
DAVID_PHONE = "sms:+15555550102"
DAVID_CAREGIVER_PHONE = "sms:+15555550103"
TOKEN = "doorstep-local-demo-token"


@pytest.fixture
def svc() -> DoorstepService:
    service = DoorstepService(Database(":memory:"))
    service.reset()
    return service


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from doorstep.api.app import create_app

    app = create_app(":memory:", seed=True)
    return TestClient(app, headers={"X-Demo-Token": TOKEN})


def warn(svc):
    return svc.start_demo_warning(seed.DEMO_ZONE, seed.SCENARIO_A)


def maria_confirmed(svc) -> str:
    warn(svc)
    svc.submit_resident_response(MARIA, "Necesito ayuda, uso silla de ruedas y tengo un perro", "es",
                                 sender=MARIA_PHONE, external_id="m1")
    svc.submit_resident_response(MARIA, "Sí", "es", sender=MARIA_PHONE, external_id="m2")
    return MARIA


def eligible(result, provider_id=None):
    offers = [o for o in result["offers"] if o["eligible"]]
    if provider_id:
        offers = [o for o in offers if o["provider_id"] == provider_id]
    return offers[0]


def maria_proposed(svc):
    maria_confirmed(svc)
    t = svc.find_transport(MARIA)
    d = svc.find_destination(MARIA)
    ta = svc.propose_assignment(MARIA, eligible(t)["offer_id"])
    da = svc.propose_assignment(MARIA, eligible(d)["offer_id"])
    return ta, da


def maria_accepted(svc):
    ta, da = maria_proposed(svc)
    svc.respond_assignment(ta.assignment_id, ta.provider_id, True)
    svc.respond_assignment(da.assignment_id, da.provider_id, True)
    return svc.store.get_assignment(ta.assignment_id), svc.store.get_assignment(da.assignment_id)


def pickup_evidence(ta):
    return Evidence(confirmations=[Confirmation(party="transport_provider", party_id=ta.provider_id),
                                   Confirmation(party="resident", party_id="resident_001")])


def arrival_evidence(da):
    return Evidence(confirmations=[Confirmation(party="destination_provider", party_id=da.provider_id),
                                   Confirmation(party="resident", party_id="resident_001")])


def david_confirmed(svc) -> str:
    warn(svc)
    svc.submit_resident_response(DAVID, "1", "en", sender=DAVID_PHONE, external_id="d1")
    svc.submit_resident_response(DAVID, "yes", "en", sender=DAVID_PHONE, external_id="d2")
    return DAVID

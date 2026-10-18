import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doorstep.demo import seed  # noqa: E402
from doorstep.models import DestinationOfferIn, Evidence, TransportOfferIn  # noqa: E402
from doorstep.services.db import Database  # noqa: E402
from doorstep.services.engine import DoorstepService  # noqa: E402

MARIA = "case_maria_001"
DAVID = "case_david_002"
MARIA_SENDER = seed.MARIA_SENDER
DAVID_SENDER = seed.DAVID_SENDER
DAVID_CAREGIVER_SENDER = seed.DAVID_CAREGIVER_SENDER
TOKEN = "change-me-local-demo-token"
AGENT_TOKEN_ENV = ("DEMO_AUTH_TOKEN", "NETWORK_AGENT_TOKEN", "DOORSTEP_AGENT_TOKEN", "ROUTE_AGENT_TOKEN",
                   "CALAMITY_AGENT_TOKEN", "REPLY_DEADLINE_MINUTES", "PUBLIC_BASE_URL", "MAP_TTL_HOURS",
                   "ROUTE_MAX_AVOID_AREAS", "RENDER_EXTERNAL_URL", "MONGODB_USERS_DB",
                   "MONGODB_PARTNERS_DB", "MONGODB_ORGS_DB", "DEMO_DATASET", "OUTREACH_MAX_ORGS")


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    """A developer's .env must not change unit-test results (A's note, 2026-10-18)."""
    for name in AGENT_TOKEN_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def svc() -> DoorstepService:
    service = DoorstepService(Database(":memory:"))
    service.reset()
    return service


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from doorstep.api.app import create_app

    monkeypatch.delenv("DEMO_AUTH_TOKEN", raising=False)
    app = create_app(":memory:", seed=True)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def warn(svc):
    return svc.start_demo_warning(seed.DEMO_ZONE, seed.SCENARIO_ID)


def t_offers(**overrides_by_id):
    out = []
    for raw in seed.transport_offers():
        raw.update(overrides_by_id.get(raw["offer_id"], {}))
        out.append(TransportOfferIn(**raw))
    return out


def d_offers():
    return [DestinationOfferIn(**raw) for raw in seed.destination_offers()]


def maria_confirmed(svc) -> str:
    warn(svc)
    svc.submit_resident_response(MARIA, "1 Necesito ayuda, uso silla de ruedas y tengo un perro", "es",
                                 sender=MARIA_SENDER, external_id="m1")
    svc.submit_resident_response(MARIA, "SI", "es", sender=MARIA_SENDER, external_id="m2")
    return MARIA


def maria_evaluated(svc):
    maria_confirmed(svc)
    t = svc.evaluate_transport(MARIA, t_offers(), "req_001")
    d = svc.evaluate_destination(MARIA, d_offers(), "req_002")
    return t, d


def maria_proposed(svc) -> str:
    maria_evaluated(svc)
    view, _ = svc.propose_assignment(MARIA, transport_offer_id="offer_t_001", destination_offer_id="offer_d_001",
                                     idempotency_key=f"{MARIA}:transport:v1")
    return view["assignment_id"]


def maria_accepted(svc) -> str:
    aid = maria_proposed(svc)
    svc.respond_assignment(aid, "transport_org_a", "ACCEPTED")
    svc.respond_assignment(aid, "destination_org_a", "ACCEPTED")
    return aid


def pickup_ev(**kw):
    base = dict(type="PROVIDER_AND_RESIDENT_CONFIRMATION", provider_confirmed=True, resident_confirmed=True,
                code_verified=True)
    base.update(kw)
    return Evidence(**base)


def arrival_ev(**kw):
    base = dict(type="DESTINATION_CHECKIN", destination_provider_id="destination_org_a", provider_confirmed=True)
    base.update(kw)
    return Evidence(**base)


def david_confirmed(svc) -> str:
    warn(svc)
    svc.submit_resident_response(DAVID, "1", "en", sender=DAVID_SENDER, external_id="d1")
    svc.submit_resident_response(DAVID, "yes", "en", sender=DAVID_SENDER, external_id="d2")
    return DAVID

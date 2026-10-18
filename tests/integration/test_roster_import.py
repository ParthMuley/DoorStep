"""An organization bulk-imports its volunteer roster (CSV) into B's real app, hands out
one-time invite codes, and the imported volunteers are matched with explained reasons."""

from pathlib import Path

import httpx
import pytest

from doorstep.workflows.backend_v2 import BackendError
from doorstep.workflows.roster_import import import_roster, parse_row
from tests.integration.fake_v2_backend import TOKEN, make_v2_backend, network_client

ROSTER = (Path(__file__).resolve().parents[2] / "scripts" / "rosters" / "eastside_rides_demo.csv").read_text("utf-8")
ORG, REGION = "eastside_rides_demo", "la_county:east_valley"


def test_bad_rows_are_rejected_with_a_reason():
    ok = {"volunteer_id": "v1", "name": "V (synthetic)", "lat": "34.1", "lon": "-118.1", "needs_they_can_cater": "1;4"}
    assert parse_row(ok)["needs_they_can_cater"] == [1, 4] and parse_row(ok)["approved"] is True
    for bad, why in (({**ok, "lat": ""}, "missing lat"), ({**ok, "lat": "95"}, "out of range"),
                     ({**ok, "needs_they_can_cater": "1;12"}, "1-10")):
        with pytest.raises(ValueError, match=why):
            parse_row(bad)


async def test_roster_import_invites_and_match(monkeypatch):
    backend, _ = make_v2_backend(monkeypatch)
    async with httpx.AsyncClient(transport=backend._transport, base_url="http://backend.test") as http:
        results = await import_roster(http, ORG, REGION, ROSTER + "vol_bad,Bad (synthetic),,,SEDAN\n", TOKEN)
        again = await import_roster(http, ORG, REGION, ROSTER, TOKEN)
    by_id = {r.volunteer_id: r for r in results}
    assert [r.status for r in results] == ["IMPORTED"] * 5 + ["INVALID"]
    assert all(r.invite_code and r.invite_code.startswith("EASTSIDE-") for r in results[:5])
    assert len({r.invite_code for r in results[:5]}) == 5
    assert {r.status for r in again} == {"EXISTS"}  # re-import never overwrites

    linked = await backend.link(by_id["vol_eastside_alex"].invite_code, "agent1q_alex_test", "corr")
    assert linked["role"] == "VOLUNTEER" and linked["volunteer_id"] == "vol_eastside_alex" and linked["org_id"] == ORG
    with pytest.raises(BackendError):  # one-time code
        await backend.link(by_id["vol_eastside_alex"].invite_code, "agent1q_someone_else", "corr")

    poll = (await backend.trigger_alert("ISSUE", "corr", preset="ZONE_3_WILDFIRE", poll_now=True))["poll_result"]
    warning = next(a["alert_id"] for a in poll["new_alerts"] if a["status"] == "WARNING")
    net = network_client(backend)
    await net.start_outreach(warning, f"{warning}:outreach", "corr")
    for vid in ("vol_eastside_alex", "vol_eastside_jordan", "vol_eastside_priya"):
        await net.record_availability(warning, vid, ORG, True, "2026-10-18T10:00:00Z", f"{warning}:{vid}", "corr")
    for i, text in enumerate(["1 Necesito ayuda. Uso silla de ruedas y tengo un perro pequeño.", "SI"]):
        await backend.submit_resident_response("case_maria_001", text, "sim_phone_maria", "corr", language="es",
                                               external_id=f"sim_maria_{i}")
    res = await backend.propose_match("case_maria_001", True, "maria:match:v1", "corr")
    vols = res["evaluation"]["volunteers"]
    assert vols["eligible"][0]["volunteer_id"] == "vol_eastside_alex"  # closest, covers wheelchair + transfer + pet
    assert res["match"]["volunteer_id"] == "vol_eastside_alex"
    why = {x["volunteer_id"]: x["reason_codes"] for x in vols["rejected"]}
    assert "NO_WHEELCHAIR_SPACE" in why["vol_eastside_jordan"]
    assert "INSUFFICIENT_PET_CAPACITY" in why["vol_eastside_priya"]
    assert "VOLUNTEER_NOT_APPROVED" in why["vol_eastside_kim"]
    assert "AWAITING_REPLY" in why["vol_eastside_sam"]  # asked, hasn't answered

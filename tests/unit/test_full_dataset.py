"""The "full" demo dataset (decision B-45, docs/demo-cast.md): every person's story plays out as the
cast sheet says, over the real API. The "core" dataset stays the default for every other test."""

import pytest

from doorstep.demo import seed

V2 = {"schema_version": "2.0"}
NETWORK = {"X-Agent-Token": "change-me-network-agent-token"}
DOORSTEP = {"X-Agent-Token": "change-me-doorstep-agent-token"}

WILDFIRE_YES = ["sarah", "joe", "lee", "nadia", "marcus", "fatima", "mei", "raj", "hector"]
FLOOD_YES = ["lee", "hector", "diego", "rina", "fatima", "mei"]


def reset_full(client):
    r = client.post("/demo/reset", json={"dataset": "full"})
    assert r.status_code == 200, r.text
    return r.json()


def trigger(client, preset):
    r = client.post("/demo/alerts/trigger", json={**V2, "action": "ISSUE", "preset": preset, "poll_now": True})
    assert r.status_code == 200, r.text
    return r.json()["poll_result"]


def outreach_and_answer(client, poll, yes, no=()):
    asked = set()
    for alert in poll["new_alerts"]:
        if alert["status"] == "ORDER":
            continue  # nobody is sent into an order zone; outreach runs for the warning
        r = client.post(f"/alerts/{alert['alert_id']}/outreach", headers=NETWORK, json={})
        assert r.status_code == 200, r.text
        asked |= {a["volunteer_id"] for o in r.json()["orgs"] for a in o["asked"]}
    for name in yes:
        client.post("/sim/inbound", json={"sender": f"sim_phone_{name}", "text": "YES", "external_id": f"y-{name}"})
    for name in no:
        client.post("/sim/inbound", json={"sender": f"sim_phone_{name}", "text": "NO", "external_id": f"n-{name}"})
    return asked


def ask_for_help(client, case_id, sender, yes="YES"):
    for i, text in enumerate(["1", yes]):
        r = client.post(f"/cases/{case_id}/responses", json={"text": text, "sender": sender,
                                                             "external_id": f"{case_id}-{i}"})
        assert r.status_code == 200, r.text


def evaluate(client, case_id):
    r = client.post("/matches/propose", json={**V2, "case_id": case_id, "create_proposal": False})
    assert r.status_code == 200, r.text
    return r.json()


def first(ev, kind):
    eligible = ev["evaluation"][kind]["eligible"]
    return eligible[0]["volunteer_id" if kind == "volunteers" else "site_id"] if eligible else None


def rejected(ev, kind, entity):
    key = "volunteer_id" if kind == "volunteers" else "site_id"
    return next(c for c in ev["evaluation"][kind]["rejected"] if c[key] == entity)


# ----------------------------------------------------------------- dataset shape
def test_core_stays_the_default(client):
    body = client.post("/demo/reset").json()
    assert body["dataset"] == "core" and body["residents"] == 2


def test_full_dataset_counts(client):
    body = reset_full(client)
    assert (body["dataset"], body["residents"], body["organizations"], body["volunteers"], body["link_codes"]) == \
        ("full", 10, 11, 15, 19)


def test_unknown_dataset_rejected(client):
    assert client.post("/demo/reset", json={"dataset": "huge"}).status_code == 422


def test_full_ids_are_unique_and_labeled_synthetic():
    people = [r.name for r in seed.residents("full")] + \
             [v.name for r in seed.regions("full") for o in r.orgs for v in o.volunteers]
    assert all("(synthetic)" in n for n in people)
    vids = [v.volunteer_id for r in seed.regions("full") for o in r.orgs for v in o.volunteers]
    assert len(vids) == len(set(vids))
    assert len({c["display_name"] for c in seed.link_codes("full").values()}) == 19


# ----------------------------------------------------------------- wildfire
@pytest.fixture
def wildfire(client):
    reset_full(client)
    poll = trigger(client, "ZONE_3_WILDFIRE")
    return client, poll


def test_wildfire_zones_and_consent(wildfire):
    client, poll = wildfire
    zones = {c["case_id"]: c["zone_status"] for c in poll["affected_cases"]}
    for case in ("case_maria_001", "case_ruth_003", "case_carlos_004", "case_kenji_005"):
        assert zones[case] == "WARNING"
    assert zones["case_david_002"] == "ORDER" and zones["case_harold_007"] == "ORDER"
    assert "case_beatriz_008" not in zones                       # outside every zone
    contacted = str(poll["checkins_sent"])
    assert "grace" not in contacted                               # opted out: never contacted
    orgs = {o["org_id"] for o in poll["outreach_orgs"]}
    assert orgs == {"eastside_rides_demo", "neighbor_sedans_demo", "red_cross_demo", "valley_paratransit_demo",
                    "hillside_drivers_demo"}                       # flood-only and unapproved orgs never asked


def test_wildfire_outreach_skips_unapproved_and_far_volunteers(wildfire):
    client, poll = wildfire
    asked = outreach_and_answer(client, poll, WILDFIRE_YES, no=["maya"])
    assert {"volunteer_sarah", "volunteer_nadia", "volunteer_marcus", "volunteer_raj"} <= asked
    assert "volunteer_hector" in asked                            # his co-op handles fires too
    assert not asked & {"volunteer_beth", "volunteer_tom", "volunteer_sam", "volunteer_diego", "volunteer_rina"}


def test_wildfire_matches(wildfire):
    client, poll = wildfire
    outreach_and_answer(client, poll, WILDFIRE_YES, no=["maya"])
    ask_for_help(client, "case_maria_001", seed.MARIA_SENDER, yes="SI")
    ask_for_help(client, "case_ruth_003", "sim_phone_ruth")
    ask_for_help(client, "case_carlos_004", "sim_phone_carlos", yes="SI")
    ask_for_help(client, "case_kenji_005", "sim_phone_kenji")

    maria = evaluate(client, "case_maria_001")      # core story unchanged
    assert first(maria, "volunteers") == "volunteer_sarah" and first(maria, "shelters") == "dest_center_a"

    ruth = evaluate(client, "case_ruth_003")        # oxygen: van that handles it, shelter that supports it
    assert first(ruth, "volunteers") == "volunteer_nadia" and first(ruth, "shelters") == "dest_center_a"
    gym = rejected(ruth, "shelters", "dest_gym_b")
    assert gym["missing_needs"] == [3]

    carlos = evaluate(client, "case_carlos_004")    # 2 dogs + walker: closer sedan rejected
    assert first(carlos, "volunteers") == "volunteer_marcus"
    joe = rejected(carlos, "volunteers", "volunteer_joe")
    assert "INSUFFICIENT_PET_CAPACITY" in joe["reason_codes"] and joe["missing_needs"] == [8]

    kenji = evaluate(client, "case_kenji_005")      # service animal
    assert first(kenji, "volunteers") == "volunteer_fatima"

    ask_for_help(client, "case_harold_007", "sim_phone_harold")   # inside the order zone, like David
    harold = client.post("/matches/propose", json={**V2, "case_id": "case_harold_007"}).json()
    assert harold["match"] is None and harold["no_match_reason"] == "ORDER_ZONE"


def test_wildfire_real_proposals_do_not_collide(wildfire):
    client, poll = wildfire
    outreach_and_answer(client, poll, WILDFIRE_YES, no=["maya"])
    picks = {}
    for case, sender, yes in (("case_maria_001", seed.MARIA_SENDER, "SI"), ("case_ruth_003", "sim_phone_ruth", "YES"),
                              ("case_carlos_004", "sim_phone_carlos", "SI"), ("case_kenji_005", "sim_phone_kenji", "YES")):
        ask_for_help(client, case, sender, yes=yes)
        r = client.post("/matches/propose", json={**V2, "case_id": case, "idempotency_key": f"{case}:m"})
        assert r.status_code == 201, r.text
        picks[case] = r.json()["match"]["volunteer_id"]
    assert picks == {"case_maria_001": "volunteer_sarah", "case_ruth_003": "volunteer_nadia",
                     "case_carlos_004": "volunteer_marcus", "case_kenji_005": "volunteer_fatima"}


# ----------------------------------------------------------------- flood
def test_flood_use_case(client):
    reset_full(client)
    poll = trigger(client, "SOUTH_VALLEY_FLOOD")
    assert {a["calamity_type"] for a in poll["new_alerts"]} == {"FLOOD"}
    assert {c["case_id"] for c in poll["affected_cases"]} == {"case_omar_009", "case_dolores_010"}
    orgs = {o["org_id"] for o in poll["outreach_orgs"]}
    assert orgs == {"red_cross_demo", "flood_only_demo", "valley_paratransit_demo"}   # wildfire-only orgs skipped

    outreach_and_answer(client, poll, FLOOD_YES)
    ask_for_help(client, "case_omar_009", "sim_phone_omar")
    ask_for_help(client, "case_dolores_010", "sim_phone_dolores", yes="SI")
    omar = evaluate(client, "case_omar_009")
    assert first(omar, "volunteers") == "volunteer_hector" and first(omar, "shelters") == "dest_library_c"
    dolores = evaluate(client, "case_dolores_010")
    assert first(dolores, "volunteers") == "volunteer_diego"


# ----------------------------------------------------------------- linking + approval
def test_full_link_codes_and_pending_volunteer(client):
    reset_full(client)
    r = client.post("/link", headers=DOORSTEP, json={**V2, "code": "RUTH-2417", "asi_one_address": "user1qruth_demo"})
    assert r.status_code == 200, r.text
    r = client.post("/link", headers=DOORSTEP, json={**V2, "code": "NADIA-5162", "asi_one_address": "user1qnadia_demo"})
    assert r.status_code == 200, r.text
    pending = client.get("/volunteers/pending", params={"org_id": "hillside_drivers_demo"}).json()["volunteers"]
    assert [p["volunteer_id"] for p in pending] == ["volunteer_beth"]

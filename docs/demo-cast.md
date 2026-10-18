# Demo cast (full dataset)

> DOORSTEP DEMO: every person, organization and address below is **synthetic**. Link codes are public because nobody is real.

There are two demo datasets (decision B-45):

| Dataset | Who's in it | Used by |
|---|---|---|
| **core** | Maria, David, Sarah, Joe, Maya, Lee, Tom, Rina, Sam | every test and the scenario runner (they check exact counts) |
| **full** | core + everyone marked *new* below | the live demo on Render (`DEMO_DATASET=full`) |

Load one (Bearer `DEMO_AUTH_TOKEN`):

```bash
curl -X POST "$DOORSTEP_API_URL/demo/reset" -H "Authorization: Bearer $DEMO_AUTH_TOKEN" \
     -H "content-type: application/json" -d '{"dataset": "full"}'
```

With no body, `/demo/reset` uses `DEMO_DATASET`, else core. Maria's and David's stories are the same in both.

## Use case 1: wildfire (`ZONE_3_WILDFIRE`)

Organizations asked: Eastside Accessible Rides, Neighborhood Sedans, Red Cross, Valley Paratransit Co-op, Hillside Community Drivers. **Not** asked: Flood Boats (floods only) and Unlisted Vans (not approved).

### Residents

| Person | Code | Zone | Needs | What should happen |
|---|---|---|---|---|
| Maria (es) | `MARIA-4821` | Warning | wheelchair, transfer help, 1 dog, step-free | **Sarah**'s wheelchair van → Civic Center. Joe is closer, but his sedan is rejected |
| David | `DAVID-5932` | **Order** | wheelchair | No volunteer. Escalated, receipt only, **unresolved** |
| Ruth *(new)* | `RUTH-2417` | Warning | oxygen, equipment space, caregiver rides along | **Nadia**'s oxygen-ready van → Civic Center. The gym is rejected (no oxygen support) |
| Carlos *(new, es)* | `CARLOS-3851` | Warning | walker, **2 dogs** | **Marcus**'s SUV. Joe is closer, but has room for only 1 pet and no walker space |
| Kenji *(new)* | `KENJI-4962` | Warning | service animal, walker | **Fatima**'s Red Cross minivan |
| Grace *(new)* | none | Warning | wheelchair | **Never contacted:** she opted out |
| Harold *(new)* | `HAROLD-5073` | **Order** | oxygen | Like David: escalated, **unresolved** |
| Beatriz *(new, es)* | none | Outside every zone | wheelchair, transfer help | **Not contacted:** she's outside the alert zones |

## Use case 2: flood (`SOUTH_VALLEY_FLOOD`, new)

```json
{"action": "ISSUE", "preset": "SOUTH_VALLEY_FLOOD", "poll_now": true}
```

Organizations asked: Red Cross, Flood Boats, Valley Paratransit Co-op. The wildfire-only organizations are skipped.

| Person | Code | Needs | What should happen |
|---|---|---|---|
| Omar *(new)* | `OMAR-4093` | wheelchair, transfer help | **Hector**'s high-roof van (2 wheelchair spaces) → South Valley Library Hall |
| Dolores *(new, es)* | `DOLORES-6184` | **3 pets** | **Diego**'s high-clearance truck (room for 3 pets) |

## Volunteers

To answer as a volunteer without ASI:One, send `YES` or `NO` from their simulated phone: `POST /sim/inbound {"sender": "sim_phone_<name>", "text": "YES"}`. Anyone who doesn't answer within 15 minutes counts as not available.

| Volunteer | Code | Organization | Vehicle | Can help with | Notes |
|---|---|---|---|---|---|
| Sarah | `SARAH-7310` | Eastside Accessible Rides | wheelchair van, 2 seats | wheelchair, transfer, 1 pet, Spanish | Maria's match |
| Nadia *(new)* | `NADIA-5162` | Eastside Accessible Rides | wheelchair van, 3 seats | wheelchair, transfer, oxygen, equipment, caregiver | Ruth's match; no pet space |
| Joe | none | Neighborhood Sedans | sedan, 3 seats | 1 pet, Spanish | closest to Maria and Carlos, rejected for both |
| Marcus *(new)* | `MARCUS-6274` | Neighborhood Sedans | SUV, 4 seats | 2 pets, Spanish, walker | Carlos's match |
| Maya | none | Red Cross | minivan, 4 seats | transfer, 1 pet, Spanish, walker | says NO in the scripted demo |
| Fatima *(new)* | `FATIMA-7395` | Red Cross | minivan, 5 seats | transfer, 1 pet, service animal, Spanish, walker | Kenji's match |
| Lee | `LEE-6624` | Red Cross (South Valley) | wheelchair van, 2 seats | wheelchair, transfer, 1 pet, service animal | Maria's backup if Sarah declines |
| Sam | none | Red Cross (San Francisco) | wheelchair van | | never asked for an LA alert |
| Hector *(new)* | `HECTOR-7385` | Valley Paratransit Co-op | high-roof van, 2 wheelchair spaces | wheelchair, transfer, oxygen, walker, equipment, caregiver | Omar's match; Ruth's backup |
| Mei *(new)* | `MEI-8406` | Valley Paratransit Co-op | sedan, 3 seats | Spanish, walker | |
| Raj *(new)* | `RAJ-9628` | Hillside Community Drivers | sedan, 3 seats | Spanish | |
| Beth *(new)* | `BETH-9739` | Hillside Community Drivers | minivan, 5 seats | 1 pet, walker | **waiting for approval**: shows on the coordinator's approval card |
| Tom | none | Unlisted Vans | wheelchair van | | organization not approved, never asked |
| Rina | none | Flood Boats | wheelchair van | wheelchair, transfer, 1 pet | floods only |
| Diego *(new)* | `DIEGO-8517` | Flood Boats | high-clearance truck | 3 pets, Spanish, walker | Dolores's match |

Coordinator: `COORD-1150`. Approve Beth with `POST /orgs/hillside_drivers_demo/volunteers/volunteer_beth/approve`.

## Shelters and recovery

| Place | Organization | Beds | Supports | Notes |
|---|---|---|---|---|
| Civic Center | Civic Center Shelter | 12 | oxygen, pets, service animals, step-free | the only shelter with oxygen support |
| Eastside High Gym *(new)* | Civic Center Shelter | 40 | pets, service animals, step-free | no oxygen, so never Ruth's |
| South Valley Library Hall *(new)* | Red Cross | 15 | pets, step-free | flood shelter |
| Red Cross Shelter (Westside) | Red Cross | 30 | pets, service animals, step-free | far from both zones |

Recovery organizations: Red Cross (housing, insurance guidance), Recovery Housing Partners (housing), **Insurance Help Desk** *(new)* (insurance guidance), **Community Supplies Bank** *(new)* (supplies, replacing medical equipment such as Ruth's oxygen gear).

## Suggested demo order

1. Reset with `{"dataset": "full"}` and open the coordinator board: approve Beth.
2. Issue the wildfire. Show who was contacted: Grace and Beatriz were not.
3. Volunteers answer (Maya says no). Match Maria, Ruth, Carlos and Kenji: each gets a different volunteer for a different reason.
4. Take Maria all the way to arrival (the main story). David and Harold stay unresolved.
5. Issue the flood: only flood-capable organizations are asked. Omar gets Hector, Dolores gets Diego.

Checked by `tests/unit/test_full_dataset.py`. If a story here changes, update that test too.

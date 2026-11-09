# Shared downstream mission legs (SHARED-DOWNSTREAM, 9 Nov 2026)

Three skill streams (SKILL-KILLMARK, SKILL-ROOFTOP, SKILL-POLICE) had their own skill working and
lost the job afterwards, in mission code nobody owned: the two-star getaway, the respray, and the
COP CAR CRUSH drives that burned the Cop Car. This page records what was wrong, what changed and the
sessions that prove it. Runners live in `gamerun/` (mirrored in `linux/docker/`).

## 1. COP CAR CRUSH: the Cop Car burning (SKILL-ROOFTOP's losses)

**Respray with no money** (`skills/deliver_intact.py`). In rp6 and rp8 the fragile drive, with the
car under carhp 17500, diverted to the respray at 86.5,160.5: 65 blocks off the way to the crane.
The player had $15-20 and a respray takes $5,000 (`RESPRAY_COST`; with less the shop does nothing,
pt8_respray2), so nothing was repaired and the detour took the car from about 14000 to 2000 and
set it alight. `deliver()` now diverts only with at least `RESPRAY_COST` on hand (`SP_RESPRAY_COST`
overrides it); without the money the leg goes on to its goal at the health-paced speed. This
applies to every job that drives through `deliver_intact.deliver` (horn pickups, crane drives, car
bomb, escort, GET GAMA REI, HOT DOG HOMICIDE).

**Shady's box** (`skills/horn_pickup.py`, step 1). Two more losses on the 4-block hop from the street
point into Shady's 2 x 2 locate box, an alley between two buildings:
- sd_ccc2: the stand-point drive stalled on its first move, re-routed onto a 95-block route and
  pressed the car on walls and traffic from 26283 to a fire. The drive is now stopped when it gets
  `WANDER` (4) blocks farther from the box than it started (at least 8 away).
- sd_ccc4: the car stopped at y 96.50, 0.04 outside the box edge. Every drive then "arrived" at
  once (tolerance 0.9 around a point 0.7 inside the edge) and the six legs ran out in 4 s. After the
  drive, a box centre nearer than `CREEP_NEAR` (3) is now crept into straight
  (`deliver_intact.creep_into` on the locate box itself, ended only by the horn brief or boarding).
- sd_ccc5 (an intermediate version that crept first, from the alley mouth) shows why the creep
  comes second: the straight line from the street hits the alley walls (-5800 carhp). The router
  drive does the turn into the alley; the creep only does the last short way.

The crane step (`skills/crusher_crane.py`, SKILL-CRUSHER's) needed no change: its lane creep put the
car under the hook in every session that got there.

## 2. BANK ROBBERY: the getaway and the respray (SKILL-POLICE, SKILL-KILLMARK)

`missions/bank_robbery_sp.py` v1 ran the old runner (`bank_robbery.py`) and drove the getaway
with the shared `drive3`, which stops at corners and queues in traffic: busted at the right-angle
turns in 6 of 19 sessions, and its stair climb pinned at 193.4,177.2 in 5 of the last 6. v2 is
built on `missions/bank_robbery_km.py` (KILLMARK-GETAWAY's runner: the getaway car parked in the
eastbound lane, the guards by `skills/kill_marked`, the launch and one hand-placed path from the
bank to the 204 bay without stops). Where that runner would roll into a bay (`lane_in`), v2 hands
the step to `skills/shake_police.shake`, which picks the shop, drives the rest under the chase
rules when the path ended early, breaks away from an officer at the door, takes another shop after
a miss, and enters with the job's rolling bay entry.

Two optional arguments were added to `shake_police` (defaults keep the old behaviour):
- `enter(shop, secs, done, check)`: the job's own way into the tunnel instead of the pulse creep
  (`respray(..., enter=)`, `shake(..., enter=)`). Pulses at two stars are a car standing still,
  and officers board it (sp2, sp5, sp9, kmg9).
- `first=(x, y)`: the shop the job's drive brought the car to, tried first without the router (five
  router calls are seconds standing still at two stars; sp7).

## 3. Sessions

Fresh games, `GTA2_SPEED=2`, `FPS=0`, `GTA2_DIRECT_KEYS=1` (chase view), shared stage:

```
GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \
  gamerun/grun.sh sd_ccc<N> 1500 missions/keys_cop_car_crush.sh -e GTA2DX9_STATE_EVERY=5
GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 gamerun/grun.sh sd_br<N> 1200 keys_bank_robbery_sp.sh -e GTA2DX9_STATE_EVERY=5
```

| session | job | code | result | where it was won or lost |
|---|---|---|---|---|
| sd_ccc1 | COP CAR CRUSH | respray gate | **complete** ($20,654) | car healthy all the way (crane lane at 26083); gate not exercised |
| sd_br1 | BANK ROBBERY (sp v2) | final | **complete** ($20,080) | path to the bay in 12 s; `shake_police` respray at 204.5,221.5: wanted 2 -> 0, $5,000 taken, 2 s |
| sd_ccc2 | COP CAR CRUSH | respray gate | lost (car burned) | stand-point drive into Shady's box re-routed 95 blocks (fixed: `WANDER`) |
| sd_ccc3 | COP CAR CRUSH | creep v1 | **complete** ($20,750) | crane seen lifting the car (z 3.00) |
| sd_br2 | BANK ROBBERY (sp v2) | final | **complete** ($20,040) | path ended early at 216.0,200.1; the skill drove the rest to the bay and resprayed |
| sd_ccc4 | COP CAR CRUSH | creep v1 | lost (stuck) | 0.04 outside Shady's box edge, six legs in 4 s (fixed: creep into the locate box) |
| sd_ccc5 | COP CAR CRUSH | creep v2 (creep first) | **complete** ($20,743) | the creep from the alley mouth hit the walls (-5800); reordered: drive first |
| sd_ccc6 | COP CAR CRUSH | final | not counted | the rooftop phone answer failed (1113, no title): never reached these legs |
| sd_ccc7 | COP CAR CRUSH | final | **complete** ($20,661) | Shady boarded, crane seen lifting the car |
| sd_br3 | BANK ROBBERY (sp v2) | final | **complete** ($20,040) | officer 0.7 from the bay door: `shake_police` broke away (back), resprayed (wanted 2 -> 0) |
| sd_ccc8 | COP CAR CRUSH | final | **complete** ($20,001) | the stand-point drive wandered to 88.1,89.2 and was stopped; the next try reached the box |

**Results on the final code.** BANK ROBBERY with the respray by `shake_police`: 3 of 3 (sd_br1-3);
the guards in the same sessions are `kill_marked`'s (SKILL-KILLMARK). COP CAR CRUSH: 2 of 3 sessions
(sd_ccc7, sd_ccc8; sd_ccc6 lost upstream in the rooftop phone step), 2 of 2 that reached these legs.
No `FAULT` in any of the five complete sessions' logs; frames in the chase view (`m_ccc_end`,
`m_br_end`, `m_sp_resprayed`). Earlier versions: sd_ccc1/3/5 complete, sd_ccc2/4 lost (fixed after).

Untested: the respray gate firing in a session (no session since had the car under 17500 with a shop
near); the horn-pickup changes on stops other than Shady's box (`pickups()` in other jobs use it).
Still open, outside these legs: fires from the frozen shared driver grinding through traffic (rp3),
the rooftop phone answer (sd_ccc6).


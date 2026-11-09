# Skill: shake the police / respray (Wave M, SKILL-POLICE, 9 Nov 2026)

Module `gamerun/skills/shake_police.py` (mirrored in `linux/docker/skills/shake_police.py`). It is
verified on BANK ROBBERY! (`wil_ye2`) with `gamerun/missions/bank_robbery_sp.py`
(`keys_bank_robbery_sp.sh`). It is built on the frozen `mission_lib` / `drive_lib` and changes
neither of them. It also leaves `missions/bank_robbery.py` unchanged; the GET GAMA REI runner
imports that file.

## What the 11 jobs ask

These are the `wanted_evasion` jobs in `docs/missions-catalogue.json`: wil_ye2, wil_yh1, wil_zm3,
ste_zm3, ste_zh2, ste_rm3, ste_rh2, bil_ke2, bil_zh1, bil_zh2 and bil_rm1. In the scripts they follow
one of three patterns:

- **Clear the level.** BANK ROBBERY does `ALTER_WANTED_LEVEL_NO_DROP (p1, 2)` and then loops on
  `CHECK_HEADS_GREATER`. A NO_DROP level never decays, so only a respray or a bribe ends it. Any
  respray clears it, not only the shop the script's arrow points at.
- **Survive a timed chase.** DISTRACTION ACTION asks the player to evade arrest for 60 s.
- **Bring home a police or army vehicle.** These are SWAT VAN SWIPE, LAW ENFORCEMENT LARCENY, COP
  CAR SCRAP, the tank jobs and OFFICER DOWN. The level rises by itself. A respray on the way
  repairs the car to carhp 32000, which keeps it intact.

## Respray shops

A respray is a `CAR_SHOP n` object, where n is the remap colour it paints. `BOMB_SHOP`,
`OILSLICK_SHOP`, `MINES_SHOP` and `MACHINEGUN_SHOP` are the other drive-ins in the same strip, two
cells apart. Each district has the following resprays (from `assets-src/missions/{wil,ste,bil}.mis`):

| district | shops (x, y: remap) |
|---|---|
| wil | 204.5,221.5: 10 · 219.5,34.5: 32 · 24.5,60.5 (level 2): 5 · 46.5,136.5: 0 · 86.5,160.5: 9 · 209.5,121.5: 26 |
| ste | 6.5,183.5: 0 · 178.5,216.5: 5 · 215.5,76.5: 9 · 94.5,27.5: 10 |
| bil | 177.5,14.5: 28 · 234.5,154.5: 24 · 30.5,216.5: 2 · 64.5,90.5: 0 |

Each shop is a **drive-through, three cells long, under a roof**. For example, 204.5,221.5 is lot
cells 220-222 on column 204 with a level-2 roof. The two mouth cells are covered, so
`node_kind` calls them unwalkable. `_side_score` lets the first cell beyond the shop's own cell
through on its lid alone. It then scores up to six more cells outward: road 3, lot 1.5, pavement
0.5, stopping at a wall face. Every side scoring at least 4 becomes an entry point 2.9 cells out
from the centre. Two sides were driven in earlier sessions, and each of those two shops keeps only
its proven side: 204.5,221.5 from the north (br7, br9, gr1) and 86.5,160.5 from the south.
`pick_shop` asks the shared car router for the path length to the five nearest entries by straight
line, and takes the shortest. When the router finds no path, the cost is the straight distance x 1.4 + 20.
Offline check (`python3 skills/shake_police.py <game data dir>` on the host):

- from the bank getaway (190,179.6): 204.5,221.5 from the north, a 76-cell route;
- from 60,150: 46.5,136.5 from the south, 26 cells;
- from 120,60: 219.5,34.5 from the west, 141 cells.

Going in with at least $5,000 sets the wanted level to 0, repairs the car and takes the money. In
br7 the money went from 5040 to 40 and carhp went to 32000. In pt8_respray2, with only $20, nothing
happened at all.

## API

| call | does |
|---|---|
| `wanted()`, `police_near(s, car_r, ped_r)` | `wanted()` reads the level from `view: mission`; `police_near` counts police cars (models 12/52/54) and officers on foot, and gives their centroid |
| `shops(world)`, `pick_shop(world, s, avoid)`, `pick_shop_fast(...)` | the district's shop entries (as above); the nearest by route, or by straight line when police are within 8 blocks, so the car does not stand still during the router calls (sp7) |
| `chase_drive(world, x, y, tol, budget, until)` | `M.drive3` under a chase: the normal pace while carhp >= 20000 (the fragile caps made sp5's car a 2 blocks/s target). If an officer on foot comes within 2.3 blocks while the car is slower than 1.5, the drive stops for `break_away()` (forward if the way ahead is open, else reverse with the wheel turned) and then resumes |
| `respray(world, shop, check, view_switch, done)` | drives to the entry with the fragile-car guards, creeps into the tunnel cell and waits for the game (wanted 0 from above 0, carhp back to 30000+, the money taken, or `done()`); if nothing happens it backs out the way it came |
| `shake(world, check, view_switch, done, tries, budget, evade_ok)` | the whole skill: resprays nearest-first, with a second go at a shop before it is skipped. Without $5,000, or with `evade_ok`, it then runs `evade()` until the level drops |
| `evade(world, secs, check, view_switch, until)` | drives 25-45 block legs to road cells on the far side of the police it has seen, for `secs` seconds (scaled by `GTA2_SPEED`) or until `until()` holds; for timed chases |

Every step writes a `police: ...` line to `/out/marks.txt` and appends to `EVENTS`. The milestone
frames are `sp_getaway`, `sp_respray_in`, `sp_resprayed` and `sp_evade<n>`.

```python
from skills import shake_police as SP
r = SP.shake(world, check=check, view_switch=view_switch,
             done=lambda: <the job's next brief / arrow>)    # "clear" | "stuck: ..."; check() raises on the job's end
r = SP.evade(world, 60, check=check, until=None)             # a timed chase: "time" | "clear" | "on foot"
```

## BANK ROBBERY runner

`missions/bank_robbery_sp.py` imports `bank_robbery` and replaces one function, `BR.drive`. The
first time that runner drives to one of its two hand-placed respray entries (step 5, after Hiroshi
is out and the level is at two stars, NO_DROP), `SP.shake` takes over. Its `done()` is the
safehouse arrow or brief 1661, 1662 or 1010. When the level is clear, the runner sees the
safehouse arrow and goes on to step 6 unchanged. If the skill does not clear the level, it marks
this and hands control back, so a session where the runner's own loop resprayed is labelled as such.
`SP_EVADE_FIRST=<s>` drives `evade` for that many seconds first; the level is NO_DROP, so this only
exercises the evasion legs.

## Sessions

All sessions ran at `GTA2_SPEED=1`, `GTA2_DIRECT_KEYS=1`, `FPS=0` (a screenshot every 5 s) through
`gamerun/grun.sh`, on a loaded host: the CPU governor paused several of them for minutes.

| session | code | outcome | what happened |
|---|---|---|---|
| sp1 | first version | phone "refused" (1093) | The walker came round the phone dais from the west and its unstick moves answered the neighbouring phone, GET ZITZAKI at 44.5,150.5. This phone then said "already on a Yakuza job" (1093), which `bank_robbery.answer` treats as a refusal. |
| sp2 | + 1093 with the arrow on the GRAHAM counts as answered | failed (1125) before the skill ran | The guards went down, then a cop punched him down at the car door: `wanted: busted: punched down while wanted` in the log. |
| sp3 | same | phone (1631, then 1093) | GET ZITZAKI's phone again. |
| sp4 | + walk to the east foot of the dais first | phone (1631, then 1093) | From the east foot, the router still goes up the dais by its only ramp (column 43) and turns north past 44.5,150.5. |
| sp5 | + hand-placed climb: ramp, row 152, then north | failed (1125) during the respray drive | The skill took over at the getaway: 204.5,221.5 by an 82-cell route. The fragile-car caps held the car to about 2 blocks/s. It was pressed on the corner of row 216 and column 204, 2.3 blocks from the entry, and an officer on foot pulled him out (busted). |
| **sp6** | + `chase_drive` (normal pace while carhp >= 20000, a break-away when an officer on foot is within 2.3 blocks of a slow car), drive tolerance 1.6, longer creep pulses | **JOB COMPLETE** (+$20,000) | The skill took over 384 s into the job, at two stars with NO_DROP. It drove to 204.5,221.5 and crept into the tunnel with one police car 15 blocks off. The respray took the money (5060 -> 60) and repaired the car (carhp 32000); the script said 1668, then 1010 ("Excellent, Kosai! Now bring the car back to the Safehouse"). 128 s from getting into the car to clear. The runner's safehouse leg then ran: PARK, 1124. |
| sp8 | + straight-line pick when police are within 8 blocks; the shop table read at level start | phone (1631, then 1093) | A ten-minute governor pause used up the wall-clock budget of the climb's walk, and the shared walker went up the dais its own way. |
| sp9 | + the two dais cells beside GET ZITZAKI's phone, (44,151) and (45,150), off the router for the approach | failed (1125) 22 s into the respray drive | The phone answered. The getaway drive west along row 179 took two hits. An officer on foot came within 2.3 blocks at 176,183; the break-away came 2 s after the drive stopped (log reads), when the arrest had already started. |
| sp7 | same as sp6 | failed (1125) at the car | He got into the car with two officers 2.0 blocks away and one police car near. `shake` spent 4.5 s with the car standing while it read the shop table and made five router calls, and he was arrested before it moved. |

# City AI in the street views (AI-TRAFFIC-PEDS, 9 Nov 2026)

Goal: pedestrians and traffic that read as a living city from a camera in the street:
lane discipline, junction behaviour, reactions to the player and to danger, pedestrians
keeping out of the way of cars, crowds that scatter at gunfire.

Code: `dll/src/city_ai.{h,cpp}` (hooked from `WorldView::MatchGameViewToFrame`, installed
from `dllmain.cpp`), settings `[city_ai]` in `package/gta2dx9.ini`, analysis
`tools/ai_census.py`, probe `gamerun/ai_probe.py` + `keys_ai_probe.sh` (not in git).

## What gta2.exe 9.6 already does (read off the binary)

Names from the CriminalRETeam/gta2_re reimplementation (10.5); the Ped layout is the same in
9.6 (+0x21C flags, bit 2 panicking; +0x258 objective; +0x25C internal objective; +0x28C
threat reaction, 3 = run away; +0x14C internal target ped; +0x1D0 internal target point).

| Behaviour | Where (9.6) | Verdict for the street views |
|---|---|---|
| Traffic follows the road arrows, keeps to the lane centre, stops at red lights, brakes and honks for peds and cars in its probe (about 1.75 blocks ahead) | CarAI (10.5 `AlignToLaneCenter`, `ReactToNearbyPed`, `ScanAheadForObstacles`) | Kept as is; measured below (axis share, queued vs free stops) |
| A civilian runs from a ped who fires a weapon or drives recklessly, if that ped is within **4 blocks** (Chebyshev) | 0x43F3DF..0x43F5D9; the compare `push 0x5E5C9C; call 0x4037E0` at 0x43F4D3/0x43F4E0; threatening-ped list 0x5E5EE0, flag 0x5E5BE2, added per shot by the weapon code (0x4CDD42...) and by reckless driving (0x49F41B) | 4 blocks is half the top-down screen. From the street, a shot 6 blocks away leaves everybody strolling |
| "Flee from ped till safe" ends as soon as the threat is **6 blocks** away and the ped stands on pavement | 0x4347D0, `push 0x5E5C2C` at 0x434804 | Caps any wider reaction: told to flee from 8 blocks, a ped stops at once |
| A ped never steps out of a car's way | - | A fast car (the player's) drives through a crowd that keeps walking |
| Nobody keeps clear of a burning car | - | People stroll past a car about to explode |

## What city_ai changes (third and first person only; the classic view keeps every byte)

1. The reaction radius: `gun_radius` (12) for an armed threat, `car_radius` (5) for one at
   the wheel. The call at 0x43F4E0 goes to `CityAiThreatLess`, which picks the radius by
   edi (the threatening ped, as the game's code holds him there).
2. The safe distance: `safe_distance` (14), the operand at 0x434805.
3. Dodge: a passer-by (threat reaction 3, on foot, no objective, no group, not panicking)
   within `dodge_time` seconds ahead of a car moving faster than `dodge_speed` blocks/s and
   within 0.75 blocks of its path gets the game's own SetObjective2 (0x436920) "flee on foot
   till safe" (1) from the point of the path beside him, faces straight off the path, runs.
4. Fire: the same from a burning car (damage 16000..32000) within `fire_radius` (4).

Every site is checked byte for byte before it is written; another exe build leaves the game
as shipped and logs `ai: gta2.exe is not the 9.6 this knows`.

## Census (`ai:` log lines)

Every `census_every` frames (15), two samples a line; within `census_radius` (20) of the
player: peds on foot by state (walk/run/stand/down/dead), panicking, fleeing (any flee
objective); driven cars moving/stopped, stopped behind another car (queued) or not (free
stop: lights, junctions, peds), share of moving cars within 10 degrees of a street axis,
mean speed; and the events since the last line: threat frames, flee onsets, dodges, fire
flees, near misses (a car over 2 blocks/s passing within 1 block of a ped). One
`ai: event <kind>` line per flee onset, dodge, fire flee and near miss.

## Measurements (9 Nov, L4 host, `gamerun/ai_probe.py`, Downtown, machine gun)

Same script with the reactions on and off (`GTA2DX9_CITY_AI=0`); `tools/ai_census.py
out/<run>`. Census within 20 blocks of the player. Runs on a loaded host: the governor paused
some containers (fps column of the tool), so the drive phases are not paired like for like.

**Gunfire** (three 1 s bursts; flee = mean peds with any flee objective or panicking during
the bursts; onsets = peds that started fleeing within 6 game seconds of the first burst):

| Spot | Run | Peds near | Flee (mean) | Run state (mean) | Onsets | by distance 0-4 / 4-8 / 8-12 / 12-20 |
|---|---|---|---|---|---|---|
| kerb 164.5,147.6 | off `aitp_off2` | 15.8 | 3.0 | 2.9 | 4 | 2 / 2 / 0 / 0 |
| kerb 164.5,147.6 | on `aitp_on2` | 14.4 | 8.4 | 8.4 | 12 | 7 / 0 / 3 / 2 |
| boulevard 165.5,140.5 | off `aitp_off3` | 10.3 | 0.6 | 0.6 | 1 | 1 / 0 / 0 / 0 |
| boulevard 165.5,140.5 | on `aitp_on3` | 9.6 | 4.8 (peak 7.5 of 10) | 3.5 | 6 | 0 / 2 / 3 / 1 |
| courtyard north of it | on `aitp_on4` | 8.2 | 6.3 | 6.2 | 9 | 2 / 1 / 2 / 4 |

With the game's 4-block radius almost nobody past the first few blocks reacts; with 12/14 the
street empties at a run and fills again within about 10 s (the flee ends on pavement past 14
blocks). Bystanders are also shot (dead 2.6 mean in `aitp_on2`: the script fires along the
pavement).

**Dodges** (`aitp_on3` + `aitp_on4`, 100 s drives by the route planner): 11 dodges, none
knocked down. One game second later the 4 peds on the car's right (`lat0` < 0, the kerb side
in GTA2's right-hand traffic) were 1.9 blocks further off the path (`lat1` -1.96..-2.62);
the 7 on its left (towards the road's centre) had moved only 0.2-0.3 blocks (0.62-0.74 to
0.93-1.01, all stopping near 1.0 off the centre line): they turn and run but get nowhere, presumably blocked by the median or the
pathing refusing the carriageway. That half does not work yet. Near misses
(a car over 2 blocks/s within 1 block of a ped) were 16 in that drive and 7 in the off drive (`aitp_off3`),
which had fewer peds near the route (7.0 against 12.3 mean): not comparable, and no claim is made.

**Traffic** (the game's own, unchanged; drive phases of all runs): 4-7 driven cars moving and
3-6 stopped within 20 blocks; 83-92 % of moving cars within 10 degrees of a street axis (the
rest are turning at junctions); of stopped cars 2-15 % queued behind another car, the rest
stopped free (lights, junction give-way, peds in the probe); mean moving speed 1.9-2.9 blocks/s.

**Fire flees**: 3 in `aitp_on2` (the player's own car alight beside a pavement).

## What still looks wrong

- Fleeing figures jog: the avatars have no fear, cower or point clips (quality bar row 34;
  the figure animation is not this stream's).
- The dodge works for peds on the kerb side of a car and not for those on the road-centre
  side (above); next step: send those to the kerb side too (cross the path ahead of a car
  still beyond 1 s) or to the nearest pavement cell, and log the car heading with each dodge.
- Frames: the probe's gunfire frames show one figure running off (aitp_on4 qa_fire0_3) but no
  crowd scatter in shot; the warp at 165.5,140.5 lands at 168.5 facing across the road and
  the walk north ends in a courtyard. A framed clip is still owed.
- Traffic: lane discipline and lights are the game's and measure well, but there is no
  speed variation by street, no indicators, and cars do not slow for a ped stepping off the
  kerb further ahead than their 1.75-block probe.
- Gunfire from police and gangs widens the same way (same code path); not filmed.

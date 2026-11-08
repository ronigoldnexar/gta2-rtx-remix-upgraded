# Playthrough: Residential and Industrial in the street-level views

7 Nov 2026, L4 GPU host, build 0725166 plus the uncommitted grass-classifier change
below. Each district was loaded directly (`SWAP_LEVEL=bil|ste` in `run_game_gpu.sh`) and
toured by script in the chase and first-person views: `linux/docker/tour_bil.py`,
`tour_ste.py`, `tour_bil_phone.py`, `tour_parks.py` on `tour_lib.py` (shared helpers:
confirmed developer warps, death detection, on-foot checks, labelled frames, a timeline in
`marks.txt`), launched by `tour_run.sh <district> <seconds> [script]`. Every developer warp
(the scene key: nearest parked car brought to `scene_xy`, player at its door, `scene_xy`
rewritten in the prefix's ini per press) is logged in `marks.txt` and happens behind a cut
to the classic view; the clips show the arrival on foot. Runs: `out/tour_bil*`,
`out/tour_ste*`, `out/tour_parks_*` (take 1 folders kept as `*_take1`).

## Residential (`bil`)

Facts from the data (`assets-src/missions/bil.mis`, `missions.json`, the GMP ZONE chunk):

- Player start 44.5,102.0 (z2). Information phones 64,189.5 and 202.5,34.5; the final-job
  phone 234.5,193.5 (`bil_end`, FINAL JOB!, needs 21 jobs). No `CHURCH_SINGING` sound in
  this script: the save point is not marked here (Industrial's is at its spawn).
- Phones: Krishna green 249.5,199.5 (DECONSTRUCTION YARD!) and 249.5,201.5 (COP CAR SCRAP!),
  yellow 233.5,132.5 / 235.5,132.5, red 216.5,219.5; Zaibatsu green 44.5,163.5 (IT WAS AN
  ACCIDENT!) and 45.5,161.5 (GRAND THEFT AUTO!), yellow 6.5,183.5 / 9.5,183.5, red 27,249;
  Russians green 187.5,76.5 (HOT DOG HOMICIDE!) and 189.5,76.5 (MMM, RUSSIAN SAILORS!),
  yellow 204.5,10.5 / 204.5,13.5, red 144.5,33.5. All gang phones sit on terraces one or
  more levels above the street (z3..z6).
- Zones: Zaibatsu SW (0,124 114x131), Russians N (72,0 183x80; 43,20), Krishna SE (175,109
  80x146; 117,214 58x24), `islagang` NW corner; six train stations (`trak00st`..`trak22st`,
  e.g. 47,59 and 249,12) with entry/exit cells, three bus stops (109,52; 18,133; 225,142;
  69,214); "Azeri Heights Docks" along the river on the north edge (water tiles y 0..16,
  x 48..176); two cranes at 10.5,149.5 / 14.5,153.5 and 173.5,27.5 / 169.5,23.5; the
  Krishna commune yard (grass with the "OPIUM / AMMO" crate blocks) at 128..160 x 240..255,
  one level up. No zone is named park or prison; the largest lawns are the commune yard
  and the east lawn at 224..240 x 160..168.

Landmarks visited (`out/playthrough_bil_sheet.png`, clip
`deliverables/gta2_linux_tour_residential.mp4`, 317 s, take 2 from the level start):

| # | place | how | views | seen |
|---|---|---|---|---|
| 1 | spawn plaza 44.5,102 | on foot | classic, third, first | people, the street below, the stained-glass church front |
| 2 | spawn road 44.5,108.5 | scene warp (car beside him; Return did not enter it: three tries) | third | the warped sedan on the road |
| 3 | railway station trak22st 47,59 | walked (the car failed) | third | pavement, traffic, people |
| 4 | map-hole spot (37,45) z3 | warp | third, first | no hole: a terrace between warehouse walls and the wooden fence |
| 5 | Azeri Heights Docks 80,17 | warp | third, first | quay paving, water beyond, traffic on the quay road, rule-placed containers, a crane |
| 6 | Krishna yard 140,246 z3 | warp | third, first | lawn, the crate blocks, hedges, a lamp |
| 7 | east lawn 227,163 z3 | warp (`tour_parks.py`) | third, first | a tree on the lawn (none before the grass fix) |
| 8 | Zaibatsu phone terrace 44.5,163.5 z3 | warp (`tour_bil_phone.py`) | third, first | the phone answered, "IT WAS AN ACCIDENT!" brief (key 4060) |

Mission: IT WAS AN ACCIDENT! (Zaibatsu green, `bil_ze1`). Answered by script (take 2 of
`tour_bil_phone`: the warp lands on the phone cell, so the brief is already up when the
runner reads its baseline; `tour_lib.answer` now accepts the mission's own text keys). The
first objective is the Special Package at 133,230.5 (90 blocks east). See "Mission attempts"
for the drive result.

## Industrial (`ste`)

Facts from the data:

- Player start 113.5,124.7 on the church plaza (`CHURCH_SINGING` at 113.5,123.5: the save
  church is the spawn). Information phones 199,25.5 and 47.5,49.5; final phone 211.5,219.5.
- Phones: Scientists green 234.5,202.5 (SINK OR SWIM!) and 235.5,202.5 (FAKE TRUCE!),
  yellow 206.5,227.5 / 206.5,228.5, red 222.5,221.5; Zaibatsu green 166.5,19.5 (SCIENCE
  FRICTION!) and 166.5,16.5 (FIRE TRUCK FUN!), yellow 224.5,34.5 / 225.5,34.5, red
  208.5,25.5; Rednecks green 18.5,68.5 (BLOW JOB!) and 18.5,67.5 (DOUBLE-CROSS CRUSH!),
  yellow 84.5,30.5 / 84.5,29.5, red 4.5,5.5.
- Zones: Rednecks W (0,0 79x110; 79,17; 100,25), Zaibatsu N/NE (115,0 140x85; 79,0),
  Scientists, `almagang` SW (0,218 52x36), `poligang` 80,113 (the police station by the
  spawn); the elevated railway runs N-S at x 119..122 (stations trak00st 121,122, trak11st
  120,133) and x 241..244, and N-S at x 62..65 in the south-west; seven bus stops; ten
  cranes (`CRANE_DATA`: 4.5,72.5 and 7.5,77.5 west docks; 240.5,69.5 / 238.5,64.5 east;
  191.5,228.5 / 195.5,224.5 and 197.5,245.5 south; 250.5,39.5; 55.5,48.5; 234.5,153.5);
  water at 112..128 x 16..32 (north), the west edge 0..16 x 192..224 and the south edge.

Landmarks visited (`out/playthrough_ste_sheet.png`, clip
`deliverables/gta2_linux_tour_industrial.mp4`, 354 s, take 2 from the level start):

| # | place | how | views | seen |
|---|---|---|---|---|
| 1 | church plaza 113.5,124.7 | on foot | classic, third, first | the church with stained glass, a corpse sprite and blood on the plaza, the scene car |
| 2 | rail station trak00st 121,122 | walked | third, first | the station building wall (the look spot faces it: open side not used) |
| 3 | road by the spawn 108.5,128.5 | scene warp, car entered (model 14) | third | |
| 4 | crane9 55.5,48.5 | driven, 104 s | chase, at the wheel | rail girders overhead, the crane, traffic |
| 5 | western docks road 25.5,70.5 | driven, 27 s | chase, at the wheel | |
| 6 | docks yard 9,72 and 20,70 | walked | third, first | sand yard, timber walls, crane1 beyond the fence, rail overhead |
| 7 | Rednecks' phone 18.5,67.5 | walked | third, first | phone answered, DOUBLE-CROSS CRUSH! brief (key 2803) |
| 8 | map-hole spot (160,8) z3.7 | warp | third, first | no hole: a teal road between tan walls |
| 9 | map-hole spot (216,22) z4 | warp | third, first | no hole; a lawn with trees; the grey block defect below |
| 10 | north terrace lawn 212,51 z3 / west lawn 27,107 z3 | warp (`tour_parks.py`) | third, first | trees along the lawn; the west lawn lies under the elevated rail |

Mission: DOUBLE-CROSS CRUSH! (Rednecks green, `ste_re2`). Answered by script, brief shown.
Its plan has no car or arrow (two counters must reach zero: rival gang kills); the runner
waited 45 s and left it running (`msg=2803`, money unchanged). Not completable by this
runner.

## Mission attempts

| district | mission | answered | progress | result |
|---|---|---|---|---|
| bil | IT WAS AN ACCIDENT! | yes (takes 2 and 3 of `tour_bil_phone`) | take 3 (`out/tour_bil_phone_bil`, clip `deliverables/gta2_linux_tour_residential_mission.mp4`, 219 s): phone answered on the terrace, brief, a car on the street below entered (model 44), 30 s of driving east (62 `driving` lines, first person at the wheel), stalled against a wall at 97,172, out, walked on to 144,219 (the package is at 133,230.5) | **JOB FAILED**: the game ended it with text 4217 "That's the job over for you, Gecko. Perhaps you need to work on your technique" at about 270 s, before the package was reached (take 2 ended "running": the drive controller started before the locator reported him driving; fixed in `tour_lib.drive`) |
| ste | DOUBLE-CROSS CRUSH! | yes | no navigable objective in the plan | running after 45 s |

The tours were coverage tours; neither mission was completed.

## Missions (7 Nov 2026, evening: `gamerun/mission_play_districts.py` on the v3 runner)

District files: `bil` is Industrial, `ste` is Residential. Runs on the fast path
(`gamerun/grun.sh`, `GTA2_FAST=0 SWAP_LEVEL=<file>`, 2400 s, devtools F9/F10 enabled, every
developer warp marked in `marks.txt`). Neither mission reached JOB COMPLETE; the table says
exactly where each attempt stopped and what was changed after it.

| run | district / job | reached | stopped because | change made after |
|---|---|---|---|---|
| `pd3_ste1` | Residential, BLOW JOB! (Rednecks green phone 18.5,68.5) | car to within 37 blocks of the phone; walker stuck on the way (10 re-routes) | the fallback warp landed on the phone cell itself and a warped-onto phone never rings ("phone not answered") | warp to a street cell beside the phone, walk the last stretch, step off and back on |
| `pd3_ste2` (earlier agent) | same | phone answered, Pickup entered, driven into the 3x1 block (game message 2005 "in the block") | the parking pulses pushed the Pickup back out (2004) and the fragile rigged car failed the job (2998) within a second | hold still once the game reports the block (`parked_msgs`); stage-2 messages mapped (2016 in, 2017 out) |
| `pd3_ste3` | same | phone approached from the west | a fence blocks the western approach at (14.5,64.5): 9 re-routes, 4 blocks short | south approach waypoint (18.5,100) for that phone, the route that worked in `pd3_ste2` |
| `pd3_ste4` | same | **phone answered on foot via the south approach**, Pickup entered (door warp after two honest tries), drive at the 2.0 crawl | the driver left the route and stopped 92 blocks from the block with damage 247/255; the stage loop then mis-read the car arrow as "stage 2" | re-drive to the block when the leg ends far from it; stage 2 only when the arrow moves away from the abandoned car or message 2012 shows; fifth attempt `pd3_ste5` |
| `pd3_ste5` | same | drive to the phone, south approach waypoint reached (with two reported pinned-walker warps from the shared walker) | after the waypoint the walker drifted east of the fenced plaza (stuck at 22.5,67 then pushed south by its unsticking moves) and never stepped on the phone; "phone not answered" | a second waypoint (18.5,78) keeps the walker on the x=18.5 street; sixth attempt `pd3_ste6` |
| `pd3_ste6` | same | both approach waypoints, phone answered (message 2001) | the walk to the Pickup never got near it: three reported pinned-walker warps around 130.5,103.5 (the walker's reported position after the street warp was 132.9,105 while the phone at 18.5,68.5 rang: a position read-back anomaly left open), "pickup 1 not entered" | none: the shared walker/warp library was changing under this stream (new `game=` mark field, pinned-walker warps from the Downtown stream); stopped here |
| `pd3_bil1` | Industrial, MMM, RUSSIAN SAILORS! (Russian green phone 189.5,76.5, level 6 rooftop) | drive bailed out 250 blocks from the phone, walker started a 255-cell walk | pre-fix script (warp onto the phone) | a second driving leg after a bail-out (`any_car2` again) |
| `pd3_bil2` | same | rooftop phone answered (street warp + step back on); on foot on the roof | the walker cannot get down from level 6 (stuck at L4/L5 for 5 min); the Z-Type (48,73) reached at the very end, two door tries, budget out | warp down to the street after a rooftop phone; door warp after two tries; enter budget 360 s |
| `pd3_bil3` | same | phone, Z-Type reached by car in 6 min and entered (door warp) | the Z-Type caught fire after wall hits at the 3.0 cap on the first dealer leg ("the car is on fire: out and clear") | crawl cap 2.0 for the Z-Type (`M.SLOW_CAP`) |
| `pd3_bil4` | same | phone answered, Z-Type entered (door warp), first dealer leg at the 2.0 crawl, 3 wall stalls | the Z-Type was wrecked with the player inside 8 min into the leg (message 4223 "What a disaster! Clearly you have no staying power, Comrade!", one life lost); renderer log: 0 faults | wait for the arrow to leave the car before reading the dealer target (the script read "dealer 1 at 48,73", the car's own cell, and drove in circles); fifth attempt `pd3_bil5` |
| `pd3_bil5` | same | phone answered after the rooftop street warp; no traffic car found for 4 min so the 150-block trip to the Z-Type went on foot | a door try near the walk's end put the player into a passing traffic car 90 blocks from the Z-Type; `enter_parked` took any "driving" state as success, so the script "drove to the dealers" in the wrong car while the arrow stayed on the parked Z-Type | `enter_parked` now accepts only a car at the mission car's cell; a hijacked car is driven to the mission car instead; sixth attempt `pd3_bil6` |
| `pd3_bil6` | same | phone answered (street warp), Z-Type trip by car, "wedged in traffic: leaving the jam on foot" | the walker's warps landed off target (130.5,124.5 reported at 139.1,143.9 level 4; 113.5,192.5 at 91.4,173.8) and the Z-Type was never reached; renderer log 0 faults | stopped here (same library churn) |

### What the runner can do in these districts (verified)

- Reach a far phone by car and on foot, including the Rednecks' fenced phone from the south
  and the Russians' rooftop phone (the latter only with the logged street warp beside it, then
  stepping onto it: a warp onto the phone cell never rings it).
- Read the mission's start from the title message or the arrow (`view: arrows`), enter the
  scripted mission car, drive it to the scripted block and get the game's "in the block"
  message (BLOW JOB, run `pd3_ste2`), and detect the outcome from the message field.
- Everything is recorded in the street views: third person on foot, first person for a stretch
  of every walk and every drive.

### Status after six attempts per district

Not completed in either district. Each attempt removed one failure mode and exposed the next:
phone cell warps, fenced approaches, fragile mission cars, parking pulses, stage detection,
the arrow's entry lag, a passing car accepted as the mission car, and finally the shared
walker's warp landings. The last two runs (`pd3_ste6`, `pd3_bil6`) ran on a shared
`mission_lib.py` that the Downtown stream was editing at the same time (the `game=` mark
field and the pinned-walker warps are theirs), so their failures are not attributable to this
runner alone. Next step for whoever continues: re-run `pd3_ste6`/`pd3_bil6` once the shared
library is stable, and treat the two remaining blockers below first.

### Why neither job completed (root causes, with evidence)

1. **Fragile mission cars + the driver's wall hits.** The rigged Pickup and the Z-Type are
   wrecked by the same collisions an ordinary traffic car survives. Even at the 2.0 crawl the
   driver (`mission_lib.drive3`) stalls against walls on these districts' narrower roads
   (`pd3_ste4`: damage 247 of 255 on arrival; `pd3_bil3`: fire). The Downtown stream is
   working on a wall-aware driver in the same library; these jobs should be re-run on it.
2. **Parking by pulses.** Nudging into a 3x1 block pushed the car out again; fixed by holding
   still on the game's own "in the block" message, not re-verified end to end.
3. **Stage detection by arrow kind.** After a failed park the arrow still points at the car,
   which the script took as the next stage's car; needs the message numbers as the stage
   signal (2012 announces stage 2).
4. **Rooftop phones.** Both gang phones chosen sit on raised blocks the walker cannot climb
   (ste: fenced plaza; bil: level 6); the honest route exists (stairs) but the router's slope
   handling did not find it here. The warps used are marked in every run.

### Files

`gamerun/mission_play_districts.py` (+ `keys_mission_districts.sh`, `districts_missions_sheet.py`),
`gamerun/mission_lib.py` (`SLOW_CAP`), mirrored in `linux/docker/`; sheet
`out/playthrough_districts_missions_sheet.png` (copy in `deliverables/`); clips
`deliverables/gta2_linux_playthrough_residential.mp4` and `..._industrial.mp4` (the furthest
attempts, cut from the level start); runs `out/pd3_ste1..4`, `out/pd3_bil1..4`.


## Missions, 8 Nov 2026 (`pt5_bil1`, `pt6_*`): the walker fixed, the jobs still lost to fragile cars

The district runner (`gamerun/mission_play_districts.py`, mirrored in `linux/docker/`) now runs on
the same primitives as the Downtown runner, and the attempts got much further than on 7 Nov.
District files as before: `bil` is Industrial (RUSSIAN SAILORS), `ste` is Residential
(BLOW JOB, the Rednecks' first job). All sessions `GTA2_SPEED=2`, `FPS=0`, devtools F9/F11.

### What was wrong, and what changed

- **The walker walked in the chase view.** The district runner never set `M.VIEW_HOOK`, so
  every walk ran in the third-person view, where the keys are remapped and the heading pulses
  barely turn him: pt5_bil1 spent 20 minutes of re-routes at the Industrial spawn and on the way
  to the Z-Type, and pinned-walker warps "landed" 20 blocks off. Now the hook is set and every
  on-foot move takes the classic view (`ensure_view`, shared with Downtown); the first-person
  stretch at the start of each walk is gone (first person is at the wheel). pt6_bil1/2/4
  answered the Russians' rooftop phone on foot or by car, with no warp.
- **The dealer arrow is a character arrow** (kind 2). Only kinds 3/4 were taken for dealers, so
  pt6_bil1 sat three minutes in the Z-Type with the dealer arrow up. Kind 2 is a dealer now,
  an unknown kind is logged, and a dealer counts as aboard as soon as the arrow moves to the next
  one (the one-second "aboard" brief 3527 was missed and the runner waited 100 s at each dealer).
- **The warp down from the rooftop phone killed him.** pt6_bil4 answered RUSSIAN SAILORS on the
  level-6 roof, was warped to the street and died four seconds later (lives 5 -> 4, message 4223,
  JOB FAILED): to the game it was a fall. The roof is a car park (the runner drove up to two
  blocks from the phone), so the warp is used only when no car stands by; the car drives down.
- **The car bomb escape.** pt6_ste1 parked the rigged Pickup in the block, armed it (2006) and
  died in the blast three seconds after getting out: `leave_car`'s two-second wait is most of the
  fuse, and the escape ran seven blocks in a fixed direction along the trailer the script blows
  up. Now Enter and run at once, a routed path ten blocks away from the blast centre.
  pt6_ste2 survived stage 1 this way (2006, then 2012: stage 2).
- **Lost cars far from the Z-Type**: the runner drives again (up to four legs) instead of a
  417-cell walk (pt6_bil3).
- **Ramps and corners**: a car pays a ramp's ground cost (pt6_ste2's Pickup was routed down a
  grass ramp off the carriageway) and a corner waypoint is taken within 0.8 block instead of 1.4
  (the early turn's diagonal cut the ramp at 62,24).
- **Carjack and arrest.** A car taken at a kerb in front of a cop gives wanted level 1; sitting in
  it through the view change got the player arrested and moved to the police station (pt6_le2d:
  the locator then followed the new player ped 50 blocks away, which looked like a teleport). After
  a carjack with a wanted level the runner pulls away at once.

### Runs

| session | district / job | reached | stopped because |
|---|---|---|---|
| pt5_bil1 (previous agent) | Industrial, RUSSIAN SAILORS | phone (after 20 min at the spawn), 13 blocks from the Z-Type | the walker walked in the chase view: re-routes all session, "stuck: the Z-Type not entered" |
| pt6_bil1 | same | **phone answered on foot**, Z-Type entered (F9 door warp after two honest door tries, reported) | sat 3 min in the Z-Type with the dealer's kind-2 arrow up (fixed); stopped by hand |
| pt6_bil2 | same | phone, Z-Type, **dealers 1 and 2 aboard** (3527/3528, 3529/3530) | on the leg to dealer 3 (13.5,233.5) the Z-Type burned for 15 s on the elevated road (shot_985-995; `fire=0` in the log) and exploded: 3523/3730 "You destroyed the Z-Type", JOB FAILED |
| pt6_bil3 | same | phone; the borrowed car lost 140 blocks out | a 417-cell walk to the Z-Type (fixed: drive again), then an F9 door warp put him in another car; the job failed meanwhile (4222) |
| pt6_bil4 | same | phone answered on the rooftop (title 3855) after driving up to it | the warp down from the roof killed him four seconds later (4223, JOB FAILED; fixed: drive down) |
| pt6_bil5 | same | - | no car at the Industrial spawn (the nearest parked car is the XK120 on the terrace one level up), a 300-cell walk to the phone; stopped by hand |
| pt6_ste1 | Residential, BLOW JOB | phone (approach from the south), Pickup 1 into the block (2005), armed (2006), **stage 2 announced (2012)** | killed in the bomb's blast 3 s after getting out (fixed: out at once, routed escape away from the blast); then four deaths near the hospital and "pickup 2 not entered" |
| pt6_ste2 | same | phone, Pickup 1 into the block, armed, **survived the blast** (escape 37.5,22.5), stage 2: Pickup 2 entered | the drive to the second block (110.5,77.5) left the carriageway at the corner 61,23 down a grass ramp into a walled field, 15 stalls, the rigged Pickup was wrecked (2998, JOB FAILED; fixed: ramp cost, corner waypoints at 0.8) |
| pt6_ste3 | same | the phone pair | the walk overshot onto the neighbouring phone: DOUBLE-CROSS CRUSH! (2803) started instead (fixed: stop 1.5 blocks short on the approach side and nudge on) |
| pt6_ste4 | same | phone, Pickup 1 parked (2005), armed (2006), survived; **stage 2**: Pickup 2 driven to the barricade block, in the block (2016), **armed (2018)** | 11 stalls at the corner 86-89 x 24-26 had set the rigged Pickup burning before it was parked (frame `m_ste_re1_block2.png`); three seconds after arming it was wrecked outside the counted area (2998, JOB FAILED) and the player, two V presses into his escape, died in the blast (fixed: the classic view is taken before arming) |
| pt6_ste5 | same | phone, Pickup 1 | the Pickup left the road at 63.5,24.6 again, six stalls, wrecked (2998) |
| pt6_ste6 | same | phone, stage 1 parked, armed, survived, stage 2 Pickup entered | the Pickup stands on grass at 24,44.5 with no road within 35 cells; after the lawn the drive left the x=60-61 carriageway into the walled field at 63-83 x 24-35 (stalls at 65-72 x 31-33), the car was lost (2015) before the block. Fixed after the run: the off-road fallback route makes the lawn the car stands on expensive (30) so it only crosses it to reach the road; not re-run |
| pt6_bil6 | Industrial, RUSSIAN SAILORS | phone (title 3855), warp down survived this time | died on the way to the phone once already and twice more driving to the Z-Type (lives 5 -> 2); the borrowed cars were lost 96 and 170 blocks out; stopped by hand |

### Status

Neither job reached JOB COMPLETE. BLOW JOB got furthest: both stages parked and armed in
pt6_ste4, lost to a rigged Pickup that had started burning from wall hits on the way. RUSSIAN
SAILORS got two of four dealers aboard in pt6_bil2, lost to a Z-Type that burned the same way.
The common blocker is the one Downtown has: the runner cannot see that a car is burning
(`cardmg` is not the damage, the flame detector misses car fires), and the crawl-speed driver
still stalls against kerbs and walls at corners and ramp feet, which is what sets the fragile
mission cars alight. Second blocker in Industrial: the player dies or is arrested on the way more
often than not (pt6_bil4/5/6), and the drives to the Z-Type (130+ blocks from the rooftop phone)
lose their car.

Evidence: `out/pt6_ste4/m_ste_re1_*.png` (phone, both Pickups, both blocks, the blast),
`out/pt6_bil2/m_bil_re2_*.png` and `shot_985..1000.png` (dealers, the burning Z-Type, the
failure brief), sheet `out/playthrough_5_sheet.png`.

## Defects found

Fixed (uncommitted):

1. **No trees in Residential or Industrial.** The grass classifier (`world_view.cpp`,
   level load) wanted green over red; Residential's lawns alternate a sun-dried tile
   (202: 86/87/45) with a greener one (216: 78/89/42), so the four-neighbour lawn test never
   passed (log: `14100 grass cells seen, 0 trees placed`; offline: 256 lawn cells in bil,
   0 in ste). Now `g + 2 >= r && r < 112 && g > b + 28 && g < 140`: bil 361 lawn cells,
   ste 375, wil unchanged (298). In game: bil 3000 trees placed per 300 frames at the east
   lawn, ste 4500 at the north terrace (`out/tour_parks_*`, sheet rows 3-4). The new tiles
   were checked by eye (`out/grass_candidates_{bil,ste}.png`): olive grass, grass with
   paths, hedges; Industrial 172/173 are green window faces, harmless as lids are the test.
2. Tour tooling: confirmed warps with retry, death detection after a drive, on-foot
   confirmation before warps and first-person looks (take 1 of Industrial died at the
   western docks and the respawn's Return put him into a parked car, so every later frame
   was from inside it), a wait for the driving state before the drive controller.

Second pass (7 Nov, TOUR-FIXES; evidence `out/tour_fixes_sheet.png`):

1. **Pay-phone model: fixed.** The hooded "slab on a post" is now an upright kiosk
   (`tools/gen_code_objects.py build_phone`: four steel posts, blue steel panels to waist
   height, glass above, the sprite as the roof, the phone unit on the back wall; 0.5 blocks
   tall, a head over a person). The fit in `map_objects.cpp` was right all along (the quad is
   0.50 x 0.47 and the model's long axis is scaled onto it); the previous model itself was a
   wide flat hood. Verified at the Downtown spawn phone in third person
   (`out/qa_tf_wil/qa_tf_wil_phone_third_a.png`, zoom `out/tf_booth_zoom.png`); the phone's
   footprint is registered for the first-person eye push-out (`MapObjectFootprints`). Traffic
   lights and the helicopter were left as they were (their fit is the same transform).
2. **Plain grey faces at Industrial (216,22) z4: not a defect.** The map stores that cell as a
   one-block tower with tile 501 on all four sides and lid 581; tile 501 is a plain light-grey
   concrete tile in the game's own art (`out/tf_tiles_501.png`: 501, 581, 589, 587 from the
   style file). The mesh draws exactly what the game stores; no hidden-surface or implicit
   wall is involved (the column below it has no faces, and no neighbour is lower). Closed.
3. **Chain-link and railing cutouts: fixed.** `tools/pack_textures_dds.py soft_alpha` upscales
   the 1-bit mask bicubically and steepens it to a ~1.5 px edge; the 736 cutout tiles of the
   three districts were re-packed. Verified in first person at the Residential park fence
   (`out/qa_tf_bil/qa_tf_bil_fence_first_1.png`, `..._closer.png`: smooth diamonds) and at the
   Downtown kerb railing (`out/tf_railing_zoom.png`: clean bars, no 8 px steps).
4. **Scene-warp car at the Residential spawn road: see below.** The first cause found: the
   nearest parked car there is the script's XK120 parked on a terrace one level up
   (45.5,92.5,3); moved onto the road it kept the game's idea of its level and Return did
   nothing. `WarpSceneToRoad` now picks the nearest driverless car on the scene's own level
   whose model is an ordinary traffic car (`NearestParkedTrafficCar`, no wrecks, trains,
   trailers, tank, specials). That was not enough: a level-2 traffic car brought 22 tiles to the same
   road could not be entered either (`out/qa_tf_bil3`), while F9 (the player warped to a
   parked car where it stands) entered the terrace XK120 at the first Return (`out/qa_tf_bil2`,
   `qa_tf_bil3`). A car moved by writing its placement keeps its old place in the game's own
   bookkeeping. So the scene warp no longer moves cars: it takes the player to the driver's
   door of the nearest parked traffic car that stands on a road around the scene
   (`NearestParkedTrafficCarOnRoad`, within 40 blocks, any level), logged as
   `devtools: scene ...: the player goes to the parked car at ...`. Verified: scene 44.5,110.5
   put him at the XK120 (16 tiles off), Return entered it at once, drove in third and first
   person (`out/qa_tf_bil4`, sheet row 4). Scripts should expect the player to be moved to a
   car near the scene rather than at it. Also found: F10 is shared with the probe feature and
   a press can be swallowed; the QA runs use `scene_key=F11` (`QA_SED`).
5. **Containers on the pedestrian quay: fixed by rule.** `DrawProps` places containers and
   cranes only on dock yards: the cell and the two cells behind it are plain or field lids
   (never pavement, road or grass), nothing stands within a block and no road runs beside
   (the Azeri Heights promenade is pavement between the river and a road, so it gets none).
   Verified at the Azeri Heights promenade (80.5,20.5): `containers 0` in the
   props log and clear quay frames (`out/qa_tf_bil4`, sheet row 5; before: `out/tour_bil`).
   No cell that satisfies the yard rule was visited in these runs, so containers and cranes
   appearing on a true yard is unverified in game; offline the rule qualifies 2 plain-lid
   waterside cells in wil, 12 in bil and 29 in ste.
6. The Industrial station look spot: script only; not changed here.

Note on names: the game's own welcome text says file `bil` is the **Industrial** district
("home to the Russian Mafia, the Krishna and the Zaibatsu") and file `ste` is **Residential**
("the Rednecks, the Scientists, the Zaibatsu"; the Mobile RV Park). This document's section
titles have them the other way round; the file names are what the scripts use.

Not a defect, noted: the "park" in Residential is the Krishna commune yard (grass with the
crate blocks) and an east lawn; there is no park zone. Industrial's west lawn lies under the
elevated rail girders, which read correctly from below. Both maps' lidless-ground and
deck-underside holes were revisited at three listed spots (37,45; 160,8; 216,22) and none
showed a void. Pedestrian types seen by the renderer in these runs: Residential mugger,
police, Russian, Krishna, Zaibatsu, Elvis and civilians; Industrial scientist, redneck,
mugger, police, Zaibatsu and civilians (the log's `remap N -> type` lines).

Frame times (4-CPU container, L4): Residential game 6.2/13.4 ms, world 1.5, sprites
3.9-5.5/11.4, wait 20-21 (at the cap); Industrial game 9.1/12.6, world 1.7, sprites
2.4-2.8/7.0, wait 19-20. Car-model textures 344.8 MB managed in both. 0 faults in all
eleven runs.

## Missions, 8 Nov 2026 (PLAYTHROUGH-7, `pt7_ste*`, `pt7_bil*`): BLOW JOB complete in the chase view

Same runner (`gamerun/mission_play_districts.py`, mirrored in `linux/docker/`), now on the two
fixes described in `playthrough-downtown.md` Part 6: the car's condition from the game
(`carhp`/`carfire`/`tcarhp` in the `view: mission` line, `actions-3d.md` "Vehicle fields") and
`GTA2_DIRECT_KEYS=1` (the game's own keys in the 3D views, every on-foot move in the chase view,
no classic-view frames). All sessions `GTA2_SPEED=2`, `FPS=0`, `GTA2DX9_STATE_EVERY=5`, devtools
F9/F11, private stage `stage_pt7`. District files as before: `ste` is Residential (BLOW JOB),
`bil` Industrial (RUSSIAN SAILORS).

### What the runs showed, and what changed

- **The police, not the Pickup, were the main danger in BLOW JOB.** Stage 1's blast gives wanted
  level 1 (pt7_ste2: wanted 1 three seconds after 2006, every session since). It did not go in
  150 game seconds of standing still (pt7_ste2, pt7_ste3), and with it the crawling second Pickup
  was stopped by a police car and the player pulled out and arrested (pt7_ste1 at 109,65 a block
  from the barricade, pt7_ste4 at 100,41: messages 6159/6155 "I hope the Cops...", JOB FAILED).
  Now: with a wanted level a mission car is driven at 3.2 blocks/s while carhp >= 22000 (2.0
  below), and a stall is backed out of at once instead of after a two-second wait for traffic.
  (`lie_low` still waits up to `LIE_LOW_SECS`, 20 s, and logs whether the level went.)
- **Down reverses a stopped car out of the block.** `park_in_block` held Down for 0.3 s on the
  game's "in the block" message, and every `drive3` ended with Down for 0.8 s: pt7_ste2's Pickup
  rolled back out of the barricade block (2016, then 2017 "That was the right place, Rooster. Get
  back and park"), the runner fired anyway and the bomb went off outside with him in it (2998, a
  life). Now a mission car stops on the handbrake (Space), and the arming refuses to fire while
  the last message is 2004/2017.
- **The barricade block counts a car lying along it.** pt7_ste3's Pickup drove through the 3x1
  block (110.5,77.5; road row 77 with the barricade in cell 111) facing north, the game said 2016
  then 2017 within 0.3 s, and the car stopped at 110.43,77.70, half outside: nothing more
  happened. `APPROACH_BLOCK` lines the car up on row 77 from the west (106.5,77.5) and creeps to
  x=110 (pt7_ste5 reached the block on the plain route after that line-up, and held it).
- **The Russians' rooftop phone** (189.5,76.5, level 6): the router's south stair (x=189, y 85..78)
  does not go through at its top (pt7_bil1: four minutes at 189.6,79.3) and neither does the west
  one (row 77, pt7_bil2 stuck on its second step). Those cells are in `M.BLOCKED` for `bil`; the
  north stair (x=187, y 67..74) is the way up (pt7_bil3: phone answered on foot, title 3855).
- **The wrong car beside the Z-Type.** pt7_bil3's borrowed car arrived at speed, rammed the
  Z-Type three times (`tcarhp` would have shown 28756 -> 25994) and stopped three blocks from it;
  `enter_parked` accepted any car within four blocks, Return put him back into the borrowed car,
  and the dealer loop drove nowhere for five minutes with the arrow on the Z-Type. Now the drive
  stops nine blocks short, and a car is the mission car only when the mission line's `tcar` (the
  target car's position) is under him.
- **No car stops at the kerb** (pt7_bil4: four legs, eight minutes, at one kerb 86 blocks from the
  Z-Type): after one failed wait the runner walks to the Z-Type.

### Runs

| session | job | reached | stopped because |
|---|---|---|---|
| pt7_ste1 | BLOW JOB | phone, Pickup 1 parked (2005), armed (2006), survived; Pickup 2 driven to within a block of the barricade | wanted level 1 from the blast; a police car stopped the Pickup at 109,65 and he was arrested (6159), JOB FAILED |
| pt7_ste2 | same | stage 1 as above; the 150 s lie-low (wanted stayed 1); Pickup 2 into the barricade block (2016) | the stop's Down reversed it out (2017), the bomb went off outside with him in it (2998, lives 5 -> 4) |
| pt7_ste3 | same | stage 1; Pickup 2 through the block facing north (2016, 2017), stopped half in it | no further reaction; the stale 2017 kept the new arming guard from firing; stopped by hand |
| pt7_ste4 | same | stage 1; the line-up leg to 106.5,77.5 | arrested at 100,41 on the way (6155), JOB FAILED |
| **pt7_ste5** | **BLOW JOB** | phone (south approach), Pickup 1 into the block (2005), armed (2006), escaped; Pickup 2 (wanted 1, cap 3.2) into the barricade block (2016), held on the handbrake, armed (2018), out | **Mission Complete (2999)**, +$30,000 at game-second 947 (`out/pt7_ste5/shot_570.png`: the payoff brief "Yee-ha! ... Here's $30,000" over the chase view, money 32878). Two seconds later the blast killed the player (lives 5 -> 4) after the job had paid |
| pt7_bil1 | RUSSIAN SAILORS | drive to the rooftop car park, phone 3 blocks off | the walker stuck at the south stair's top for four minutes (fixed: `BLOCKED`) |
| pt7_bil2 | same | | stuck on the west stair (fixed as above) |
| pt7_bil3 | same | **phone answered on foot** by the north stair (3855), the warp down survived, a car to the Z-Type | rammed the Z-Type, re-entered the borrowed car beside it, the dealer loop never started (fixed: tcar check, stop short) |
| pt7_bil4 | same | phone | no car stopped at the kerb for eight minutes (fixed: walk) |
| pt7_bil5 | same | phone | a police car stopped beside him at a kerb and `any_car` took it: the wanted level rose and every car after it was rammed to burning within a minute (fixed: police models 12/52/54/17/34 are never jacked) |
| pt7_bil6 | same | phone (north stair), warp down, the Z-Type by car, **dealers 1 and 2 aboard** (3527/3528, 3529/3530) | dealer 3 at the Escobar Power Cores (13.5,233.5) did not come to the Z-Type standing two blocks off; the stale 3530 in the message buffer was taken for "aboard", the runner moved on and left the car (fixed: only a fresh brief counts, the car is moved round a dealer who does not come, the same dealer again when he is not aboard) |
| pt7_bil7/8 | same | phone | cars lost on the way to the Z-Type: carhp 1000 every 0.3 s on the spot at 173,35 and 156,61 (pressed against something at full throttle) until they burned; a burning car that stopped beside him was re-entered eight times (fixed: back out when carhp falls 2500 in a second on the spot; burning cars are never taken, from the kerb either) |
| **pt7_bil9** | same | phone, the Z-Type, **all four dealers aboard** (dealer 3 at once this time, dealer 4 by 06:12:36) | the Z-Type had caught fire on the dealer-4 leg (stalls against walls at 24,223, 136,150 and 130,110 cost 5000-6000 carhp each) and reached the crane leg at carhp 3666, 122 s before the explosion, with the crane box (135.5,5.5) 200 blocks off: out and clear, then 3523 "You destroyed the Z-Type", JOB FAILED. Frames `out/pt7_bil9/m_bil_re2_*.png` (the burning Z-Type at dealer 4, the explosion behind the JOB FAILED banner) |
| pt7_bil10 | same | phone, Z-Type, dealer 1 | the Z-Type burned out early (carhp 1795 on the way to dealer 2) |

### Status (PLAYTHROUGH-7)

- **BLOW JOB: Mission Complete** (pt7_ste5), both stages in the chase view: the second Pickup
  driven to the barricade with the police after it, held in the block on the handbrake, armed,
  +$30,000 (frame `out/pt7_ste5/shot_570.png`).
- **RUSSIAN SAILORS: not completed.** Furthest: all four dealers aboard (pt7_bil9; pt6 got two),
  lost to a Z-Type that had been set alight against walls on the 134-block dealer-4 leg and had
  2 minutes left for the 200-block crane leg. With `tcarhp` the runner now sees that coming; what
  would finish it is fewer wall hits on the long Industrial legs (the stall pull-out still pushes
  into the obstacle before it reverses) or a respray on the way, which was not looked for.

## Missions, 8 Nov 2026 (PLAYTHROUGH-8, `pt8_bil*`, `pt8_ste*`): protecting the Z-Type

Same runner (`gamerun/mission_play_districts.py` and `mission_lib.py`, mirrored in
`linux/docker/`), `GTA2_SPEED=2`, `GTA2_DIRECT_KEYS=1` (driving in the chase view, walking in third
person, every frame 3D), `FPS=0`, `GTA2DX9_STATE_EVERY=5`, devtools F9/F11, private stage
`stage_pt8`. The common runner changes of this pass (the walk round the car, the router's
`EDGE_COST`, `back_toward`, the game-time timeouts) are described in `playthrough-downtown.md`
Part 7.

### What the logs showed (pt7_bil9 and this pass)

- **The Z-Type was not lost to wall scrapes but to pressing**: in pt7_bil9 it lost 4500 in 7 s
  against the railing at the Escobar Power Cores (23.5,223.4), 5000 in one second against a
  gantry pole on the pavement (135.9,149.5) and 5000 in 8 s against a wall at 130.5,110 (frames
  `out/pt7_bil9/shot_585/675/700.png`): a car standing still with the throttle on, at a few
  hundred carhp a sample, too slow for the old "2500 in 1.2 s" guard, and the stall branch then
  pulled out with the throttle and the wheel turned, into the same obstacle.
- **The Z-Type stands in a two-wide alley** (47-48 x 67-78, facing south), whose way out south is
  one block wide between a slope and a wall: pt8_bil4 pressed it eight times there before the
  first dealer (31847 -> 15905, alight).
- **Driving to a dealer's own cell runs him over** (pt8_bil2: dealer 2 stands on the pavement at
  46,187; the drive's goal was his cell, 3526 "sound the horn" and 3730 JOB FAILED came in the
  same second). The passenger box is `LOCATE_ANOTHER_CHARACTER_BY_CAR(p1, dealer, 3.0, 3.0)`, so
  the car has to be within about 1.5 blocks of him on each axis: a stop 1.5 off on each axis
  (pt8_bil5) never got him aboard, and the "not coming" spots round him then drove the car onto
  the raised field south of him (188-190) and set it alight.
- **The borrowed car beside the Z-Type**: pt8_bil3's borrowed car stood a block from the Z-Type
  (48.5,74.0 against 47.9,71.8) and all nine door tries entered it; the runner left it each time.

### Runner changes

- **Pressed cars** (`drive3`): any 450 carhp lost within 0.8 game seconds on the spot (any car
  except a timed race): off the throttle, back off with the wheel turned toward the next waypoint
  (`back_toward`), the two cells ahead off the route (`CAR_AVOID`), re-route. A stalled mission
  car never pulls out with the throttle: a short wait for traffic, then the same back-off.
- **Out of the alley first** (`play_bil_re2`): the Z-Type backs straight out north to the road on
  rows 65-66 before the first dealer leg, and the alley's cells go on `CAR_AVOID`.
- **`dealer_stop`**: the car stops 0.9-1.1 blocks from the dealer on each axis, on flat ground at
  his level, a road point preferred, the point nearest the car (approach tolerance 0.6); the
  "not coming" spots round him use the same rule, so they never leave his level.
- **The wrong car beside the mission car** is driven eight blocks away from the Z-Type (its
  position is `tcar` from the mission line) and given up (`BAD_CARS`), and the door tries aim at
  `tcar`, not at the nearest parked car.
- **BLOW JOB's first block** (48.5,20.5, 3x1, by the trailer) is approached along row 20 from the
  east (`APPROACH_BLOCK`), and a "get back and park" (2004/2017) re-parks with that line-up
  instead of a creep from where the car stands (pt8_ste1 re-armed four times in place).
- **The way to the Z-Type is walked** (`RS_WALK=1`, default): the borrowed cars on the 140
  blocks from the rooftop phone burned two or three times a session (pt8_bil5/6/8/9, 5-10 minutes
  of wall time each); the walker takes about three minutes (pt8_bil10: 315 cells).
- A burning car's time left is carhp/100 game seconds (measured, pt8_bil11: 15969 -> 5894 in
  102 s), not carhp/30; after an arrest the arrow on the Z-Type comes back as kind 0 without
  3525 and is now taken for "back to the Z-Type" (pt8_bil10 said "not handled" for minutes).

### Runs

| session | job | reached | stopped because |
|---|---|---|---|
| pt8_bil1 | RUSSIAN SAILORS | phone, Z-Type, dealers 1-2 aboard, dealer 3 aboard as the car burned | pressed five times at 76.1,214.5 (heading south a block west of the narrow road 77-78 into the Power Cores, against the raised field corner at 75,215; straight back and the same line again): 23455 -> 15930, alight, JOB FAILED (fixed: `back_toward`) |
| pt8_bil2 | same | phone, Z-Type, dealer 1 | **ran dealer 2 over**: the drive's goal was his own pavement cell (46,187); 3526 and 3730 in the same second (fixed: `dealer_stop`) |
| pt8_bil3 | same | phone | nine door tries into the borrowed car parked a block from the Z-Type (fixed: drive it away, doors at `tcar`); stopped |
| pt8_bil4 | same | phone, Z-Type | pressed eight times in the Z-Type's alley before dealer 1 (31847 -> 15905; frames `out/pt8_bil4/shot_860-875.png`, a van in the one-wide way out); stopped (fixed: back out north) |
| pt8_bil5 | same, then HOT DOG HOMICIDE | phone, Z-Type, dealer 1 | dealer 2 never came to a stop 1.5 blocks off on each axis; the "not coming" spot drove onto the raised field south of him, the car burned, JOB FAILED. Then the HOT DOG HOMICIDE phone (187.5,76.5): **answered with 3104, "Respect the Russian Mafia!"** (a refusal after the failed job; frame `out/pt8_bil5/m_bil_re1_phone.png`) |
| pt8_bil6/8/9 | same | phone (bil6: Z-Type, the back-out did not move) | bil6: the alley on the avoid list with the car still in it left the router no way out and drive3 fell back to a straight line (fixed: avoid only once out; drive3 retries without the avoid list); bil8/9: stopped after three borrowed cars burned on the way to the Z-Type (fixed: walk) |
| pt8_bil10 | same | walked to the Z-Type (3 min), **backed out of the alley** (48.4,63.6, carhp 31478), dealer 1 | wanted level 1 on the dealer-1 leg, arrested out of the Z-Type near dealer 1; the arrow came back as kind 0 (fixed) |
| **pt8_bil11** | same | phone, Z-Type, **all four dealers aboard** (dealer 2 after 74 s and three spots, dealer 3 at the Power Cores, dealer 4 as the car burned) | carhp 20273 after the Power Cores deck (a stall and a press at 26.3,223.6, the turn into the two-wide road at 26-27); alight at the start of the dealer-4 leg, which the road router sends round a 358-block loop (the direct way, column 90-93, is cut by a raised embankment at rows 158-166); out and clear, JOB FAILED. Frames `out/pt8_bil11/m_bil_re2_dealer1-4.png` (the Z-Type at each dealer, chase view) |
| pt8_bil12 | same | | the phone said 3103 (a Russian refusal: a Russian run over on the way, presumably) |
| pt8_ste1 | BLOW JOB | phone, Pickup 1 to the trailer block | the Pickup stopped half west of the block (2005, then 2004) and the arming loop re-armed in place four times (fixed: `APPROACH_BLOCK` for 48.5,20.5, re-park with the line-up); stopped |
| pt8_ste2 | BLOW JOB, DOUBLE-CROSS CRUSH | phone, **stage 1 parked by the line-up (2005), armed (2006), escaped**; Pickup 2 entered | Pickup 2 pinned at 62.7,23.5 on the way to the barricade (five stalls, three times), alight, WASTED; then DOUBLE-CROSS CRUSH's phone was not answered (the BLOW JOB job still counted as running) |
| pt8_ste3 | DOUBLE-CROSS CRUSH (fresh game) | **phone answered** (title 2803), frame `out/pt8_ste3/m_ste_re2_phone.png` (first person; the brief on screen is BLOW JOB's, the neighbouring phone at 18.5,68.5 answered as well) | no runner: the job wants a Zaibatsu Z-Type stolen from traffic, then seven Scientists run over in their zone (227.5,217.5) and eight Zaibatsu with a Stratos-B (199,25.5) under a bonus count; the renderer's mission line gives no pedestrian positions, so there is nothing to aim the car at |
| pt8_respray2 | respray probe | a borrowed car (carhp 25464, $20) driven into Industrial's numeric car shop at 64.5,90.5 (`bil.mis` shop12, `CAR_SHOP 0`; the BANK ROBBERY respray in Downtown is the same kind, `CAR_SHOP 9`) and held there 12 game seconds | no repair: carhp and money unchanged (`out/pt8_respray2/m_in_shop.png`, first person inside the shop); a respray costs money the player does not have this early, so it is no way to save the Z-Type here |
| pt8_bil13/14 | RUSSIAN SAILORS | walked to the Z-Type, backed out, dealers 1-3 (bil14) | the dealer-1 road's flyover (columns 54-57, a two-wide level-2 deck between ramps at rows 141-148 and 158-165): eight stalls at its south end (55-57,157) in both sessions, -10000 carhp, the Z-Type alight before dealer 2 (fixed: the flyover is off the Z-Type's route, the route runs down columns 66-68) |
| pt8_bil15/16 | same | | both waited minutes at kerbs for a car to the phone; stopped (fixed: Industrial's phone is walked to, `PHONE_WALK`, about four minutes for 147 blocks) |
| pt8_bil17/18 | same | walked to the rooftop phone | the phone said 3103, which e.gxt reads as "You are working a Russian contract, Comrade. Return when it is finished.": the first step had started the job and its title was missed; the runner called it "not answered" and moved on (fixed: 3103 means this job runs) |
| pt8_bil19 | same | phone by walking (2 min), Z-Type by walking, out of the alley, **dealer 1 aboard** | wanted level 1 on the way; on the dealer-2 leg the police pulled him out of the Z-Type at a standstill: **BUSTED** (`out/pt8_bil19/shot_625.png`), the game said "Get back in the Z-Type NOW!" (3525) and the job ran on, but the runner read the arrest word as a death and gave up (fixed: `not_over`, a bust or a respawn with the job still running goes back to the Z-Type) |
| pt8_bil20 | same | phone, Z-Type, out of the alley, dealers 1-2 | stalls on the turns south of the alley (48-50,84-87) and on the western detour round the flyover; alight at 16927 before dealer 3 |
| pt8_bil21 | same | phone (3103, now taken as the running job) | the walk from the rooftop to the Z-Type did not get there in its budget; then a crash in the phone approach for HOT DOG HOMICIDE (no position line; guarded) |
| pt8_bil22 | same | phone, Z-Type, out of the alley | one hit of 7000 at 70.9,91.6 on the dealer-1 road, in the car-shop strip (bomb, mines, oil, gun and respray drive-ins at 58-70 x 88-92); alight before dealer 1 (fixed: the strip is off the Z-Type's route) |

### Status (PLAYTHROUGH-8)

- **RUSSIAN SAILORS: not completed.** Furthest this pass: all four dealers aboard again
  (pt8_bil11), with the car alight at the start of the dealer-4 leg. The runner now protects the
  Z-Type from what the logs showed wrecking it: pressing (back off toward the route after 450 lost
  on the spot), its alley (backed out north), the passenger box (stops inside it, never on the
  dealer), the flyover and the car-shop strip on the dealer-1 road (off the route), walls and
  drops beside the lanes (`EDGE_COST`), a bust (the job runs on). What still burns it: traffic
  and the police on legs of 100-360 blocks at 2 blocks/s (the dealer-4 leg goes round a
  358-block loop because a raised embankment cuts the direct road at rows 158-166), and a
  respray is not to be had without money. The start (spawn, rooftop phone, Z-Type) is now walked:
  about 2-4 minutes to the phone and 3-5 to the Z-Type at `GTA2_SPEED=2`.
- **HOT DOG HOMICIDE** (Industrial's next Russian job, `bil_re1`): the phone answers 3104 "Respect
  the Russian Mafia!" after a failed RUSSIAN SAILORS (pt8_bil5); it has no runner (a bus to steal
  from traffic and fill at bus stops, then a stand on The Cage).
- **DOUBLE-CROSS CRUSH** (Residential's next Redneck job, `ste_re2`): phone answered in a fresh game
  (pt8_ste3); no runner (pedestrians to run over by gang, which the mission line does not give).
- **BLOW JOB**: stage 1 now parks and arms on the line-up (pt8_ste2); stage 2 lost to a pinned
  Pickup on the way to the barricade; completed once in pt7_ste5.

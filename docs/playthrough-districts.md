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

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

Open (evidence paths):

1. **Pay-phone model lies on its side.** The code-object phone (base 4 frames 510-512,
   `code_phone`) is drawn as a wide blue slab with the sprite face on its end; the player
   stands on it when answering (`out/tour_ste/t_10_phone_answered.png`,
   `out/tour_bil_phone_take2/t_21_phone_answered.png`; also QA2's mission panel). The quad
   is 0.50 x 0.47 tiles, so the fit in `map_objects.cpp` is right; the GLB's up axis or
   `forward` from `tools/gen_code_objects.py` is not. Owner: code objects.
2. **Plain grey block faces at Industrial (216,22) z4.** A building-sized cube with
   untextured light-grey sides next to the glass-roofed hall
   (`out/tour_ste/t_13_hole_216_22_third_b.png`): looks like the implicit base walls or
   hidden surfaces (`world_mesh.cpp`) textured with a plain lid tile on all four sides.
   Owner: world mesh.
3. **Chain-link fence tiles are blocky at 512 px.** The cutout alpha of the fence HD tiles
   is a 64 px mask scaled up (`out/tour_bil_take1/t_12_park_first_a.png`). Owner: HD tiles
   (a sharper alpha from the ESRGAN output, or a cutout pass).
4. **Scene warp car not enterable at the Residential spawn road**: the car was placed at
   44.5,109.05 and the player at its door, three Returns did nothing
   (`out/tour_bil/t_05_car_arrives.png`; devtools line 23:59:10). Not seen in Industrial.
5. Rule-placed containers stand on the docks' pedestrian quay at Azeri Heights (one in
   the middle of the walkway, `out/tour_bil/t_10_river_third_a.png`): plausible for a dock,
   but the rule should prefer the dock side of the quay. Owner: props.
6. The Industrial station look spot (119.5,122.5) faces the station wall in all four
   first-person frames; the tour should look from the open side (script, not renderer).

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

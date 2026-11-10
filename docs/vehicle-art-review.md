# Vehicle art review (9 Nov 2026, VEHICLE-REVIEW)

Audit of every vehicle model the 3D views draw, judged against the original GTA2 sprite (silhouette,
proportions, colour, roof art) and against a modern realism bar (panel shapes, wheels and tyres, glass and
frames, lights, bumpers and grilles, mirrors, paint material, interior through glass, arches, ride height,
contact shadow). Triage only: defects are filed in `/mnt/gta2/defects/open/` for the fixer agents.

## Ranked summary

Of the 83 vehicle models (60 image-to-3D cars, 23 parametric: trains, trailers, wrecks, shared-sprite dummies, the van,
the agent car), 34 score good, 30 acceptable, 19 bad. The fleet's era and identity work is mostly in: the sedans, vans,
the truck cab, the cop car, the taxi and the sports cars read as GTA2's cars at chase distance. What breaks the realism
bar is systematic, not per-car: opaque baked glass, hard facets on bonnets within a block, no contact shadow, and a set
of parametric placeholders that never got a model.

**Three worst vehicles** (by how often a player sees them x how wrong they are):

1. **The wrecks 072-081**: flat dark pancakes with no cabin, roof, arches or tyres. After every explosion, every mission.
   (`vr-wrecks-flat-dark-pancakes-no-car-shape`)
2. **068 Van**, the second most frequent Downtown car: a parametric loaf with flat grey disc wheels and no panel lines,
   while its twin 067 TV Van is a good VW bus. (`vr-van-068-parametric-flat-disc-wheels-no-panel-lines`)
3. **083 Furore GT** and the other four round-8 regenerations (047/048 Meteor, 016 Panto, 064 SX): the shipped bodies are
   the pre-round-8 modern/1980s ones. The CAR-ERA doc section says they were replaced; the files never reached
   `assets/models`. (`vr-round8-era-models-never-shipped-furore-meteor-panto-sx`; copy done in this pass, restage pending)

Runners-up: 050 B-Type and 018 Shark (crumpled bonnets, blob headlamps; ranks 13 and 11), 084 Special Agent Car (an
untextured lime wedge), 056 Taxi (torn chequer band, rank 6), 069 U-Jerk Truck (drives tail-first since round 11:
confirmation appended to pl19-jacked-truck-drawn-backwards).

**Single highest-leverage fix**: the shared-sprite mapping. Point 068 at 067's mesh, 084 at 014's, the four hot-dog
dummies at 023's (manifest entries only, no generation): it turns the second most seen car, the agents' car and four
mission vans from placeholders into the good models that already exist, in one afternoon. Second: translucent glass with
a dark interior box on every car (one renderer change lifts all 60 generated bodies a class).

Defects filed this pass (`/mnt/gta2/defects/open/vr-*`), ranked: wrecks (2), facets and crumpled bonnets (3),
taxi chequer (4), 068 van (5), pre-war blob lamps (6), roof sprite colour (7), 084 agent car (8), trains and trailers (9),
036 Schmidt canopy (10), opaque glass (11, feature), hot-dog dummies (12); plus the round-8 copy (assigned, 5p) and the
069 confirmation.

## Method

- Stage: a private hard-link copy of the live stage (`stage_vr` = `repo/stage` at ac0e16a, 15:00 restage,
  the round 9-11 models included), plain renderer, L4 GPU 4, 1280x720, daylight, Downtown carriageway.
- Traffic sweep (`gamerun/vr_traffic.py`, run `out/vr_traffic1`): `[devtools] force_car_model=N` draws every
  traffic car as model N; the player stands in the lane so the queue comes at the chase camera nose first.
  Frames per model: `drv_far_NNN` (within 4 blocks, chase camera), `drv_close_NNN` (within 1.5 blocks),
  `drv_fp_NNN` / `drv_fp2_NNN` (first person on foot at eye height, 1.2 s apart).
- Own-car sweep (`gamerun/vr_seat.py`, run `out/vr_seat1`): the scene car with `force_own_car_model=N`:
  `t_own3_NNN` (chase camera behind the player's car, the view a driver sees most), `t_own1_NNN` (from the seat),
  `t_own3drive_NNN` (chase camera while steering).
- Contact sheets: `tools/vehicle_review/vr_sheet.py` -> `out/vr_review/sheet_*.png` (sprite | far | close |
  eye | eye2 | own chase | own seat, 7 models per sheet).
- Reference: `out/vr_review/sprites_all.png` (every x4 sprite, nose down as the game draws it).

## How often a player sees each vehicle

Counted from the Downtown carriageway watch (`out/noses_wil`, 9 335 drawn-car samples over 5.5 minutes,
`GTA2DX9_LOG_CAR_NOSES=1`), plus the catalog's `traffic_districts` for the other two districts (presence only,
no counts). Mission, police and emergency vehicles are seen on events, not in traffic.

| Rank | Model | Downtown samples | Also in |
|---|---|---|---|
| 1 | 063 Truck Cab | 2213 | Residential |
| 2 | 068 Van | 1110 | Residential, Industrial |
| 3 | 013 Minx | 975 | Residential |
| 4 | 036 Schmidt | 861 | Industrial |
| 5 | 008 Bug | 625 | Industrial |
| 6 | 056 Taxi | 587 | |
| 7 | 069 U-Jerk Truck | 526 | Residential |
| 8 | 000 Romero | 453 | Residential |
| 9 | 038 Big Bug | 353 | Residential, Industrial |
| 10 | 067 TV Van | 303 | Residential, Industrial |
| 11 | 018 Shark | 288 | Residential |
| 12 | 004 G4 Bank Van | 267 | Residential, Industrial |
| 13 | 050 B-Type | 242 | Residential, Industrial |
| 14 | 027 Ice-Cream Van | 197 | |
| 15 | 012 Cop Car | 126 | every chase |
| 16 | 002 Aniston BD4 | 104 | |
| 17 | 053 Michelli Roadster | 70 | |
| 18 | 001 Wellard, 005 Beamer | 18, 17 | |
| - | Residential/Industrial only: 007, 014, 016, 021, 023, 031, 032, 033, 035, 039, 040, 044, 045, 046, 049, 051, 057, 062, 064, 071, 082, 083 | | |
| - | Events: 017 Fire Truck, 034 Medicar, 052 SWAT Van, 084 Special Agent Car, 003 Pacifier, 054 Tank, 022 Armed Land Roamer | | |
| - | Missions/parked only: 010, 011, 019, 028, 029, 030, 037, 041, 042, 047, 048, 058, 070, 086 | | |
| - | Rails: 059-061 trains, 065/066 trailers; 072-081 wrecks after every explosion | | |

## Per-class assessment

Scores: **good** = reads as the GTA2 vehicle and holds up within a block; **acceptable** = right identity, visible
flaws at close range; **bad** = wrong identity, placeholder body, or a flaw that reads at chase distance.
Frames: `W` = `out/vr_walk3/drv_{door,fq,rq,far1,far3}_NNN.png` (tiled in `out/vr_review/cards/card_NNN.png`),
`T` = `out/vr_traffic1/drv_{far,close,fp,fp2}_NNN.png` (tiled in `out/vr_review/sheet_*.png`),
`S` = `out/vr_seat1/t_own1_NNN.png` (from the seat). Zooms of the top traffic cars: `out/vr_review/zoom/`.
Rank = traffic frequency from the table above (D = Downtown samples).

### Sedans, coupes and compacts (the bulk of traffic)

| Model | Rank | Score | Identity vs sprite | What is wrong (close) | Frames |
|---|---|---|---|---|---|
| 000 Romero | 8 | good | Giulia-style three-box sedan, chrome spine and V-grille as the sprite | side glass an opaque baked smear (global); no contact shadow (filed) | card_000, z_door_000 |
| 001 Wellard | 18 | acceptable | T-bird style coupe | a dark lettering ghost on the door panel, grille soft | card_001 |
| 005 Beamer | 18 | acceptable | 507-style coupe (sprite has four door slots) | dark lumpy roof; the runner missed the door frame (car moved) | card_005, T 005 |
| 008 Bug | 5 | acceptable | Beetle, right | bonnet is a crumpled sheet of hard facets with a baked white specular streak; from the seat the bonnet drops out of view | z_door_008, S 008 |
| 010 Bulwark | parked | acceptable | 1950s Buick | flat planes across the bonnet, mustard blotches on cream paint | card_010 |
| 013 Minx | 3 | acceptable | boxy 1960s saloon | mild facets on the bonnet; windows opaque; otherwise the cleanest common car | z_door_013, S 013 |
| 014 Eddy | R/I | acceptable | 1957 Fairlane two-tone | the roof is the sprite's yellow on a red body (roof-colour defect) | card_014 |
| 016 Panto | R/I | **bad** | 1980s Panda-style hatch, yellow roof | the pre-round-8 body: the round-8 Mini never shipped (defect filed) | card_016, T 016 |
| 018 Shark | 11 | **bad** | 1930s pontoon-fender sedan; the sprite is a 1950s finned sedan | headlamps are grey melted blobs on the wings, grille a smudge; from the seat the blobs fill the view | card_018, S 018 |
| 035 Benson | I | good | Mercedes Ponton, grey over black | - | card_035 |
| 036 Schmidt | 4 | acceptable | bubble car | canopy carries the sprite's black strokes (reads cracked), lamps are blobs on stalks | z_door_036 |
| 040 Maurice | R/I | acceptable | Morris Minor, maroon | the chrome spine is a flat white streak; facets on the bonnet | card_040 |
| 042 A-Type | parked | **bad** | 1930s sedan (right era) | headlamps melted grey blobs with a pink blotch, grille smeared | card_042 |
| 049 Hachura | I | good | Citroen DS, cream | - | card_049 |
| 050 B-Type | 13 | **bad** | 1940s sedan | the whole bonnet and wings are a mosaic of creased facets, lamps blobs, grille smeared | z_door_050 |
| 057 T-Rex | I | acceptable | Hudson Hornet style, gold | facets, soft chrome | card_057 |
| 070 Z-Type | mission | acceptable | 1930s streamliner, copper | very smooth, low detail, faired-in lamps; fine at distance | card_070 |
| 029 Dementia | mission | good | tan Isetta (boxier than the sprite's egg, tracked in #2) | - | card_029 |
| 028 Dementia Limousine | D | acceptable | long tan Hudson-like sedan; the sprite is a stretched bubble car | flat facets on the bonnet | card_028 |

### Sports and muscle

| Model | Rank | Score | Identity vs sprite | What is wrong (close) | Frames |
|---|---|---|---|---|---|
| 002 Aniston BD4 | 16 | good | DB4 coupe, gold | slightly soft | card_002 |
| 019 GT-A1 | mission | good | GT40, twin stripes, roof disc | - | card_019 |
| 031 Jefferson | R | good | E-type roadster, open interior | - | card_031 |
| 037 Miara | parked | good | Miura, orange | tan sprite roof panel (roof-colour defect) | card_037 |
| 039 Morton | I | **bad** | 1930s roadster | headlamps grey melted blobs sunk in the wings, grille shell a lump | card_039 |
| 044 Arachnid | R/I | good | Giulietta Spider, red | - | card_044 |
| 045 Spritzer | I | good | Austin-Healey, tan, interior visible | - | card_045 |
| 046 Stinger | R | acceptable | Corvette Stingray, near-black | baked white highlight smear on the bonnet; tan sprite roof panel | card_046 |
| 047 Meteor | parked | **bad** | 1970s wedge with fins | pre-round-8 body (defect filed) | card_047 |
| 048 Meteor | parked | **bad** | 1980s hatchback | pre-round-8 body (defect filed) | card_048 |
| 053 Michelli Roadster | 17 | good | 250 California style, cream, red interior | - | card_053 |
| 062 Trance-Am | I | acceptable | gold Firebird | tan sprite roof on a gold body; windows baked dark | card_062 |
| 071 Rumbler | R | good | red muscle car, twin stripes | - | card_071 |
| 082 Jagular XK | R | good | dark green XK120 | - | card_082 |
| 083 Furore GT | I | **bad** | modern white supercar | pre-round-8 body (defect filed) | card_083, T 083 |

### Vans, pickups and trucks

| Model | Rank | Score | Identity vs sprite | What is wrong (close) | Frames |
|---|---|---|---|---|---|
| 004 G4 Bank Van | 12 | good | 1950s armoured van, white roof | - | card_004 |
| 007 Box Truck | R | acceptable | brown box, navy cab | a cardboard box: faint grid, no panel detail, no rear door hardware | card_007 |
| 021 Garbage Truck | R | acceptable | brown 1940s truck | the hopper is a plain box (tracked in #2) | card_021 |
| 023 Hot Dog Van | R/I | good | orange step van, hot dog, awning | - | card_023 |
| 024/025/026/085 Hot Dog dummies | mission | **bad** | parametric boxes / a sedan with the sprite smeared over the top | placeholder bodies (defect filed) | card_024, card_025, card_026, card_085 |
| 027 Ice-Cream Van | 14 | acceptable | pink/white 1950s van | the cone is a lumpy melted shape | card_027 |
| 041 Pickup | parked | good | 1948 F1 pickup, red, whitewalls | bonnet a touch lumpy | card_041 |
| 058 Tow Truck | mission | acceptable | white cab, yellow bed and boom | cab lumpy, boom crude | card_058 |
| 063 Truck Cab | 1 | good | green Kenworth-style conventional, chrome grille, stacks, mirrors | hubs soft; door glass a black panel | z_door_063, S 063 |
| 064 Truck Cab SX | I | acceptable | red cab-over | the pre-round-8 body (the doc calls it a 1990s cab-over; here it reads 1950s COE); round-8 pick not shipped | card_064 |
| 067 TV Van | 10 | good | VW split-screen bus, white over green | - | card_067 |
| 068 Van | 2 | acceptable | parametric loaf (shares 067's sprite) | flat grey disc wheels, no door or sill lines, roof sprite smear (defect filed) | z_door_068 |
| 069 U-Jerk Truck | 7 | acceptable, **drawn backwards** | Model AA with a black slatted box | the box faces the car's heading: in `card_069` the front-quarter frame shows the bed and the rear-quarter frame the cab, the opposite of every other model; the traffic queue (`T 069`) shows the bed toward the camera. Confirms PLAYTEST-FEEL's open report pl19-jacked-truck-drawn-backwards-grille-toward-chase-camera (round 11 dropped the `forward: -z` entry; the new mesh evidently faces -z) | card_069, T 069 |

### Emergency, police, special

| Model | Rank | Score | Identity vs sprite | What is wrong (close) | Frames |
|---|---|---|---|---|---|
| 012 Cop Car | 15 + chases | good | navy/white, door badge, light bar | - | card_012, S 012 |
| 017 Fire Truck | events | acceptable | red 1950s pumper | cab bonnet lumpy, lights as blobs | card_017 |
| 034 Medicar | events | good | 1950s ambulance, red cross | front slightly lumpy | card_034 |
| 052 SWAT Van | events | acceptable | navy/white armoured truck, light bar | fake lettering on the flank, emblem blob, red hubs (tracked in #2) | card_052 |
| 084 Special Agent Car | events | **bad** | flat-shaded lime parametric wedge with a light bar | placeholder body (defect filed) | card_084 |
| 003 Pacifier | mission | acceptable | olive armoured van, two roof hatches | Land-Rover cab where the sprite has a low glazed front (tracked in #2) | card_003 |
| 022 Armed Land Roamer | mission | good | Willys with the bonnet star | - | card_022 |
| 030 Land Roamer | mission | acceptable | Land Rover with canvas | very dark green, low contrast | card_030 |
| 054 Tank | mission | good | Patton-style tank | - | card_054 |
| 032 Stretch Limousine | I | good | long tan Cadillac, fins | - | card_032 |
| 033 Sports Limousine | R | good | Continental-like | - | card_033 |
| 011 Bus | parked | good | red/cream 1950s coach | - | card_011 |
| 086 Karma Bus | mission | good | yellow school bus | a torn seam at the front corner | card_086 |

### Rail and trailers

| Model | Score | What is wrong | Frames |
|---|---|---|---|
| 006 Box Car | acceptable | cream coach with a window band; flat shading | card_006 |
| 055 Tanker | **bad** | a passenger coach, not a tank car; end face a flat sprite-smeared panel | card_055 |
| 059 Train, 061 Train FB | acceptable | coaches; end faces flat with the roof sprite wrapped down | card_059, card_061 |
| 060 Train Cab | **bad** | a beige loaf with a blotchy roof: no cab windows, no loco front | card_060 |
| 065 Container | acceptable | ribbed box; front face sprite smear | card_065 |
| 066 Transporter | **bad** | a plain brown loaf, no deck or ramps | card_066 |

### Wrecks (072-081)

All **bad**: flat dark pancakes a third of a car high, no cabin, roof line, arches or tyres (card_072, card_073, card_075,
sheet_074_080). Seen after every explosion. Defect filed.

### From the driver's seat (first person, `out/vr_seat1`)

`force_own_car_model` changes only the hood copy and the cab class of the player's car (the chase camera still shows
the scene car, a 063 Truck Cab, in every `t_own3_*` frame; those frames are not per-model evidence). The seat frames show
each model's own bonnet under the QB-31 cab, 0 FAULT. What reads wrong across the fleet: the mirrors are black slabs
(nothing reflected); the A-pillars are flat grey strips without a glass edge; the header band is a plain light-grey
bar; no bonnet carries an ornament, wiper or seam line; models with high wings or lamp pods (018, 042, 050) put lumpy
boulders in the lower half of the view (`S 018`); cars with low bonnets (008, 036) show no bonnet at all (`S 036`:
only the dash). The open roadsters (`S 031` Jefferson) show the bonnet as a thin pink sheet with black torn triangles
behind it: the assigned pm8-fp-bonnet-shredded-slivers-and-grey-header-bar, still reproducible on this stage. No torn
shards on the closed cars at damage 0 (pt-fp-cab-jagular-xk-torn-black-shards fix is in this stage).

### Global findings (every generated model)

1. **Glass is opaque baked albedo**: no interior, no driver, no reflection; the open roadsters (031, 045, 053) look a
   class better than every closed car for this reason alone. Defect filed.
2. **No contact shadow**: every car floats on the road (pm-no-contact-shadows-cars-peds-props-float, assigned).
3. **Facets and crumpled bonnets** within a block on about a third of the generated set (008, 010, 013, 038, 050,
   058): decimation to 3-8k faces with unsmoothed normals. Defect filed.
4. **Baked highlights** (the concept image's specular streak) on bonnets: 008, 046, 010. Covered by the facets defect.
5. **Roof sprite colour**: a lighter sprite roof becomes a mismatched panel (014, 037, 046, 062, 016). Defect filed.
6. **Wheels** are generally right (round, dark tyres, hub detail on 041, 004, 063, 082); the parametric bodies
   (068, 084, dummies) have flat discs.
7. **Paint**: the soft paint mask and the dark-paint floor (FIX-CAR-RENDER) hold: no posterised flanks and no black
   bodies were seen in daylight; the Stinger 046 and Jagular 082 (near-black) show panel edges and a sky sheen.
8. **Ride height and proportions** are right on nearly all (the fit's 15 % aspect cap works); 070 and 028 sit low and long
   as their sprites do; the Big Bug's lifted stance reads.

## Runs

- `out/vr_traffic1` (83 models x 4 frames, 0 FAULT), `out/vr_walk3` (83 models x 5 frames, 0 FAULT), `out/vr_seat1`
  (68 models x 3 frames). GPU 4, stage `stage_vr` (= repo/stage at ac0e16a). `out/vr_walk1`/`vr_walk2` were aborted
  runner iterations (the parked-car fields; the warp finds no parked car at the carriageway).
- Round-8 copy fix: `stage_vr8` = `stage_vr` with the five round-8 meshes from `stage_carera`; after frames in
  `out/vr_traffic_r8`, before/after sheet `out/vr_review/round8_before_after.png` (0 FAULT, all five `faces +z`). The files
  are in `repo/assets/models` and the cars archive is repacked in `release_cars_r8/`; `repo/stage` needs the next
  `restage.sh` to pick them up.

## VEHICLE-VERIFY: 063 Truck Cab (97309c4), 068 Van (c152690), 013 Minx (2104027) in gameplay

### Harness fix (why vehicle QA was blocked)
`[devtools] scene_key` is empty in `package/gta2dx9.ini` and so in every stage ini. The DLL reads it once at start
(`dll/src/dllmain.cpp`), so a scene-warp press is ignored unless the run sets the key. The earlier review run did this
with an INI_SED on the command line that was never written down; `out/vcheck_new` went without it ("no devtools line
(key not seen)" x4, then frames from the church). It was not the restage's ini merge: the key has been empty since
a89b092. Fixes:
- `linux/docker/run_game.sh` / `run_game_gpu.sh` apply `# ini-sed:` lines found in the keys script, so a keys script
  carries the ini it needs. `keys_vr_traffic.sh`, `keys_vr_seat.sh` and `keys_vr_walk.sh` declare `scene_key=F11`,
  `warp_key=F9` and `nav_map=0`, and export `SCENE_KEY=F11`.
- `tour_lib.warp` presses the key the run's ini actually binds, refuses with a clear log line when none is bound, and
  detects the devtools line by log byte offset (the old 60 KB window count misreads on a busy log, see mission_lib).
- `vr_traffic.py` stops (`RESULT warp did not land`) instead of photographing the wrong street.
- `vr_seat.py` warms up the first forced model (the first seat frame used to show the scene car).
Verified: 7 runs in a row (out/vverify_tr2, _btr2, _seat1, _bseat1, _seat2, _bseat2, _m68tr, _m68seat): every
warp landed at its first press, 0 FAULT.

### Method: like for like
The 15:00 `vr_traffic1` frames are NOT a valid "before": camera, props and traffic have changed since (the fence, the
lane the queue uses), and comparing against them would repeat the rejected sheet's distance mismatch. Instead:
two private stages that differ ONLY in the three models' files. `stage_vverify` is a hard-link copy of the live
repo/stage (models 17:16); `stage_vverify_before` swaps in the `013_minx*`, `063_truck_cab*` and `068_van*` files
from `stage_vr` (Nov 8 meshes). Same DLL, ini, spot (164.5,149.2 facing 180,149.4), script and GPU, run back to back.
- Sheets: `out/vverify_review/ba_013_minx.png`, `ba_063_truck_cab.png`, `ba_068_van.png`
  (`tools/vehicle_review/vr_before_after.py`), and `out/vverify_review/after_live/sheet_013_068.png` (`vr_sheet.py`).
- Limits: `force_car_model` draws forced cars in neutral 235 paint (white); traffic cars draw in game paint
  (see the 063 and 068 chase cells, which are real unforced scene cars). `force_own_car_model` changes only the seat
  view, so "own chase" is valid only where the scene car happened to be the model under test (063 both stages, 068
  authored); the rest are marked n/a. Third-person "close" frames catch the queue 3-4 blocks out at this spot, so the
  eye-height frames are the close-up evidence. The live stage DLL predates VEHICLE-GLASS 33c34be (no `car_glass` in
  its ini), so every window seen here is the old opaque glass.

### Verdicts
- **063 Truck Cab: a player will notice.** Before: a smeared green image-to-3D lump with a muddy grille, blob lamps
  and stub wheels. After: a crisp chrome bar grille, rounded fenders, a bumper and a plate. From the chase camera
  (the most common view): stacks with perforated heat shields, fifth wheel, rear fenders and tail lamps, in the game's
  navy paint. Short of AAA: the headlamps are blank grey domes (vv-063-truck-cab-headlamps-blank-grey-domes), the
  paint is flat with no clearcoat, the tyres and the underside go black with no tread or sidewall visible, there is
  no contact shadow, the bumper edge has a pale-blue rim (vv-carkit-chrome-and-glass-edges-pale-blue-outline), and
  the plate is a black box.
- **013 Minx: a player will notice.** Before: a copper shell with a smeared face and a shredded bonnet seen from the
  seat. After: a clean early-60s coupe with the sprite's dark roof, whitewall tyres, hubcaps, chrome spear and
  framed screens, and a smooth bonnet from the seat. Short of AAA: stair-stepped grille slats that read as a broken
  texture at eye height (vv-013-minx-grille-slats-stair-stepped-texture), pale-blue outlines on every chrome and
  glass edge, mottled paint noise, and opaque dark glass with no interior (a restage with 33c34be should change that;
  unverified).
- **068 Van: a player will NOT notice. The change is not in the game.** The manifest maps model 68 to 067_tv_van
  (91f7442), so before and after are the same VW-style bus at every framing (log `-> 067_tv_van`)
  (vv-068-authored-van-never-drawn-manifest-maps-68-to-067). With only that map entry changed, the authored van is
  a real step up and closer to the sprite: forward-control box, ribbed roof, shut lines, twin rear doors, arches with
  hubcaps, and glass with the driver visible through it. Short of AAA even then: flat slab tail lamps, almost no rear
  bumper, plain black tyres, blotchy paint noise, no contact shadow. Whether 68 uses its own mesh is the
  coordinator's decision.
- Fleet-wide, unchanged by these commits: no contact shadow; flat, non-specular paint (no clearcoat or reflections
  that move with the camera).
- Classic: no renderer code changed (harness, tools and docs only), so the classic view is untouched by
  construction; no frame diff was run.

## VEHICLE-ART-6: 063 Truck Cab lamps, mudflaps, carkit chrome (9 Nov 2026)

- **Headlamps (vv-063):** they were grey domes with concentric shading, read as hubcaps. Now each is a sealed
  beam (`sealed_beam_shader` in `tools/vehicle_art/m063_truck_cab.py`): a silvered reflector annulus behind a
  prism grid, a dark bulb shield with a chrome cap, and a dark seal at the rim. The glass is flatter and sits under
  a proud chrome bezel. Its env reflection drops to 0.12 so the sky does not wash the pattern out. Its glTF
  material name is still `headlamp_lens`, so it is still lit at night.
- **Mudflaps (pm120):** the "black rod from the bumper to the road" was the 2 cm flap seen edge-on, hanging to
  16 cm off the road. It is now a rounded 4 cm slab that ends 30 cm up.
- **Pale-blue chrome and glass edge (vv-carkit):** `carkit.sky_env` baked a saturated zenith (0.50, 0.66, 0.92).
  Every rounded top edge mirrored it, so bumpers, rims and frames carried a blue line. The zenith is now a hazy
  (0.62, 0.66, 0.72), and the horizon is 0.88. Only rebuilt models pick this up: 063 now; 013 and 068 at their
  next rebuild. `tools/vehicle_art2` has its own carkit, which is not changed.
- Frames (same spot, own car stopped, regression camera, the old model's files vs the new ones, same DLL):
  out/va6_063a (before) and out/va6_063b (after), poses front34, eye, side, rearside, rear34, far and chase.
  0 FAULT in both runs.
- Still short of a shipping frame: the cab's proportions follow the sprite rows (VEHICLE-ART-1) and were not
  re-cut. The door glass is still dark. At the chase distance the hubs are soft.

## VEHICLE-ART-6: pre-war lamps on the 050 B-Type and 018 Shark (item 7)

TRELLIS fused the free-standing lamps into the wings, and the bake left pale grey blobs. There was no rim, no
lens and no reflector. `tools/vehicle_art/add_lamps.py` adds carkit lamps at the positions you give it (glb units,
mirrored to -x). Each lamp is a short chrome bucket sunk into the blob, its rim proud of the blob's front, a dark
seal, and the 063's sealed-beam lens. It writes them into the generated glb as a second material (image 1 and 3,
256 px).
- The body's mesh, UVs and texture are untouched (vertex counts: 13910 + 936 and 10674 + 936), so the resplit
  body textures `NNN_0*.tga` (FIX-CAR-IDENTITY) and their Remix hashes stay valid. Only the `.mesh` and the new
  `_1`/`_3` lamp textures are copied in.
- Positions: 050 at x 0.185, y 0.222, r 0.032. 018 at x 0.124, y 0.271, r 0.034. You can measure them with an
  orthographic front render of the glb.
- `assets-src/cars/models3d/050_b_type.glb` and `018_shark.glb` now include the lamps. Run the tool on the
  lamp-less originals (backups in `<workspace>/backup_va6/src`), never on its own output.
- Frames (same spot, own car stopped, regression camera, forced model, same DLL): out/va6_lampa (before) and
  out/va6_lampb (after), poses front34, eye, side, far and chase. 0 FAULT.
- Still short: the 050's bonnet is still lumpy (geometry, item 6). On the 018 the octagonal blob still shows
  round the new lamp from the side. The 018 is a 1930s pontoon body, while its sprite is a finned 1950s
  sedan: that identity miss needs a regenerated or authored body. The grilles are unchanged. 042 and 039 were
  not done (they can use the same tool).

## VEHICLE-ART-6: 051 Taxi Xpress (item 10, the 051 half; the 056 half was VEHICLE-ART-2's authored taxi)

`tools/vehicle_art/fix_051_taxi.py` repaints the generated texture in object space. It UV-rasterises the glb so that
each texel knows its point and normal on the body, then:
- **Belt band:** side-facing texels at y 0.200-0.242 are redrawn as two clean rows of black and white squares.
- **Patches and blotches:** the rear doors' "QR code" patches and the bonnet blotch go back to the body's yellow
  (flat). The roof's broken squares go back to yellow with their own shading.
- **Centre stripe:** a chequered stripe, the sprite's (|x| < 0.042, 3 squares across), runs over the flat tops
  (normal y > 0.82): bonnet, roof round the sign, and boot.
- **Boot lid:** TRELLIS stood it up behind the rear window as a torn fin up to roof height (the before frames
  show an open boot). There is no other boot top under it, so its vertices fold down onto the boot line (0.255).
  The faces that end up facing down are turned over, and its texels are painted as body with the stripe.

The vertex count is unchanged (7230). 051 had not been resplit, so the whole import (mesh, `_0`, `_0_paint`) is
replaced. Run the tool on the original glb (backup in `<workspace>/backup_va6/src`), not on its own output.
- Frames (same spot, own car stopped, regression camera, forced model, same DLL): out/va6_taxia (before) and
  out/va6_taxib (after), poses front34, eye, side, rear34, high and far. 0 FAULT.
- Still short: faint ghosts of the old front-door blobs and a few dark spots beside the bonnet stripe; a small
  stub at the C-pillar where the fin met the roof; the folded lid is flat paint, with no shut line. Under Remix the
  changed texture has a new hash, so any gta2hd prim keyed on the old 051 texture no longer applies (FIX-REMIX-IDENTITY).
- 036 Schmidt and 056 Taxi (VEHICLE-ART-2's authored bodies), checked in out/va6_taxi1: the 036 canopy is clean
  glass with no sprite lines, and the 056 band is straight. Their lamps are plain dark domes (not done).

## VEHICLE-ART-7 (9-10 Nov 2026): 050 authored, trains and trailers authored, sealed beams, hubs, roofs, chrome

Probe: `gamerun/va6_own.py` (the stopped own car forced to each model, regression-camera poses front34 / eye /
side / far / chase, same spot and DLL before and after), plus `gamerun/va2_show.py` for traffic cars (no seated
driver, forced paint). Runs: `va7_base` (before), `va7_a1`..`va7_a4` (after). 0 FAULT in every run.

Per model, what the close frames showed and what was done (mesh work only where a frame proved it):

| Model | Close-pose finding (va7_base) | Fix |
|---|---|---|
| 050 B-Type | bonnet and wings a crumpled mosaic of lumps several faces wide, a torn grille, a stray fin on the bonnet: geometry, not shading (a normal-only Taubin pass, `tools/vehicle_art/smooth_shell.py`, barely changed it) | **re-authored** in the vehicle_art2 kit: `tools/vehicle_art2/car_050.py`, a late-1940s four-door (wings swelling round each wheel in plan, split windscreen, bar grille with the sprite's chrome centre bar, sealed-beam lamps in the wings, spear, wraparound bumpers with over-riders, whitewalls), neutral 235 paint tinted by the identity record; `driver_seat` in `seat_anchor.py` |
| 018 Shark | bonnet acceptable; front and rear hubs jagged spiked lumps (spun by the shell wheel split) | `tools/vehicle_art/flatten_hubs.py`: the hub vertices pressed onto a smooth dome (positions only, UVs/textures untouched; the 20:38 re-split `_0` textures kept). Body still 1930s against a 1950s sprite |
| 013 Minx, 063 Truck Cab | authored (carkit), smooth: no facets | 013 and 068 re-baked with the hazy-zenith chrome (92fa080): only `_0` (trim atlas) and `_4` (glass) change; mesh and paint byte-identical |
| 036 Schmidt | dark-dome lamps; the bonnet spine a black stripe (the chrome band texture's ground half at the deck's v ~ 1) | spine: own `chrome_spine` material (flat bright metal); lamps as below |
| 056 Taxi | dark-dome lamps; the chequer band bent down and up round the wheel openings (a band at fixed loft v over the lifted arch) | band stops 4 cm clear of each opening; lamps as below |
| 008, 040 | dark-dome lamps | lamps as below |

**Sealed beams (vehicle_art2 kit, `tex_lamp("head")`):** the fluted grey-blue lens over a dark bowl read as a dark
dome in the game's light. It is now the 063's sealed beam as a texture: a silvered reflector bright round the bulb,
prism cells, the bulb shield with a chrome cap, a dark seal (128 px). Only `NNN_lamp_head.tga` changes for 008, 036,
040 and 056 (tail and amber lamps byte-identical).

**Trains and trailers** (vr-trains-trailers-parametric-loaves-sprite-smear): six authored bodies in
`tools/vehicle_art2` with a shared `rail_kit.py` (flanged rail wheels, two-axle bogies with side frames, springs and a
bolster, buffers and coupler, trailer chassis, dual-tyre axles, landing legs, mud flaps, grime / corrugated / plank
/ grating / louvre textures). Every model spans exactly +-1.0 block (the game's 2-block body); a carriage's body
stops at +-3.95 m (GTA2 overlaps coupled cars by 0.41 block), a 1 cm marker on the ground holds the length.
- 059 Train: coach with a window band, two pairs of sliding doors (CARI door rows), end doors, gangway, roof vents, cream roof.
- 060 Train Cab: the coach shell with a streamlined nose (wraparound windscreen cut on the shell, headlamp, pilot), silver louvred roof hood, crew doors at the back.
- 061 Train FB: plank deck, side sills with stake pockets and stanchions, end bulkheads with lamps.
- 055 Tanker: elliptical tank, girth bands, stainless ends, two filler domes (the sprite's), walkway with rails, ladder, tandem dual axles, landing legs.
- 065 Container: ribbed box with the sprite's X-braced outside frame, corner castings, roof spine, rear doors with locking bars.
- 066 Transporter: two-deck open frame, grated decks, diagonals, headboard, folded ramps.
59-61 are liveries (own colours); 055/065/066 are neutral paint tinted per remap.

**Roofs** (vr-roof-sprite-keeps-sprite-paint-mismatched-roof-colour): `tools/vehicle_art/roof_paint.py` moves a
generated car's roof texels (upward faces near the top, not glass, not chrome, not already paint) from the untinted
half into the paint half with their luminance only. Applied to 046 Stinger (the tan hardtop now takes the body
paint) and 062 Trance-Am (a small remainder). Not applied: 014 Eddy and 047 Meteor (the roof is already paint after
FIX-CAR-IDENTITY-3 / round 8), 037 Miara (already paint; the tool would paint over the engine-cover louvres).

Remix: every changed texture has a new hash (list in the journal line of 9-10 Nov); prims are FIX-REMIX-MATERIALS-2's.

Still short of a shipping-AAA frame: the 050 is clean but plain (no stamped wing creases or trim detail of a real
1948 car, lamps a little small); the 018's 1930s body against its 1950s sprite; the 051's door ghosts, roof blotches
and C-pillar stub (needs re-authoring like the 050); the train cars are seen only as forced models at street level
(not yet filmed on the elevated line in motion); the trailers' coupling with the 063 cab is not filmed.

## VEHICLE-ART-8 (10 Nov): paint by geometry, 051 authored, 042/039 lamps

**Paint by geometry** (pmm1: the bil 082 Jagular XK was copper only on its roof and bonnet; boot, rear wings, tail
and lower flanks near-black teal). The generator baked deep shading into many bodies, so the shaded half of a body
is near-black: no hue, and `car_paint_resplit.py` (hue-based) leaves it in the untinted half. The 3D car then shows
the generator's undercoat with patches of the sprite's colour. `tools/vehicle_art/geo_paint.py` re-splits the body
atlas by where each texel is on the mesh (`uvraster.py`: UV rasterisation, each texel's point and normal):
- paint = the outer shell (not the underside, above the sills) minus the wheels (a cylinder round each axle found from
  the ground-contact vertices), minus bright grey texels where chrome lives (bumper ends, the window band, low
  trim; `--chrome-ends`, `--glass-zone`, `--chrome-low`: elsewhere a bright grey texel is a baked highlight and is
  painted), minus strongly coloured texels of another hue (lamps, badges), minus a grille zone (`--grille`);
- the paint is written neutral and nearly flat (`--level`, plus the texel's fine detail as a clipped high-pass), so
  the renderer's light, not the generator's, shades the panel; the gutter round each painted UV island takes the
  paint too (`--gutter`), or bilinear/mip sampling draws pale seams at the island edges;
- **the `_paint` texture must keep the original RGB where its alpha is 0**: with `car_paint_soft_mask=1` the renderer
  draws the paint mesh opaque as texel x lerp(1, tint, coverage) (model_store.cpp softPaint), so a coverage-0 texel
  shows its own RGB. Writing 0 there drew every tyre, whitewall and bumper black (out/va8_a1).
- `tools/vehicle_art/preview_pair.py` previews a generated glb with a texture pair, tinted, in the kit's views.
Applied: 082 (`--detail 0.10 --grille 0,0.24,0.20,0.75 --grille-lum 32 --chrome-ends 0.80 --glass-zone 0.62
--glass-lum 40 --chrome-low 0.30`; upper-shell paint 48 % -> 86 %), 038 Big Bug (`--wheel-r 0.16 --wheel-x 0.40
--hue-tol 22 --sill 0.38 --glass-zone 0.82 --chrome-low 0.40 --chrome-ends 0.96`; 25 % -> 77 %), 058 Tow Truck
(`--grille 0,0.62,0.12,0.60 --grille-lum 70`; 66 % -> 88 %). Only `NNN_0.tga` / `NNN_0_paint.tga` change.

Paint-share audit (upper shell, area-weighted, from each generated glb's UVs over the shipped `_0_paint.tga`):
bodies under 60 % that are not liveries: 038 30 57 53 046 062 005 019 004 039 003 002 044 069 031 064 021 042 049
037 016 007 (and 082 before this pass). The generic settings are NOT safe on these (tried 005, 039: dark glass,
chrome bumpers and an open cockpit get painted); each needs its own zones and a look at its preview before it ships.
Liveries (011 012 017 022 023 027 034 052 054 086 ...) are drawn untinted and are not paint-split defects.

**051 Taxi Xpress authored** (vr-taxi-051-residue): `tools/vehicle_art2/car_051.py` is the 050 B-Type's body (the
catalog: "Checker cab livery on the B-Type") in the cab livery: yellow 236,160,40 (a livery, untinted), a two-row
chequer belt under the chrome spear clear of the wheel openings, a three-cell chequer strip down the roof from the
back light to the windscreen, a long flat roof sign (dark box, TAXI faces), a navy pin line down the bonnet and boot
(the sprite's), a waterfall grille. Seat as the 050. It replaces the image-to-3D shell and its door ghosts, bonnet
spots and C-pillar stub.

**042 A-Type, 039 Morton lamps** (item 7): `add_lamps.py` at 042 x 0.10 y 0.245 r 0.030 and 039 x 0.11 y 0.235 r
0.030 (positions read off a z-max grid of the glb's front). Only the `.mesh` and the new lamp textures `_1`/`_3`
change; the body textures are kept. `assets-src/cars/models3d/042_a_type.glb`, `039_morton.glb` include the lamps
(lamp-less originals in `<workspace>/backup_va8/src`).

Still short of a shipping-AAA frame: the 082 is the right colour but its TRELLIS shell keeps jagged bumper edges and a
red/green streak baked across the rear window; the 038 is copper but its body is faceted and its headlamp faces got
painted; the 058 has a white blotch on the bonnet and one yellow rear hub; the 039's body keeps its dark undercoat
(its open cockpit needs a zone); 22 bodies of the audit are untouched.

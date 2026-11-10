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

## VEHICLE-ART-9 (10 Nov 2026): 038, 018, 082 and 058 authored

Four TRELLIS shells replaced by authored bodies in `tools/vehicle_art2` (paint neutral 235, tinted by the identity
record like the other authored cars; `driver_seat` from `tools/vehicle_art/seat_anchor.py`):

- **038 Big Bug** (`car_038.py`): the 008 Beetle body lifted 0.5 m on 1.2 m off-road tyres (lug tread texture, steel
  wheels), Baja wheel cut-outs, flared wings, a bare engine behind the cut tail (crankcase, finned barrels, chrome air
  cleaner, two upswept exhausts) in a tube cage, push-bar, roof spot lamps, ladder frame, coil-over shocks.
- **018 Shark** (`car_018.py`): the catalog's Graham-Paige Sharknose: a knife-edge prow whose top leans forward
  (`SHEAR`), a vertical-bar grille on the prow (its own UV patch), headlamps where the wings meet it, a long fastback
  roof into a teardrop tail. No side lamp blob.
- **058 Tow Truck** (`car_058.py`): a 1950s wrecker: conventional cab with two amber roof beacons, bonnet between
  pontoon wings, chrome grille and bumper, flat bed with tool boxes, winch, A-frame and the sprite's twin booms to a
  hook; wide (dual-look) rear tyres. Evidence `out/va9_058a` (before `out/va8_a4` own_*_058_t).
- **082 Jagular XK** (`car_082.py`): XK120 fixed-head coupe on the shipped orientation (bonnet +z): long bonnet
  between raised wing crowns, oval grille with a chrome surround (flat patch on the nose cap), a small cabin set
  back, dark glass, slim blade bumpers. No torn rear window, no jagged bumper, no spiked hubs.

**Wheel split trap.** The renderer (`car_bodies.cpp` BuildWheelSplit) gives every triangle wholly inside a wheel's
disc (radius = the wheel marker's height, outboard of |x| - 1.2 r) to the wheel, which spins and steers. Rear wheel
skirts (first 018/082 attempt) and a lifted body over big tyres (first 038) were cut into the wheels: a skirt and body
chunk hung off the turning rear wheel in game. Keep every body part outside that disc: open arches with a radius
above the tyre's, suspension inboard of |x| - 1.2 r. `tools/vehicle_art2/wheel_split_check.py <models> NNN` lists the
non-wheel triangles the split would take (the 160 `underbody` triangles are the wheel's own inner disc; 038's 40
`frame` triangles are its coaxial axle stubs).

Evidence: `out/va9_b5` (own car forced to 38/18/82 at the street warp, regression-camera poses front34, side, rear34,
eye, far, chase; `_t` straight, `_s25` wheels steered 25 degrees), before: `out/va8_a4` (038), `out/tri6_va6b` (018),
`out/va8_a3` (082).
Still short of a shipping-AAA frame: the 018's grille bars read stark black and white close up and its cabin is long
and upright for a Sharknose; the 082's wing crowns are faint from the side and its wheels are plain painted discs (no
wire wheels); the 038's engine is box-modelled; paint is one flat colour with orange-peel noise (no clear-coat flake
outside Remix). the 058's bed and tool boxes are plain boxes and its booms plain tubes. Remix prims for the new textures are not
built (FIX-REMIX-MATERIALS-3). Classic: vreg stage capture out/vreg_va9_1 (stage_va9, all four models): 31/31 PASS,
spawn_classic 0 changed tiles.

## VEHICLE-ART-10 (10 Nov 2026): 004 G4 Bank Van, 053 Michelli, 057 T-Rex authored

Three more image-to-3D shells replaced by authored bodies in `tools/vehicle_art2` (paint neutral 235, tinted by
the identity record; `driver_seat` from `tools/vehicle_art/seat_anchor.py`; `wheel_split_check.py` clean: only the
wheels' own 160 inner-disc triangles):

- **004 G4 Bank Van** (`car_004.py`, ptm1-bil, the van the owner demo jacks): a 1950s armoured cash truck read from
  the sprite (front down in the export): a short forward-control cab (raked windscreen, short bonnet, vertical-bar
  grille, bull-bar on a heavy bumper) and a tall armoured box with four stiffener ribs down each side (the sprite's
  notched flanks, a clear marker lamp on each), gun slits between them, a pale roof plate with the sprite's two
  domed round vents, a pale cab roof (the sprite's pale panel ahead of the box), rear doors with small armoured
  windows, hinges, locking bar and lamps. The paint covers the whole body, so the identity tint reaches every
  panel: the old shell's shaded half was untinted near-black, its roof a mottled 'camo' blotch and its rear a white
  slab (ptm1). The roof plate, cab roof and vents are a fixed pale grey (`roof_panel`, `vent`), as both remaps of
  the sprite draw them. The gun slits are `slit`, not `*_glass` (a `_glass` texture is drawn blended and would
  show through the box). The hue of the jacked van (the identity record: 59,82,115 blue for the remap-36 green van
  at 588c4f9) is FIX-CAR-IDENTITY-4's half of ptm1.
- **053 Michelli Roadster** (`car_053.py`): the sprite is a fastback GT, not an open roadster (painted roof, rear
  window at the tail): a 250 GT Berlinetta idiom on the 082 body code: long bonnet with a low centre scoop (dark
  mouth) and louvres ahead of the screen, faired headlamps at the wing tips, a wide low egg-crate grille in a chrome
  oval, gill vents behind the front wheels, the roof running into a fastback back light, a Kamm tail with twin
  round lamps, split front bumpers, chrome wheels. The first take put 26 front-wing triangles in the front wheels'
  discs (the belt there sat below the arch): the belt was raised and the arch narrowed.
- **057 T-Rex** (`car_057.py`): a 1955-57 Thunderbird hardtop: flat sides on a straight belt, bonnet scoop,
  hooded headlamps over a wide oval egg-crate grille with two bumper guards, wrap-around windscreen with chrome
  pillars, the sprite's dark hardtop as a fixed dark gloss (`hardtop`, not tinted) with a chromed porthole in each
  rear quarter and a small upright back light, a short deck between two small fins with round tail lamps, a chrome
  spear, whitewalls. geo_paint had painted its chrome and lost the dark roof (VEHICLE-ART-9).

- **042 A-Type** (`car_042.py`, audit item 6: crumpled wings): the catalog's Cord 810 idiom on the 018 Shark's body
  code without its forward lean: a blunt coffin nose wrapped in horizontal louvres (`tex_louvres`, toned down after
  the first in-game take read as a black-and-white zebra patch), headlamps in the pontoon wing faces (the first take
  buried them: the wing face is at z 2.07, read it off the mesh before placing a lamp), chrome centre strip down the
  bonnet, four doors, fastback, teardrop tail, whitewalls; the arch liners narrowed to the slimmer nose.

- **039 Morton** (`car_039.py`, audit item 6): a Morgan Plus 4 idiom written on the kit from scratch: a narrow tub
  with louvres down the bonnet sides, an upright chrome waterfall grille, separate wings (the 008 Bug's fender: long
  front wings sweeping into running boards, round rear wings), headlamps on stalks with a light bar, a small upright
  windscreen, an open cockpit (the sprite's dark cockpit) with the folded hood behind the seats, a spare on the tail.
  The first take put 218 tub triangles in the wheel discs (the tub reached past X_WHEEL - 1.2 r): the tub was
  narrowed and the track widened.
- **Renderer note** (not changed, `cab_interior.cpp` belongs to FIX-FIGURE-8): CabOpenTop() lists model 53 as an open
  top; the authored 053 is a closed fastback (the sprite's painted roof), so 53 should leave that list (glass cut,
  seated band and first-person roof then treat it as closed). 39 stays (open cockpit).

Train film (item 4): the regression camera set ahead of the logged train still framed a street and undersides
(out/va10_rail1); the `vehicles:` line gave the trains z 3.0 then 1.0 at x,y with no track in view, so its train
positions cannot be trusted yet. Trailers 055/065/066 are in no traffic district (catalog).

Probe note: in the va6_own warp probe the hero is drawn sitting outside the left flank of every car on the e0b69de
DLL (old shells and ART-9's 018 alike), while the manifest seat is published inside the cab: a probe/figure issue.

Evidence: see the READY lines on the work orders (ptm1, vr-vehicle-art-audit-batch).

## VEHICLE-ART-11 (10 Nov 2026)

Probe: `gamerun/keys_va11_own.sh` + `va11_own.py` (va6_own plus `POSES_EXTRA` poses with their own look-at point,
`PAINT` = force_car_paint, `EXIT=1`: park, step out and film the car as a parked car, so the own-car paths do not
change what is drawn). Private stages: `stage_va11` (HEAD 1f812d5 DLLs, the ee51756 stage models) and `stage_va11b`
(the same plus the files below).

- **082 seat (pmt6, art half):** the manifest seat [0.08, 0.112, -0.076, 0.2551] lies on the bucket's cushion in the
  shipped .mesh (seat triangles x +-0.128, y 0.084..0.212, z -0.124..-0.010), and the log publishes it inside the body
  (`driver's seat of 082_jagular_xk (manifest): u 0.084 z -0.077 cushion 0.116`). The filer's bil repro on the HEAD
  DLL (out/va11_bil082a, carmodel=82) still draws the hero standing at the rear-left flank in third person
  (idp_car_2third.png). That is the renderer half (FIX-SEAT-ENTRY-4). No model change.
- **063 Truck Cab glass, mirror, cab (pmx11):** the carkit bodies (063, 013, 068) bake their windows into a separate
  `glass` draw group, but the importer named its texture by image index (`063_truck_cab_4.tga`), so it drew opaque:
  a black pane over a cabin nobody could see, and VEHICLE-GLASS's mask pass also treated the body as a generated
  hull. Now: `tools/vehicle_art/glass_translucent.py` writes `<name>_glass_t.png` (the baked pane, alpha 0.45, lifted
  12 % toward the sky tint), and the manifest maps the material to it (`"material_textures": {"glass": ...}`).
  The import names it `063_truck_cab_glass.tga`: blended, z-write off (model_store CarSurfaceFor), and car_glass logs
  "has its own glass (authored body), left as it is". `m063_truck_cab.py`: the mirror housing is black painted steel
  (a baked chrome slab read from the front as a blue-black sawtooth sheet), the arms stay chrome; the cab liner is a
  light grey-beige headliner with upward-leaning normals (lit with inward normals, it got only ambient: black
  behind the glass). A liner with window holes was tried and rejected: whole-face cuts left stair-stepped edges
  through the far pane. Before out/va11_063b2, after out/va11_063a7 (parked, teal 45,110,115; poses door1 = 1 block
  from the door at first-person eye height, door06, mirror, doorL, cab3q, side, front34, rear34, eye, far, chase).
  Own-car takes out/va11_063b1 / a2: on the HEAD DLL the own 063 was ghosted (whole upper cab translucent); with the
  `_glass` texture it draws solid. Far view unchanged. Remix: `063_truck_cab_0.tga` (re-baked) and
  `063_truck_cab_glass.tga` have no prim; `_2_paint` kept its prim.
- **Fleet glass, asset side (VEHICLE_PRIORITY 2), tried on 013/068, not shipped:** the same glass-only change on the
  carkit 013 Minx and 068 Van (before out/va11_g13b0, after out/va11_g13a0) made their windows WORSE in the plain
  renderer: VEHICLE-GLASS's mask pass already draws them as sky-reflecting glass over its lit cabin shell, and a
  `_glass` texture turns that pass off, leaving a dark pane over the dark carkit liner. The 063 was different (its
  side windows stayed opaque black under the mask pass at the parked poses). Next for Remix: re-light the 013/068
  liners like the 063 (re-bakes `_0`), then a glass prim; for the TRELLIS bodies, cut panes offline from the
  renderer's own masks (`GTA2DX9_GLASS_DUMP=1`).
- **Per-model list:** 069 heading already fixed and verified (fixed/pl19, `forward: +z` on the round-11 mesh); 050 is
  ART-7's authored body; 010 left as ART-8/10 judged it; the 063's black door glass is the pmx11 change above.

## VEHICLE-ART-12 (10 Nov 2026)

- **018 Shark front (vr-prewar-sedans-headlamps-melted-blobs-grille-smear, audit item 7 residue):** the sprite
  (`out/vr_review/sheet_016_021.png`, x4) is a streamlined fastback with a narrow chrome prow, pontoon wing bulges
  either side of it and a long roof to a teardrop tail, and no tail fins: the catalog's Sharknose, which ART-9's
  `car_018.py` body already follows, so the body was kept and the front re-authored (the audit's "1950s finned sedan"
  does not match the sprite). Before: a 14-bar black/white vertical-bar patch over both prow flanks AND the wing faces
  (a zebra), the lamps 0.1 m ahead of the wing floating on it, the prow's tip open (a dark slot in the front view).
  Now: horizontal satin bars on the V prow flanks only (`tex_vgrille`, shaded per bar), a chrome strip down the knife
  edge (the sprite's chrome prow; it closes the tip), the wings fuller over the front tyre (`NOSE` 0.58, plan exponent
  3.2: the wing tucked in and its black arch liner showed as a chin) with the headlamps half sunk in the wing face
  where it passes x 0.80 (found on the surface, not a constant) inside a paint fairing ring. Paint albedo unchanged
  (mean 196.4 vs 195.7: not darker). `wheel_split_check.py`: only the wheels' own 160 triangles. Evidence (parked, PAINT
  139,98,74, poses front34/eye/nose/side/rear34/far/chase/cab3q): before `out/va12_018b0`, after `out/va12_018a1`.
  Textures changed: `018_shark_grille.tga`, `018_shark_paint_body_paint.tga` (AO re-bake), `018_shark.mesh`.
- **010 Bulwark authored (`car_010.py`, audit "flat bonnet planes, mustard blotches"):** the image-to-3D shell (a 1950s
  convertible with a translucent box for a cabin, lumpy wings, a torn hole in the rear window, blotched paint) replaced
  by a late-1950s American four-door read from the x4 sprite (front up in the export): the sprite's light roof runs from
  row 7 to row 46 of 64 with the side glass as its dark outline, so a short bonnet and a long glasshouse (the windscreen
  over the front axle, as CARI's +21 px axle and the roof start say), a wrap-around back light, a short deck between two
  swept fins ending in tall tail lamps, the sprite's centre emblem, hooded round lamps at the wing tips (its bright
  corners), a wide egg-crate grille, a heavy bumper with the sprite's two guards, a side spear, whitewalls. Paint
  neutral 235 (the identity record tints it, like the other authored cars; was a paint split of the shell at
  175,140,113), `driver_seat` from `seat_anchor.py`. `wheel_split_check.py` clean. Evidence (parked, PAINT 209,164,116 =
  the catalog's default remap): before `out/va12_010b1`, after `out/va12_010a2`. Short of AAA: the deck is a flat
  panel, the bonnet plain (no scoop or crease), the paint flat.
- **063 Truck Cab fuel tanks (ART-11's residual):** black steel straps standing proud round each tank, rolled seams at
  the dished ends, a filler neck with a chrome cap, hanger brackets inboard to the frame (`m063_truck_cab.py`). A
  rebuild of the unmodified generator reproduces the shipped files byte for byte, so only these parts changed; the
  atlas re-packs (`063_truck_cab_0`, `_2`, `_2_paint`; paint mean 129.8 vs 130.1). Evidence `out/va12_1063a1`
  own_side_063_t / own_rear34_063_t. The cabin behind the glass is unchanged (no Fresnel in the plain renderer:
  the renderer's, not the asset's).
- **Not re-authored:** 036, 008 and 056 are already authored bodies (ART-2/7: clean canopy, smooth bonnet, straight
  chequer band; the audit's lines describe the old shells, verified by triage) and 013 Minx is the carkit body; their
  previews at this pass show no torn or crumpled geometry. 013/068 liner re-light (Remix only) not done.

## VEHICLE-ART-13 (10 Nov 2026)

- **050 B-Type (item 6, "crumpled bonnet"):** stale. The shipped 050 has been ART-7's authored body
  (`tools/vehicle_art2/car_050.py`, mesh dated 9 Nov 23:57) since before the 00:15 triage that verified it. The
  18:15 and 23:58 triage lines describe the old TRELLIS shell. This pass's parked frames (`out/va13_up_b0`
  own_front34_050_t) show the smooth authored body with its sealed beams. It was not re-authored again.
- **Kit bodies inside out (FIX-CAR-IDENTITY-6's finding, 858415f):** all 19 vehicle_art2 kit bodies (004 008 010 018
  036 038 039 040 042 050 051 053 055 056 057 058 059 060 082) had faces and normals pointing inward. The renderer
  draws without culling and lights by normal, so the sun lit the inside of every panel. The shipped .mesh files are
  re-oriented with `tools/car_mesh_orient.py fix` (`check`: 0 inside out), and `tools/vehicle_art2/build.py` now runs
  the fix on every import.
- **Floor pan (DEFECT-TRIAGE pass 195, pm33's residual):** every car's underside was near-black texels: the kit's
  flat `underbody` 28,27,26 and the image-to-3D shells' random projection. A car seen from below read as a black slab.
  - `tools/vehicle_art/underpan.py` is one shared part for every road car (63 bodies: generated, carkit v1, kit; not
    063, which has an authored ladder chassis, and not the tank, rail stock, trailers or wrecks). It works on the game's
    .mesh and adds the draw group `<name>_underpan.tga`, the same texture for every car. The part is a stamped
    dark-grey pan (tunnel, swages, cross members) 3 mm under the body's measured floor, plus frame rails, sump and
    gearbox, a front cross-member, a propshaft, a rear axle with its differential, the exhaust with a silencer, and a
    fuel tank.
  - Near each axle the pan narrows to 0.2 x the half width, the renderer's wheel-split rule (all corners in the
    disc and outboard of xin). The tool counts the faces that rule would take: 0 on all 63. Shell radii come from the
    renderer's own `wheel split of` log lines (`underpan_wheels.json`).
  - The kit's `underbody` (also the wheel-well liners and the chassis boxes) is now `carkit.tex_underbody()`,
    road-grimed grey ~66.
  - `build.py` adds the pan after the orientation fix. A rebuild of 050 from source reproduces the shipped files byte
    for byte; only `.mesh`, `_underbody` and `_underpan` differ from before.
  - Offline: `tools/vehicle_art/under_view.py <models> <name> out.png` (upright under the sill, rolled 180 deg).
  - In game: `[devtools] vehicle_feel2=0` + `force_body_roll_deg=180` draws every live car on its roof. Probe:
    `keys_va11_own.sh` with `VA6_SETS=t:...|f:vehicle_feel2=0,force_body_roll_deg=180` and poses `high` / `fl34` /
    `under`. Before `out/va13_up_b0` (050 018 000 012 013), after `out/va13_up_a0` (same cars, first floor rule) and
    `out/va13_up_a1` (shipped files: 050 018 000 013 004 011; 0 FAULT, 0 'could not be read'). Rolled 180 deg, the
    flipped cars were black slabs (kit and shells alike); now a grey pan with tunnel, rails, sump, propshaft, axle,
    differential, exhaust, silencer and tank. Upright from 15 cm beside the sill, only a thin dark band under the
    sills shows, as on a real car. Floor rule: the 15th percentile of the per-cell lowest points (centre or sill band),
    never more than 0.02 under a side skirt.
  - Short of AAA: the shells' own undersides still show their projected texels round the pan (outer 20 % and the
    overhangs); the parts are plain boxes and tubes (no brackets, springs or brake lines); the pan is mid-grey in
    direct sun.
- Remix: new textures with no prims: `<NNN>_underpan.tga` (63 copies of one image, one hash), the 16 kit
  `<NNN>_underbody.tga` (one image, one hash). Every re-oriented kit .mesh has new normals: its prims are keyed by
  texture, so they should still apply. Untested under Remix.

## VEHICLE-ART-14 (10 Nov 2026)

- **Floor pan residuals (ART-13's short-of-AAA list), fleet-wide in `tools/vehicle_art/underpan.py`, no per-model
  paint:**
  - *Cover (shells and carkit v1 bodies).* Every downward-facing face of the body's lower half (geometric normal
    y < -0.72) is copied 1.2 mm outside itself into the pan's draw group and mapped planar to a new grime region of
    the shared atlas (`R_GRIME`). The image-to-3D shells' projected texels (black voids, sprite smears) under the
    arches, sills, bumpers and overhangs no longer show. Left out: faces the pan already hides; tyres (face centre
    inside 1.03 x the wheel-split disc, outboard); textures named glass/tyre/wheel/hub/rim/seat/interior/dash/lamp.
    Inside the flank round each wheel (2 x r, 0.30-0.72 x the half width) faces that lean down (y < -0.35) are
    covered too, since the noisy well kept black shards between the covered faces otherwise (0.88 x / -0.12 took
    flank paint beside the arches on the narrow 002, `out/va14_up_a7`).
  - *Kit bodies (vehicle_art2, marker wheels): geometry as ART-13* (0.80 x pan with its curled lip, 3 mm, parts,
    no cover, no arms) minus the frame rails (theirs are authored at the same height, 0.8 mm apart); only the darker
    atlas changes. Their undersides are authored, not projected texels. Note: the flipped 004 shows sawtooth combs
    along its own rails at the later sun angle with ART-13's files too (`out/va14_up_b1` vs `b0` an hour earlier),
    so they are not from this pass; they are still open (kit 004 self-overlap under the sun of 06:50 UTC).
  - *Wider pan (shells).* Between and beyond the wells the pan follows the body's own half width at floor level (0.96 x,
    clamped 0.80-0.95 x the half width) instead of a fixed 0.80, with a flat edge (ART-13's 2 cm curled lip crossed the body's own floor panels
    once the pan reached them and read as sawteeth, `out/va14_up_a6` 004). It hangs 6 mm under the measured floor (was 3),
    clear of the cover's 1.2 mm copies of the floor faces.
  - *Darker.* Pan base 64 (was 92), cast parts 46 (was 64), exhaust 64, tank 70, grime 50, sills darker than the
    centre. Suspension on the shells and carkit v1 bodies: a lower A-arm each side at every axle and a trailing link at the rear, tubes
    whose inboard end sits beside the tunnel (every face spans inboard of xin, no caps), so the wheel split takes
    none. Not on the kit bodies.
  - Check: `underpan.py <models> <out> --all`: 64 bodies, wheel-split hits 0 on each (pan, parts and cover);
    `car_mesh_orient.py check`: 0 INSIDE-OUT. Offline: `under_view.py`.
  - In game (parked, EXIT=1, PAINT 139,98,74, `_t` upright, `_f` = vehicle_feel2=0 + force_body_roll_deg=180;
    poses front34/high/fl34/under): before `out/va14_up_b0` (the ART-13 files), after `out/va14_up_a9`
    (shells 000 013 002 011, shipped files) and `out/va14_up_a12` (kit bodies 004 050 018 036, shipped files;
    `out/va14_up_b1` = ART-13's 004 at the same sun); iterations a0..a11. Flipped: the black
    void wells of 000/013/002 and the overhang plates are grime grey, the pan is dark grey with tunnel, rails, arms,
    axle, exhaust and tank; upright `under`: a darker sill band, otherwise unchanged.
  - Still short of AAA: the 000 Romero's wells keep a few black shards (shell faces that lean up); parts are plain
    tubes/boxes (no springs, brake lines or heat shields); the grime is one planar noise with no wet/dust variation.
- Remix: `<NNN>_underpan.tga` changed (one image for all 64 copies, new hash: the atlas gained the grime region);
  no other texture changed.
- **End-panel cracks and chevrons on the kit bodies (`tools/vehicle_art2/carkit.py` `Car.cap`, the 010 deck
  residual ART-12 listed):** the 010 Bulwark's tail panel had a black crack from the bumper up to the deck emblem. The
  body section's bottom-centre point sits 0.05 m off the centre line (`sepow(cos(pi/2), 0.08)` = (6e-17)^0.08), so
  the two mirrored cap fans left a wedge open between them. `cap` now pins a mirrored ring's two end points to x = 0.
  The same pass found the `underbody` region of the 050/051/056 tail caps (and the nose caps of 053/057/058/082),
  chosen by the ring parameter (v < 0.14), taking every fan triangle down to the centre: a dark chevron up the panel
  above the bumper. A cap region now takes only the fan's outer band (r > 0.8, at least 5 rings): a strip along the
  panel's bottom edge. A full kit rebuild against an unmodified one changes 11 .mesh files only (010 039 050 051 053
  056 057 058 059 060 082; no texture), each re-oriented and floor-panned as before. Offline previews
  (`build.py --preview`) and in game: before `out/va14_cap0`, after `out/va14_cap2` (parked, EXIT=1, PAINT
  209,164,116, poses rear34/chase/front34 and `tail` = 1 block behind at bumper height). The 010's flat deck and plain
  bonnet themselves were not reshaped.

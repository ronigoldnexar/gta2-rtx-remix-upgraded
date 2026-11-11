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
| 001 Wellard | 18 | good (VEHICLE-ART-24) | was a T-bird-style shell; now the sprite's late-1930s coupe, authored kit body | dark kit glass | out/va24_a2 |
| 005 Beamer | 18 | good (VEHICLE-ART-24) | 1950s roadster with the sprite's dark hardtop, authored kit body (the shell drew black from the ground) | dark kit glass; plain hardtop | out/va24_a3 |
| 008 Bug | 5 | acceptable | Beetle, right | bonnet is a crumpled sheet of hard facets with a baked white specular streak; from the seat the bonnet drops out of view | z_door_008, S 008 |
| 010 Bulwark | parked | acceptable | 1950s Buick | flat planes across the bonnet, mustard blotches on cream paint | card_010 |
| 013 Minx | 3 | acceptable | boxy 1960s saloon | mild facets on the bonnet; windows opaque; otherwise the cleanest common car | z_door_013, S 013 |
| 014 Eddy | R/I | acceptable | 1957 Fairlane two-tone | the roof is the sprite's yellow on a red body (roof-colour defect) | card_014 |
| 016 Panto | R/I | good (VEHICLE-ART-25) | the sprite's 1960 Mini, authored kit body: one paint incl. the roof | estate-like side view (the sprite's 4.4 m footprint); dark kit glass | out/va25_a2 |
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
| 028 Dementia Limousine | D | good (VEHICLE-ART-24) | the sprite's stretched bubble car (029's section drawn out), authored kit body | AO streaks before the rear arch | out/va24_a6 |

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
| 047 Meteor | parked | good (VEHICLE-ART-25) | late-1950s sports-racing coupe, authored kit body: one paint, painted bubble roof, twin bonnet intakes | plainer than the shell's sculpted pontoons; dark kit glass | out/va25_a3 |
| 048 Meteor | parked | good (VEHICLE-ART-25) | 047's body with the sprite's open engine bay and bonnet blower | engine detail coarse up close | out/va25_a3 |
| 053 Michelli Roadster | 17 | good | 250 California style, cream, red interior | - | card_053 |
| 062 Trance-Am | I | acceptable | gold Firebird | tan sprite roof on a gold body; windows baked dark | card_062 |
| 071 Rumbler | R | good | red muscle car, twin stripes | - | card_071 |
| 082 Jagular XK | R | good | dark green XK120 | - | card_082 |
| 083 Furore GT | I | good (VEHICLE-ART-25) | 275 GTB-idiom berlinetta, authored kit body: one paint, the sprite's white centre stripe as its own decal | dark kit glass; large oval mouth | out/va25_a2 |

### Vans, pickups and trucks

| Model | Rank | Score | Identity vs sprite | What is wrong (close) | Frames |
|---|---|---|---|---|---|
| 004 G4 Bank Van | 12 | good | 1950s armoured van, white roof | - | card_004 |
| 007 Box Truck | R | good (VEHICLE-ART-24) | late-1930s box van, authored kit body: ribbed box, roof ridge and frames, rear doors | flat box panels, bulbous cab | out/va24_a7 |
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
- **013/068 liner re-light (the 063's recipe, VEHICLE-ART-11):** `m013_minx.py` and `m068_van.py` give the cabin
  liner its own light grey-beige `interior_liner` material (0.46, 0.43, 0.38, shares the `interior` atlas) and lean
  its normals up (`-N + (0, 2.5, 0)`), so the cabin reads through glass instead of a black hole. Only `.mesh` and
  `_0.tga` change for each (rebuild + import + floor pan; an unmodified rebuild reproduces the shipped files byte for
  byte). Plain renderer: no visible change (the windows are the glass mask pass over its own cabin shell, and first
  person draws the renderer's cab: `out/va14_lin_b0` vs `out/va14_lin_a0`, t_cab_013/068; the a0 frames carry a
  damage flash and b0's 068 an explosion glare, not from the models). It is for Remix, where the asset's glass is
  what draws: `013_minx_0.tga` and `068_van_0.tga` are re-baked (new hashes; neither had a prim) and still need the
  glass prim.

## VEHICLE-ART-15 (10 Nov 2026)

- **012 Cop Car authored (`tools/vehicle_art2/car_012.py`; prmx 'police car door and flank livery chunky green-white
  pixel smear').** A plain-GL take first (`out/va15_cop_b0`, parked own car forced to 12, EXIT=1, wil 198.5,188.2) showed
  the smear is the asset's, not Remix's: the image-to-3D shell's atlas (`012_cop_car_0.tga`) carries a green-grey roof
  with stair-stepped blue blotches, a mottled bonnet and a white/blue pixel door. 012 is a livery (identity.cpp
  `Livery`: drawn untinted), so the kit body carries its own colours. Read from the x4 sprite nose down (the kit's
  convention: 008/036/040/057): a long bonnet with a centre crease (the sprite's split panel) ending in a dark grille
  notch, a raked screen, a long roof with the light bar, a short boot; white roof and bonnet/boot centres, navy wings,
  flanks and shoulders (the sprite's navy wing tips), a chrome belt moulding, white door panels on both doors with a
  gold CITY shield and star on the front door and POLICE on the rear door. The door panel is cut out of the shell and
  laid back as two pieces (`paint_door_r` / `paint_door_l`) with their own UVs (t by height: the lower side crowds its
  top 15 cm into v 0.496..0.5), so the lettering reads the right way round from outside on both sides at 600 px/m
  drawing resolution. Light bar at -0.25 m (DrawBeacons' along -0.05 x length) with the red dome on -x and the blue
  on +x where the renderer puts its glows (force_sirens=1 frames: each glow over its own dome); grey siren block,
  driver's A-pillar spotlight, round lamps proud of the nose panel, twin round tail lamps, plate PD 012. Driver seat
  [0.09, 0.14, 0.04, 0.308]. `car_mesh_orient.py check`: ok (0 inside-out). Before `out/va15_cop_b0`, after
  `out/va15_cop_a2` (poses side/front34/rear34/eye/far/chase/high + `door` = 2.5 m beside the doors at 0.9 m; set s =
  force_sirens=1); `out/va15_cop_a1` = the first build (domes on the wrong sides of the glows, the belt moulding a
  16 cm grey band from the same v crowding).
  - Beacon note (car_bodies.cpp, not this seat): the sprite has the red dome on the car's left and blue on its right
    (nose down: blue image-left); DrawBeacons puts red on the other side, and the model follows the glows.
  - Still short of AAA: a boxy three-box body (reads more 1960s than the catalog's early-1950s Mainline at front34);
    slab flanks with no wing creases or chrome spear; the grille a flat bar box; no interior radio/shotgun rack.
  - Remix: all 012 textures are new (no prims): `012_cop_car_paint_body_paint`, `_paint_top_paint`,
    `_paint_door_r_paint`, `_paint_door_l_paint`, `_paint_wheel_paint`, `_beacon_red`, `_beacon_blue`, `_siren`,
    `_plate`, `_trim_dark`, `_glass`, `_chrome`, `_chrome_disc`, `_grille`, `_lamp_head`, `_lamp_tail`, `_lamp_amber`,
    `_seal`, `_seat`, `_interior_dark`, `_tyre_side`, `_tyre_tread`, `_underbody`; the old `012_cop_car_0*..12` are
    gone (backups `/mnt/gta2/gta2-linux/backup_va15/models_012`).
- **013 Minx re-authored to the kit standard (`tools/vehicle_art2/car_013.py`, audit item: ART-14 did not start it).**
  The carkit-v1 body (`tools/vehicle_art/m013_minx.py`: a tall bubble glasshouse over a short body, shader-painted
  shut lines, big fins) becomes a vehicle_art2 body read from the sprite nose down: a long bonnet with a raised centre
  panel (two low ribs: the sprite's two lines), a wrap-around screen, a big glasshouse under a black vinyl roof (the
  sprite's dark roof area), one long door, a large rear quarter light, a wide back light, a short boot between two
  small fins ending in round tail lamps, a full-width bar grille between single round lamps, slim wraparound bumpers,
  a chrome belt line and side spear, whitewalls (the shipped car's), front buckets and a rear bench. Neutral 235 paint
  tinted by the identity record. The cabin liner keeps 1b59d00's light grey-beige (`interior_liner`, 117,110,97) with
  its normals leaning up (`-N + (0, 2.5, 0)`). Driver seat [0.09, 0.132, 0.02, 0.312]. `car_mesh_orient.py check`: ok.
  Before `out/va15_013_b0`, after `out/va15_013_a0` (parked, EXIT=1, PAINT 150,92,58, poses side/front34/rear34/eye/
  far/chase/high/door), first person `out/va15_fp_a1` (t_cab_013_*). Still short of AAA: the side glass is the kit's
  dark tint (no visible cabin by day, as every kit body), slab door skins with no swage line, the whitewall band is
  the kit's full outer sidewall (wide). Remix: every 013 texture is new (`013_minx_paint_body_paint`, `_paint_trim_paint`,
  `_paint_wheel_paint`, `_vinyl`, `_interior_liner`, `_glass`, `_chrome`, `_chrome_disc`, `_grille`, `_lamp_head`,
  `_lamp_tail`, `_lamp_amber`, `_plate`, `_trim_dark`, `_seal`, `_seat`, `_interior_dark`, `_tyre_side`, `_tyre_tread`,
  `_whitewall`, `_underbody`); the old `013_minx_0..` textures are gone (backups `backup_va15/models_013`).
- **069 U-Jerk Truck authored (`tools/vehicle_art2/car_069.py`; rank 7 Downtown, the most-seen body still an image-to-3D
  shell).** The shell (a fair Model AA silhouette, but blotched box sides, a crumpled cab roof, an empty window hole
  for a cab and balloon tyres) becomes a kit Model AA stake truck read from the sprite nose down: a closed cab with a
  rounded roof (058's cab loft, the sprite's tan roof), a narrow bonnet with side louvres to an upright chrome radiator
  shell round a honeycomb, black wings sweeping into running boards (039's fender), headlamps on stalks with a tie bar,
  cowl lamps, a double tube bumper; behind the cab a tall open-top box of dark plank slats between painted stakes and
  rails, a front board, a lower tailgate and five arched cross bows (the sprite's dark ribbed bed). Painted parts
  (cab, bonnet, rails, wheels) neutral 235 tinted by the record; wings, running boards, wood and louvres untinted.
  `forward: +z` kept, driver seat [0.08, 0.244, 0.03, 0.40]; `car_mesh_orient.py check` ok. Before `out/va15_069_b0`,
  after `out/va15_069_a0` (parked, PAINT 162,133,102, poses side/front34/rear34/eye/far/chase/high/door). Still short
  of AAA: a plain rounded cab with no door shut lines on the wood, pressed-steel disc wheels where the Model AA had
  spokes, a flat honeycomb radiator. Remix: every 069 texture is new (`069_u_jerk_truck_paint_body_paint`,
  `_paint_rail_paint`, `_paint_wheel_paint`, `_wing`, `_wood`, `_louvre`, `_grille`, `_glass`, `_chrome`,
  `_chrome_disc`, `_frame`, `_running_board_rubber`, `_plate`, `_lamp_head`, `_lamp_tail`, `_lamp_amber`, `_seal`,
  `_seat`, `_interior_dark`, `_tyre_side`, `_tyre_tread`, `_underbody`); backups `backup_va15/models_069`.
- **027 Ice-Cream Van authored (`tools/vehicle_art2/car_027.py`; rated acceptable: 'the cone is a lumpy melted
  shape').** The shell was also off-identity: a pink and white van, where the classic sprite draws a warm cream box, an
  orange cone, a cream swirl and a tan cab. Now, read nose down: a rounded tan 1950s pickup cab (058's loft) with a split
  screen, bar grille and pontoon wings; a tall cream box with an orange belt band, a serving hatch (translucent glass,
  a lit cream wall and a chrome counter) under a striped orange/cream awning on each side, ICE CREAM boards that read
  the right way round on both sides (box x-faces map image columns to height: `sign_r` / `sign_l`); on the roof a waffle
  cone lying tip-back on its bottom line and a rippled soft-serve swirl spilling forward over the cab (squashed to 0.6
  of its height about the roof). A livery (drawn untinted). Driver seat [0.10, 0.256, 0.043, 0.422];
  `car_mesh_orient.py check` ok. Before `out/va15_vans_b0` (own_*_027_t; that take forced PAINT 150,150,150),
  after `out/va15_027_a0` (no forced paint; poses side/front34/rear34/eye/far/chase/high/door). Still short of AAA:
  the swirl reads as a smooth horn from the side (no piped-cream spiral), the awnings stand 0.55 m proud of the
  footprint, a plain box rear. Remix: every 027 texture is new (`027_ice_cream_van_paint_cab_paint`, `_paint_box_paint`,
  `_paint_band_paint`, `_paint_wheel_paint`, `_awning`, `_sign_r`, `_sign_l`, `_waffle`, `_icecream`, `_wafer`,
  `_interior_shop`, `_glass_hatch`, `_glass`, `_chrome`, `_chrome_disc`, `_grille`, `_frame`, `_trim_dark`, `_plate`,
  `_seal`, `_seat`, `_interior_dark`, `_lamp_head`, `_lamp_tail`, `_lamp_amber`, `_tyre_side`, `_tyre_tread`,
  `_whitewall`, `_underbody`); backups `backup_va15/models_027`.
  - **Withdrawn (09:25 UTC, e6d3f4a):** with the authored 027 in a stage, scripted runs flaked into 'player not
    found' (the game's object pool placed above 2 GB, rejected by `game::PlausiblePointer`; out/va15_000_b0..b2, A/B
    out/va15_ab27_old with the old 027 enters in 13 s). The old shell files and manifest entry are back; `car_027.py`
    waits for the renderer fix (open BLOCKER 'player-not-found-when-game-pool-lands-above-2gb'). The kit bodies add
    texture memory (012: four 512 paint pictures): later kit bodies should keep their paint pictures to one 512 and
    flats at 16 px.
- **000 Romero authored (`tools/vehicle_art2/car_000.py`; rank 8, the image-to-3D shell ART-14 left with black well
  shards; its side glass carried the body paint).** Read from the sprite nose down: a long bonnet with a chrome centre
  spine to the nose emblem, a wrap-around screen, a long roof, the sprite's big triangular back light tapering to the
  tail with its centre bar, a short deck between small fins, four doors, a chrome shield grille between low side
  grilles and quad lamps, slim chrome bumpers, a side spear. Neutral 235 paint tinted by the record. Driver seat
  [0.09, 0.132, 0.02, 0.304]; `car_mesh_orient.py check` ok. Before `out/va15_000_b3`, after `out/va15_000_a0`
  (parked, PAINT 140,40,40, poses side/front34/rear34/eye/high/door; stage = 012/013/069 authored + old 027: the level
  entered normally). Still short of AAA: a boxier silhouette than the shell's Giulia line, dark kit glass, slab doors.
  Remix: every 000 texture is new (`000_romero_paint_body_paint`, `_paint_trim_paint`, `_paint_wheel_paint`,
  `_interior_liner`, `_glass`, `_chrome`, `_chrome_disc`, `_grille`, `_lamp_head`, `_lamp_tail`, `_lamp_amber`, `_plate`,
  `_trim_dark`, `_seal`, `_seat`, `_interior_dark`, `_tyre_side`, `_tyre_tread`, `_underbody`); backups
  `backup_va15/models_000`.

## VEHICLE-ART-16 (10 Nov 2026)

The 2 GB rule (BLOCKER 'player-not-found-when-game-pool-lands-above-2gb', fixed by FIX-POOL-LAA 7b36ca7) set a texture
budget for kit bodies: one 512 paint picture, flats at 16 px, detail pictures 64-128, no texture above 512 except a
livery's lettering panel. Every take below ran on a private stage built from HEAD (with 7b36ca7) and was checked for
'view: player' and 'player not found' in the log: the player was found in every run, the level entered in 11-15 s,
0 FAULT. No DLL change: the classic view is unchanged by construction (it draws no car models). Poses: gamerun
va11_own.py, parked (EXIT=1) at wil 198.5,188.2, side/front34/rear34/eye/far/chase/high/door; the x4 sprite (nose down)
beside every sheet. A forced model draws untinted unless PAINT= is set (the 027 livery is tinted by a forced PAINT too:
a probe artifact; traffic draws it in its own colours).

- **027 Ice-Cream Van re-added to the budget (`car_027.py`, ART-15's body).** 32 -> 22 textures, 4.6 -> 2.7 MB:
  one 512 paint picture (the box; the cab 256), both ICE CREAM boards in one 256 x 512 picture (new `uv_rect` option
  on `carkit.Car.box`: each face maps its picture into a rectangle of the texture), the orange belt band painted into
  the box picture, the shop wall/plate in the box paint, frame/skirt/seal in `interior_dark`, the wafer in the waffle
  picture, detail pictures 64-128. The soft-serve is a piped spiral (the ridge winds 4.5 turns to the tip) instead
  of stacked rings; the awnings reach 0.40 m (was 0.55). Before `out/va16_027_b0` (the shell: pink van, melted cone),
  after `out/va16_027_a0`; five fresh sessions with it loaded (`va16_027_a0`, `va16_s2`..`s5`: 14.3/14.3/11.7/12.7/
  12.7 s to the level). Still short of AAA: the swirl reads as a smooth horn from the side at chase distance, the
  hatch interior is the box paint (no fittings), the rear doors are drawn lines.
- **067 TV Van -> 068's mesh (manifest `cars.by_model` "67": "068_van").** The two sprites are pixel-identical; 067's
  image-to-3D shell had a black hole for a rear window, a crumpled grille and smeared paint, while 068 is the
  carkit-v1 step van. 067 is a painted car (identity.cpp `Livery` excludes it since FIX-CAR-IDENTITY-3), so the
  record's tint carries over: `out/va16_s4` (PAINT 150,92,58: 067 and 068 identical, tinted). Before `out/va16_s2`.
  068 (item 2) needed nothing: it is already the authored step van (c152690), not the loaf.
- **014 Eddy authored (`car_014.py`; audit item 8 roof colour; 084 Special Agent Car draws the same mesh).** A 1958
  Edsel-style two-door sedan read from the sprite: flat bonnet, wrap-around screen, long flat roof a shade lighter
  than the body (luminance only), upright back light, deck between modest fins, the horse-collar grille in a chrome
  oval between low side grilles, quad lamps, gull-wing tail lamps, heavy bumpers with guards. 17 textures, 1.8 MB.
  Before `out/va16_s3` (blotched silver shell with torn wings, sprite-coloured roof), after `out/va16_s5` (untinted)
  and `out/va16_s7` (PAINT 184,120,72). Still short of AAA: the kit's dark side glass hides the cabin by day, slab
  doors without the Edsel's side cove, a plainer and boxier body than the shell's flamboyant line.
- **046 Stinger authored (`car_046.py`, from 053's fastback loft).** A 1963 Sting Ray coupe: pointed prow with a centre
  bulge, wing creases, short raked screen, a roof spine running down the fastback and splitting the rear window (the
  sprite's two small panes), boat tail with four round lamps, gill vents, split bumperettes, a dark low grille. 13
  textures, 1.8 MB. Before `out/va16_s3`, after `out/va16_s7`. Still short of AAA: no hidden-lamp pods (the faired
  lamps are buried in the prow), the side view is a generic GT rather than the C2's sharp belt crease.
- **062 Trance-Am authored (`car_062.py`, from car_046).** A late-60s Trans Am: chrome beak between twin dark grille
  openings with round lamps, long bonnet with a shaker scoop and the bird painted dark into the paint picture
  (luminance only: a box decal's alpha draws opaque, a black square), wide wrap-round back light, duck-tail spoiler,
  fender vents, dark slotted wheels. 13 textures, 1.8 MB. Before `out/va16_s3`, after `out/va16_s8` (PAINT
  190,128,74). Still short of AAA: the scoop is a plain dark box, the bird is a soft silhouette, no rear quarter
  louvres.
- Checked, not changed: the kit bodies 036/008/056/018/050 at HEAD (`out/va16_s6`): 036's lamps are sealed beams in
  chrome bezels (pods proud of the nose, not blobs); 008's wings are bulbous; nothing that reads wrong at chase distance.
- `car_mesh_orient.py check`: ok for 027/014/046/062. Remix: every texture of the four bodies is new (list in the
  NOTE-1031 beside the prmx11 order); 067 adds none.

## VEHICLE-ART-17 (10 Nov 2026)

- **pmt5 taxi colour (identity rule, 910879d; docs/identity-system.md section 13).** The no-clip cap tested luminance, so a
  saturated livery's red clipped alone: the 051 taxi drew lemon (+29 % L*, hue 7 deg off on the body, 14 on the lids) at
  the gate's sunny spot. Per-channel top + a saturation-held ceiling: body 209,136,20 against the filer's sprite
  206,130,33, +13 % L*, hue 4 deg; gate 0 FAIL; classic vreg spawn_classic 0 tiles.
- **Remapped liveries keep their stripes (pmzz; `tools/vehicle_art/livery_stripes.py`).** Twelve 071 Rumbler remaps
  all draw two pale stripes over bonnet, roof and boot; the game recolours the body only. The generated 3D body had
  stripes on one atlas panel only, and under Remix the split pair is one merged surface the tint multiplies whole
  (FIX-REMIX-MATERIALS-7's note). The stripes are now their own geometry: the body's up-facing paint triangles
  clipped to the sprite's stripe shapes (pixel columns/rows of the nose-down sprite mapped onto the mesh's x/z
  extents), lifted 0.0012 block along their normals, drawn with `<NNN>_<name>_stripe.tga` (32 px flat pale picture,
  not a `_paint` texture: never tinted; under Remix a lone prim of its own, so it stays pale there too). A scan of
  every remapped sprite for texels pale in ALL remaps found four such liveries: 071 (two stripes), 083 Furore GT
  (centre stripe: deck, roof, bonnet piece), 049 Hachura (thin centre stripe) and 019 GT-A1, whose 3D art already
  carries its stripe and roof roundel (frame `out/va17_p2` pt_top3_019: left alone). Before: the bil kerb Rumbler as
  a plain dark coupe (pmzz evidence); after `out/va17_p3` (own car forced to 71/83/49 in red and green, poses
  top/top3/chase) and `out/va17_p2` (yellow): pale twin stripes over bonnet, roof and boot of the 071 in every paint;
  the 083's roof and deck stripe; the 049's boot and roof stripe. Paint parity of the bodies unchanged (stripes are
  the same in both paints, outside the change mask). Backups `/mnt/gta2/gta2-linux/backup_va17/models_stripes`;
  the cars archive (release-v1.6) carries the three `_stripe.tga`. Remix: 3 lone prims (322C0051BDFF516C 071,
  6299E81F2E6F8D02 083, B188186F5C4E5473 049), `remix_car_prim_check --pattern '.*'` 0 missing; DDS in
  `layer_deploy/VEHICLE-ART-17/` (not path traced yet).
  - Still short of AAA: the stripes are flat matte decals with no clear coat over them; triangle-clipped from a
    TRELLIS mesh, they end where the paint split ends, so the 049's stripe stops at its bonnet (that bonnet is in the
    untinted half: it draws white whatever the paint, a generated-body split fault) and the 071's stops short of the
    nose; the sprite's stripe width is used as is (no taper over the roof).
- **063 Truck Cab (audit rank 1; `tools/vehicle_art/m063_truck_cab.py`).** Filmed at eight truck-scaled poses
  (`out/va17_063b0`: parked EXIT=1 at wil 198.5,188.2, `POSES_EXTRA` tside/tfront34/trear34/teye/tfar/tchase/thigh/
  tdoor, own paint 120,89,66 = the sprite's remap mean). What read short: from above (the classic camera's sprite
  angle, chase and high) the roof carried two 10 cm dark nubs where the sprite draws two big lit roof lamps; the cab
  sides were one smooth toy panel (0.9 cm shut lines vanish beyond 3 m); no roof-edge definition. Changed: 15 cm
  roof lamps on pedestals, lens tilted 50 deg up from forward, chrome bezel, black housing (FIX-CABIN-DOME's rule);
  chrome drip rails along both roof edges (conformed to the cab); shut lines 1.5 cm and darker with a lit lip, hinge
  shadows, a second swage line. Generator reproduced byte for byte first (glb, mesh, _0/_2/_2_paint identical;
  the shipped `_glass.tga` is kept: the glass group is unchanged, its pane picture matched byte for byte).
  After `out/va17_063a0` (same poses; frames opened: two bezelled lamps from above, rail along the roof edge,
  door shut line, hinges and swages from the door pose; chase shows the lamp housings). FP cab `out/va17_fp063`
  (still/left/drive: nothing intrudes). Paint parity (out/va17_pool1, red/green) +19/+18 % as in the gate. Pool
  test: five fresh sessions (063a0, fp063, pool1-3) to_level 12.7-14.8 s, 'player not found' never, 0 FAULT.
  Textures unchanged in count and size. Remix: `_0` A77F1BEB81877CE7 (its emission now includes the roof
  lenses, as the old _0 did the head/tail lamps), `_2_paint` C536668663B86CA4; 0 missing; DDS in the bundle.
  Backups `backup_va17/models_063`. Still short of AAA: a smooth single-curvature cab with a plain back wall, the
  lenses read pale grey (not lit) in daylight, chassis and fifth wheel flat black boxes, rubber-less mudflaps.

## VEHICLE-ART-18 (10 Nov 2026): 036 lamp pods, 012 grille, 034 / 044 / 086 authored

Probe for all of them: `gamerun/va11_own.py` parked (EXIT=1) at wil 198.5,188.2, the car forced to each model, fixed
regression-camera poses (car poses side/front34/rear34/eye/high/far/lamp; bus-scaled `POSES_EXTRA` b*/x* poses for the
7-8 m bodies). Before `out/va18_b0` (036 056 012 on the a8b6b946 stage), after `out/va18_a036`, `out/va18_a1` (034,
012), `out/va18_a2` (044, 086), FP `out/va18_fp1` (keys_fixfp2_cab, force_own_car_model 44 / 86). 0 FAULT and 0 model
read errors in every run. Paint gate `out/va18_gate3_parity.md` 0 FAIL. No DLL change: classic unchanged by construction.

- **The paint gate was blind (fixed, 1569a1d).** Since cd5bb11e a comment in `package/gta2dx9.ini` (line 513) carried
  the literal text `[devtools]` ahead of the real section (line 686). `paint_parity_probe.py` (and ~40 runners that add
  a key with `replace("[devtools]", ...)`) wrote force_car_model / force_car_paint into that comment, so the gate filmed
  the real car in every frame and reported 'no car found' (out/va18_gate1, va18_gate2). The comment now says
  "devtools keys"; never put a section name in square brackets in an ini comment.
- **036 Schmidt (rank 4).** The headlamps were pancake discs sitting on the blunt nose. Each now sits in the mouth of a
  faired nacelle on the wing crown (swept paint pod from 1.22 m back, chrome bezel, the sealed beam inside), added after
  the AO bake; the atlas still re-bakes because the old discs no longer shade the deck (one Remix prim).
- **012 Cop Car.** The grille was a flat painted-bar face with a 20 cm chrome dome: now a black recess behind five thin
  chrome bars and two side posts, with a slim pointed spinner. The grille texture is gone.
- **034 Medicar (qaexp7).** Authored (`car_034.py`): 1959 Cadillac / Miller-Meteor ambulance, cream over maroon, lamp
  rack with four red domes behind the screen, the roof star of life, crosses on the compartment panels, rear doors.
  A livery painted **by position** (`tex_livery`: each texel's point on the body decides cream / maroon / pinstripe /
  star), and the end caps take a strip by height (`tex_end`): a cap is a fan to its centre, so it cannot use the body
  atlas (the first take's tail was one salmon blend of both colours).
- **044 Arachnid (pmw1 slabs, qav10 FP hood).** Authored (`car_044.py`): a Duetto-style spider. The open cockpit is
  part of the body surface (inside the sprite's oval the deck sinks into a tub), the seats are solid boxes, so there is
  no free-standing plane to draw as a black slab; the FP view shows no void.
- **086 Karma Bus (qav7 body half).** Authored (`car_086.py`): 1950s school bus, rub rails, raised roof hatches with
  smoked lights (the sprite's dark hatches), emergency door with two panes; no holes. The lower side's v mapping is
  spread (`sepow(s, 0.85)`) so painted rails are several texels tall.
- Texture budget: 034/044/086 together 55 textures and 7.0 MB against the shells' 51 and 18.3 MB.
- Remix: 22 new prims (`remix_car_prim_check` 0 missing per model), DDS in `layer_deploy/VEHICLE-ART-18`; not path
  traced.
- Still short of a shipping-AAA frame: 036's pods are plain swept tubes; the 012 grille bars are uniform rods; the
  034/086 bodies are single-loft boxes without stamped door skins, gutters or rivets, chrome bumpers without
  over-rider detail; the 044 cockpit reads as a near-black well at chase distance (dark leather on dark trim, as the
  sprite); none filmed at the filers' own spots, at night, driving, or under Remix. The kit bodies' light mottle in the
  street views is not in their textures (they are smooth); it comes from the renderer's light, not from the paint.

## VEHICLE-ART-19 (10 Nov 2026): Remix baseline of ART-18's cars, 054 Tank camo, 064 Truck Cab SX authored, plates

Probes: `gamerun/va11_own.py` parked (EXIT=1) at wil 198.5,188.2 with fixed regression-camera poses (car poses for 054,
truck-scaled `POSES_EXTRA` t* poses for 064), private stage `stage_va19` (16c259ac stage + ART-18's model files).
0 FAULT and 0 model read errors in every run. No DLL change: the classic view is unchanged by construction.

- **Remix baseline (out/va19_rx1, `frm2_remix.sh` + `keys_frm2_own.sh`, 13:00 and 22:00, 034/044/086/036/012).** Path
  traced. What falls short (the full list is on the audit order): one uniform semi-matte coat on every paint panel (no
  clear-coat reflection of sky or street on the big flats; only chrome reflects), flat single-loft flanks on 034/086 with
  the 086's rub rails smearing over the rear arch, opaque black side glass on 034/086/012, a baked dark AO smudge behind
  the 044's front arch and a hard dark crease at the 036's rear arch. Hour 22 in this harness is dusk, not night.
- **054 Tank (qaexp13; `tools/vehicle_art/sprite_camo.py`).** The image-to-3D hull drew a pale grey-olive in sun and
  near-black olive in shade: 96 % of the hull is in the untinted base half, whose texels were the generator's grey
  undercoat (median luma 12). Now the sprite's own picture is projected straight down onto the body (each covered texel's
  (x, z) picks the nose-down sprite pixel), times a little of the texel's own fine detail; down-facing faces darkened.
  Written into the base half (the camo is the sprite's art, not the record's paint) and into the paint half's RGB where
  its alpha is 0; the paint texels are left alone. Deterministic (rerun byte-identical). Before/after at the same six
  poses (out/va19_tank0 / out/va19_tank1): saturated green camouflage with light-green patches on deck and turret and
  dark tracks, where it was a grey hull. Short of AAA: the top-down projection streaks vertically down the turret's steep
  sides, and the TRELLIS hull's lumpy geometry (crumpled side skirts) is unchanged.
  Remix: the pair's maps are built matte (armour, not car paint): `remix_model_materials.py ... --pattern
  '^054_tank_0(_paint)?\.tga$' --paint-roughness 0.72 --paint-metallic 0.0` (only the .r/.m maps differ from the default
  build; the prims are the same text). With the car-paint default (roughness 0.18) the camo path-traced as a glossy
  coat (out/va19_rx2).
- **064 Truck Cab SX (qav17; `tools/vehicle_art/m064_truck_cab_sx.py`).** The truck in qav17's ste frames is the 064
  (the filer's log: dented copy, door split and seat of 064_truck_cab_sx alongside the van). Its image-to-3D shell drew the
  sprite's pale band across the cab back as a flat tan bar, the corner stacks as silver slabs ("torn chrome") and the two
  roof lights as crumpled shards. Now authored in the carkit from the 063 generator (cab, doors, glass, tanks, chassis,
  wheels, lamps and paint rules shared), with what the 064 sprite draws differently: a broad rounded hood filling the
  width between the wings with a small low chrome grille and headlamps set into its corners; two oblong chrome-rimmed
  roof lights lying fore-aft with amber lenses; a raised painted roof lip across the cab back with a chrome rain strip
  and two pressed ribs down the back wall; upright chrome stacks with perforated shields at the cab's rear corners.
  Manifest: `cars/models_art/064_truck_cab_sx.glb`, paint 235 (identity tint), 1024 px, the 063's seat, translucent
  glass (`glass_translucent.py`). In game (out/va19_t64a, forced 64 + paint 120,89,66, six truck poses incl. the filer's
  rear-left angle): one whole truck, the back is paint with the lip and ribs, no bar, no slabs, no shards. Textures
  12.6 MB when drawn (the 063's set) against the shell's 2.3 MB. Short of AAA: the cab is the 063's single-curvature
  shell; hood and lip are smooth lofts without stamped seams; the roof lights are boxes, not cast housings.
- **064 paint gate.** With the 063's coat the 064's red record read +25 % L* (FAIL, out/va19_gate1_paint.md; its broad
  sunlit hood and the roof lip add lit lid area, the 063 is +20 %). A darker coat overall changed nothing
  (out/va19_gate2_paint.md: the renderer measures each body's own paint and normalises the tint); the up-facing hood and
  lip texels now carry a 14 % deeper coat: red +24 % WARN, 0 FAIL (out/va19_gate3_paint.md, beside the 063's +20 %).
  054 in the gate (livery class, own colours): 44,57,21 against the sprite's 49,64,21, -12 % L* WARN.
- **002 Aniston BD4: tried and withdrawn.** A kit body from car_082's surface (fastback, long creased bonnet, wide low
  grille) was built and filmed against the shipped shell at the same six poses (out/va19_002b shell, out/va19_002a kit):
  in game the shell reads as a detailed DB4 (grille, chrome, plates, proportions) and the kit body as a smoother toy
  car. Not shipped; the shell stays (backup_va19/models_002 = the shipped files). The 002 needs a dedicated authoring
  pass with its grille, plates and door gaps before it beats the shell.
- **Plates (qaexp11): no change.** At the same close rear pose, parked (out/va19_plate2) and as the player's own car
  (out/va19_plate3), the shipped plate files read left to right ("RM 000", "MX 613"); the same files mirrored read
  backwards. The shipped `*_plate.tga` are right for the current meshes (u runs along -x on the -z face).
- **Kit paint mottle in the street views (order 5): it is the SSAO, measured, not fixed.** Same-spot A/B with live
  toggles at the 044's side pose: car_world_sun 0/1 and shadows 0/1 leave the cloudy blotches unchanged (out/va19_mot1);
  a paint texture with its low frequencies flattened leaves them unchanged (out/va19_mot2); `[visuals] ssao=0` removes
  them (out/va19_mot3). The half-resolution AO (src/post_fx.cpp, ssao8/12 + ao_blur, ao_strength_percent 75) breaks up
  on large smooth panels. A fleet-wide fix belongs in that pass (normal-aware blur or a cap on gently curved surfaces).

## VEHICLE-ART-20 (10 Nov 2026): the holes are the opening door; coach and stake trailer

Probes: `gamerun/va11_own.py` parked (EXIT=1) at wil 198.5,188.2, the parked car forced to each model, fixed
regression-camera poses (`lside` beside the door, `rear34`, `high`), sets `d0` (door shut), `a0` (every car's door
open, `door_arch_clear=0`, the old span) and `a1` (door open, the new span): before and after in ONE run at the same
poses (`out/va20_dsF`, 28 models; `out/va20_G` on the rebased build). Pitfalls: `force_car_door=1` opens the side
the `lside` pose faces (-1 the far side; the side never changes while the door is held open); `va11_own.py`'s setkey
inserts a missing key after the FIRST literal `[devtools]` in the file, which in the stage ini is a comment: put the
key under the real header first or the toggle is dead (`out/va20_dsD`: a0 = a1). With `force_car_model` every car
keeps its own sprite's cabin measure, so the door span differs per car (a forced 040 opened 0.09..0.46 on the van).
A 28-model forced sweep with every door open and two spans built 239 door splits (244 MB) and hit the 3.9 GB memory
ceiling at 19:52 (street views off for the rest of that session): frames after it (models 037-068 in va20_dsF) are
not evidence. Keep such sweeps to ~15 models.

- **owner10nov-3 "vehicles with holes in ordinary play": what they are.** An offline scan of every shipped car mesh
  (`tools/vehicle_art/hole_scan.py`, 72 poses per model at 1-3 blocks: alpha-test holes where both halves of a paint
  pair are under 128, nearest and bilinear, and faces seen from their lit back side) finds no alpha holes on any closed
  model; the back-face count is dominated by open sheets by design (fenders, pans, tyres wound inward) and is a lead
  list, not a verdict. The holes a player sees are made at run time when a door opens (a ped boards or leaves any car,
  traffic included: qav29). The door box ran 0.27 of the body back from the sprite's windscreen foot (front edge capped
  at 0.42 of the length), so on most bodies it reached into an arch: the wing's rear, the arch lip and part of a tyre
  were cut out with the door, swung out as torn slivers and left a hole over the wheel (in `out/va20_dsF` a0: 001
  Wellard half the rear tyre on the swung door; 002 BD4 and 056 Taxi a wheel chunk on the door; 000, 005, 013, 019, 031,
  051 arch debris under the swung door; the 068 van's and the 063/069 trucks' doors over the front wheel).
  Fixed in `dll/src/car_bodies.cpp` (door span helper shared by the split, the boarding publish and the warm-ahead):
  the tyres are found on the mesh (`MeshWheelZFor`: vertices under 6 % of the roof at the sides, front and rear
  groups; the CARI axles missed shells' wheels by 5-6 cm), the door ends 1.3 tyre radii plus 1 cm from each axle
  (radius: the larger of the feel's and 0.22 of the height), keeps its length where it fits, its place where less
  than 0.6 of it fits, and is at most 0.30 block (1.1 m). The log prints `door span of <model>` once per model.
  `[devtools] door_arch_clear=0` restores the old span (A/B). After (a1, same poses): tyres and arches whole on all
  21 valid models; the door opening ends ahead of the rear arch and behind the front one.
- **qav29 (crushed sedan and taxi with flat dark slabs, hollow roof).** Not damage geometry: the filer's own log has
  door splits of `032_stretch_limousine` on both sides at the frame's second (span z -0.02..0.46 = 0.48 block): the
  limo's two doors, each a 1.8 m flat panel of a low-poly shell, swung out on both sides (one beside the taxi), and the
  hole they left made the roof a thin canopy. The 0.30-block cap makes them front doors of a normal size.
- **qaexp20 (tan bus-bodied coach with road tyres).** The coach is model 6, `006_box_car` (the filer's log: model 6
  sprite 6 in the train with 059 coaches and the 060 cab), a parametric bus-like loaf with road wheels. Manifest only:
  `by_model 6 -> 059_train`, VEHICLE-ART-7's authored cream coach on bogies (the 006 and 059 sprites are both cream
  rail cars).
- **qav27 (stake trailer's deck black with a faint grid).** The trailer is `066_transporter` (log: model 66 sprite 60).
  Its decks were dark steel grating (60,58,56 at 35 %/100 %), which drew near-black; the classic sprite shows brown
  planks. `tools/vehicle_art2/car_066.py`: both decks are `deck_wood` (11 weathered brown planks along the trailer, dark
  gaps, staggered butt joints, 118,82,52 at full tone); the folded ramps stay grating. Rebuild deterministic (every other
  file byte-identical); `066_transporter.mesh` + `066_transporter_deck_wood.tga` in repo/assets/models (backup
  `backup_va20/models_066`). Remix: one lone prim 59AE1281DB36B5CA (additions only, `remix_car_prim_check` 0 missing for
  066), DDS in `layer_deploy/VEHICLE-ART-20`.
- Classic view: vreg on the private stage, `spawn_classic` PASS 0 changed tiles (out/vreg_stage_va20c_1110_195654;
  the 3D shots' changed tiles are all the HUD's new minimap and hearts, FIX-HUD-4, against older goldens).
- Still short of a shipping-AAA frame: the swung door of an image-to-3D shell is a skin with no thickness and the opening
  shows a hollow shell (the dim cabin box helps only from the side); the kit bodies' door edges show rows of small black
  teeth along both the opening and the swung door (040 Maurice, not the span: unchanged a0/a1; not identified yet: the
  offline replica of the split shows none, so they are drawn by a later pass, e.g. the sun-shadow map on the thin edge);
  the 040's wing still loses a thin crescent to the door; door spans of forced models follow the wrong sprite's cabin.

## VEHICLE-ART-21 (10 Nov 2026): the black-box cabin is the seated band; 070 Z-Type and 041 Pickup authored

Probes: QA-VISUAL pass 50's own repro (`gamerun/keys_qa_qav50.sh` = `to_level.sh` + `va5_own.py`: wil 164.5,147.6,
noon, plain GL, the player's car parked and forced to each model, fixed regression-camera poses side / front34 / rear34 /
eye / wheel / high, `VA5_KEY` toggled per pose in one session). A forced model is drawn untinted (identity.cpp
`r.livery = ... || ref.forcedModel`), so these frames judge shape and finish, not paint colour: a neutral kit body shows
white, an image-to-3D shell its baked texture colour (the filer's "041 silver from above, black from the side" is that
texture under the sun, not two paints).

- **qav50 71 Rumbler / 83 Furore GT "flat black box standing on the body": the FIX-SEATED band, not a body box.**
  Offline renders of both shipped meshes (`tools/vehicle_art/mesh_preview.py`) show a normal raked greenhouse;
  `car_glass` 1/0 gave identical frames (out/qa_va21ab1). The log has `band box 071_rumbler ...`: both models have
  glass and a cabin (1620 / 1168 glass texels) but no rear screen (`rear screen 0`: the bakes paint it as body), and a
  seated car whose rear screen was not found kept FIX-SEATED's band. That draws the hull between 0.60 and 0.90 of the
  cabin roof at 40 % over VEHICLE-ART-5's opaque dark band box (straight-ended, flat-topped), with only the top tenth of
  the roof opaque: the black slab with the roof a faint shell behind it, on the player's car and every traffic car
  with a driver. `car_bodies.cpp`: a car whose glass was found now always takes the glass (as under Remix since
  VEHICLE-GLASS-4); `[devtools] glass_rear_gate=1` restores the old gate. `car_glass.cpp` logs the rear-screen texels
  and, for a body with under 200 glass texels, `painted windows kept (FIX-SEATED band when seated)`.
  Verified out/qa_va21ab2 (gate 0 vs 1, same session) and out/qa_va21ab3 (rebased build, dd489cab): 071 and 083 draw a
  raked hardtop in body paint, side glass with the cabin behind it, no slab, and from above the dark flank blotches are
  gone. 041's cab is glazed instead of banded. Control 051 is unchanged. The driver shows low through the windscreen
  (071 hair, 083 torso). No driver shows from straight behind: the rear screen is painted on these bakes, which was the
  band's purpose. Pane outlines follow the baked mask (ragged).
- **070 Z-Type authored (`tools/vehicle_art2/car_070.py`; qav50 "crumpled body, ghost canopy").** The shell had 0 glass
  texels (log line above), so a seated 070 always drew the band. That was the translucent grey canopy with the interior,
  a second arch and the driver ghosting through it, over lumpy image-to-3D wings and bonnet. The kit body is built on
  VEHICLE-ART-9's 018 Shark surface, read from the sprite nose down (2.66 x 5.0 m, axles +24/-18 px): the shark shear
  is removed for an upright narrow waterfall grille with a thin chrome prow strip, the sprite's chrome bonnet strip
  ends in an arrow ornament, the pontoon swells are stronger at both axles, the lamps are faired into the wing noses,
  the glasshouse is short and two-door (door glass, rear quarter light, windscreen), the teardrop fastback carries a
  small rear light, there is a boot handle, lamps on the tail, wraparound bumpers with over-riders, whitewalls, and
  benches, dash and wheel inside. Neutral 235 paint (tinted by the identity record), kit glass. Driver seat
  [0.084, 0.140, -0.016, 0.295].
- **041 Pickup authored (`tools/vehicle_art2/car_041.py`; qav50 "torn black pixel-stepped patches").** The patches
  are baked into the shell's atlas (offline preview: the black door blotch and the ragged grille surround), so no
  render setting cures them. The kit body uses VEHICLE-ART-9's 058 Tow Truck cab recipe, read from the sprite nose down
  (2.66 x 5.0 m, axles +18/-19 px, cab 18-33 px from the nose): a bonnet over the front wheels between pontoon wings
  with the headlamps in their noses, a wide bar grille in a chrome surround, a heavy bumper, a rounded two-seat cab with
  side glass, windscreen and a small rear light, mirrors on arms. The bed has a floor of dark planks along its length
  (the sprite's slats), painted sides with a rolled top rail and chrome stake pockets (the sprite's light dots), a front
  board, a tailgate with a chrome strip, rounded wheel tubs, running boards, tail lamps on the corners and a rear
  bumper. Driver seat [0.088, 0.200, 0.036, 0.373]. The first build hung the rear fender below the bed side as a thin
  bright arc (out/qa_va21z2). The tub now ends above the side's foot (out/qa_va21z3).
- Verified (frames opened): out/qa_va21z1 / qa_va21z2 (070 at all six poses: smooth uniformly shaded panels, a clean
  grille, lamps and glass, no canopy ghost; before = out/qa_qav50 own_*_070_1) and out/qa_va21z3 (041 side / rear34 /
  front34 / eye: one finish from every pose, no patches, a glazed cab, a planked bed). Offline: `car_mesh_orient` fix
  applied by build.py; `hole_scan.py` 070 max 20 % / 041 max 20 % back-face pixels. These are the wheel-well liners seen
  through the arches from the front at eye height and the floor pan, as on the shipped kit bodies (018 max 12 %,
  058 10 %, the same shoulder seam line on 058). Neither model shows alpha holes. Classic view: vreg stage
  spawn_classic PASS 0 changed tiles (out/va21a; the 3D shots' changed tiles are the new HUD against older goldens).
- Not verified: the paint-parity gate (`keys_paint_parity.sh` run out/va21pp1: the car was not framed, the state line
  put it at 130,195.8, away from the warp; SKIP "no car found"), so the sprite colour on these two bodies in traffic is
  untested. They follow the tint path every neutral-235 kit body uses. Also untested: Remix (no prims for the new
  textures: every 070 / 041 texture is new and draws from its base texture), night, moving traffic, first person
  (FIX-COCKPIT-CAB-5's cab tables have no entry for the new interiors).
- Still short of a shipping-AAA frame: the kit glass is dark, so no cabin or driver reads through it by day (every kit
  body); 070's wings are swells of one body section, not separate pontoons with a valley to a narrow bonnet, so it
  reads more 1940s fastback than 1936 Zephyr; 041's bed sides are flat slabs with box edges; the 071 / 083 bakes keep
  their image-to-3D facets, dents and ragged pane outlines (authoring them is the remaining cure).
- Model files: `070_z_type*` and `041_pickup*` in repo/assets/models (the shells' 34 files backed up in
  `/mnt/gta2/gta2-linux/backup_va21/models`): NEEDS A RESTAGE.

## VEHICLE-ART-22 (10 Nov 2026): 035 Benson, 030 Land Roamer and 029 Dementia authored; 027's cone-tip square was a NaN normal

Probes: QA-VISUAL pass 51/55's own repro (`gamerun/keys_qa_qav51.sh` = `to_level.sh` + `qav51.py`: wil 164.5,147.6, the
player's car parked and forced to each model, fixed regression-camera poses side / front34 / rear34 / eye / high, 18:30
clock paused, plain GL, GPU 5). Forced models draw untinted (identity.cpp), so these frames judge shape and finish:
a kit body shows its neutral 235 white. Before: out/qa_va22a (HEAD ac5813dd DLLs, the shipped shells).

- **qav55 027 "flat white square at the cone tip": 40 NaN vertex normals, not a lamp glow, sprite or body art.**
  The square stayed with `car_lamp_lens` 1 and 0 (out/qa_va22a), so it is not FIX-LIGHTS-1's lens rule. Triangulated
  from three regress-camera poses it sits on the centre line 0.22 block ahead of the car's middle, at the swirl's
  front tip. A same-session toggle sweep (`gamerun/va22_ab.py`, out/qa_va22b): it goes with `shell_wheels=0` or
  `car_coat=0` and stays with every other switch tried (driver_glass, glass_seat, band_interior, cab_interior,
  tyre_shadows, car_glass). The shipped `027_ice_cream_van.mesh` has 40 vertices at the soft-serve's collapsed tip
  whose stored normal is NaN (the finite-difference normal of a zero-radius ring). The coat pass over the wheel-split
  copy turned them into an unlit 0.06-block grey square. Fixes: `model_store.cpp` sets a non-finite normal to +y at
  load and logs `vertex normals were not numbers` (only 027 of every shipped mesh has any). `carkit.py` gives such a
  normal its neighbours' mean, so a rebuilt 027 differs from the shipped one in those 40 normals only (its 22
  textures are byte-identical, so the Remix prims keep their hashes). Verified out/qa_va22c: 027 side / front34 /
  high with the OLD mesh and the new DLL show no square.
- **035 Benson authored (`tools/vehicle_art2/car_035.py`; qav55 "shredded see-through shell, ghost canopy").** It is
  a 1950s Ponton / Adenauer sedan read from the sprite nose down (2.5 x 5.0 m, axles +19/-15 px, windscreen 25 px and
  back light 49 px from the nose). It has a long bonnet, a tall upright grille in a chrome frame with low side grilles
  and a star on a stalk, slab pontoon flanks, lamps on the wing fronts (placed on the sampled surface), and an upright
  four-door greenhouse with door glass, quarter lights and one-piece screens. Inside are benches, a dash and a wheel.
  Wraparound bumpers have over-riders, and the tyres are whitewalls. It is built on VEHICLE-ART-7's 050 surface
  recipe. The body sits between the bumpers so that bumper to bumper is the sprite's 5.0 m.
- **030 Land Roamer authored (`car_030.py`; qav51 "bonnet peppered with black holes").** A Land Rover Series I idiom
  in flat panels. It has a flat bonnet with the sprite's white star in a ring, flat-topped wings with square openings,
  and headlamps and side lamps in the wing fronts. A wire-mesh grille sits between them. The split windscreen is
  upright in a frame. A rounded canvas tilt in its own olive drab covers the cab and the tub, with side screens and
  the cabin behind them. The spare wheel is on the tail flap, the bumpers are black steel, and the tyres are off-road.
  The paint is the neutral 235 tinted to the sprite's olive (30 is not a livery model).
- **029 Dementia authored (`car_029.py`; qav51 "crumpled hull, faceted spikes on the nose").** An Isetta bubble car,
  egg-shaped in plan and side view, on the B-Type surface recipe with egg profiles. A wide wraparound windscreen sits
  in the nose door with a shut line round it. The roof dome is pale, as on the sprite. It has bubble side windows, a
  small back light, lamps on short pods and an engine-lid line. The rear track is narrow and the bumpers are thin.
  The occlusion is baked before the lamp pods go on: they left dark smudges on the nose.
- Driver seats are measured by `tools/vehicle_art/seat_anchor.py` (entries added). Without them the sprite's guess put
  030's driver at the windscreen, with his head through the bonnet (out/qa_va22b).
- Offline: `hole_scan.py` max back-face share 035 11.9 %, 030 2.3 %, 029 13.4 %. It is the floor pan and a chevron on
  the end caps, the same class as the shipped 050 (7.4 %), 070 (20 %) and 041 (20 %). There are no holes in the panels.
  Textures: 16 / 19 / 14 per body, 3.2 / 1.8 / 3.1 MB (the kit budget).
- Verified (frames opened): out/qa_va22c, the rebuilt bodies at all five poses. 035 is one closed sedan hull with
  clean grille, lamps, glass and chrome. 030 has flat clean panels, the grille, the lamps, the canvas, the spare and
  the driver behind the windscreen. 029 is a smooth egg with clean lamps and no spikes. Before: out/qa_va22a.
- Not verified: Remix (no prims for the new textures, so they draw from their base textures; 027's prims are
  unchanged); night; moving traffic; first person (FIX-COCKPIT-CAB-6's cab tables have no entry for the new
  interiors); 022 Armed Land Roamer (still its image-to-3D shell).
- **The paint-parity gate works again (out/va22pp3), and its result is 0 FAIL.** Two causes made VEHICLE-ART-21's gate
  (and out/va22pp1) say "no car found". (1) The probe wrote its forced model and paint under the first `[devtools]`
  text in the ini, and FIX-CAR-SHADING-1's comment `; [devtools] car_coat=0|1 ...` (package/gta2dx9.ini) came
  first, so nothing was forced. `paint_parity_probe.py` now anchors a section header at the start of a line.
  (2) At the 5-block `top` pose the gate spot showed the classic sprite. `POSES=top3` (3 blocks up) holds the
  street view; `tools/paint_parity.py` reads its frames and the probe takes the shadow check there too.
  Result at 18:30-equivalent noon sun, lids 0.99-1.00 (open sun), paints red / green / navy: hue 0-6 degrees on
  070, 041, 035, 030 and 029. Lightness is +8..+22 % (WARN), the same band as the control 050 (+14..+15 %).
  Navy is reported, not failed (the dark-paint floor). 030's canvas keeps its own olive under any paint.
  Classic vreg: spawn_classic PASS, 0 tiles changed (out/vreg_va22a).
- Still short of a shipping-AAA frame: the kit glass is dark, so no cabin reads through it by day. 030's panels are
  sharp-edged boxes with no bevel, door detail or rivets. 029's nose and tail end in a small flat cap. 035's roof
  edges carry the kit's AO lines.
- Model files: `035_benson*`, `030_land_roamer*`, `029_dementia*` (new sets replacing the shells) and
  `027_ice_cream_van.mesh` go to repo/assets/models with backups in `/mnt/gta2/gta2-linux/backup_va22/models`:
  NEEDS A RESTAGE.

## VEHICLE-ART-23 (11 Nov 2026): 011 Bus, 017 Fire Truck and 052 SWAT Van authored

Probes: QA-VISUAL pass 56's own repro (`gamerun/keys_qa_qav51.sh` = `to_level.sh` + `qav51.py`: wil 164.5,147.6, the
player's car parked and forced to each model, fixed regression-camera poses side / front34 / rear34 / eye / high,
18:30 clock paused, plain GL, `GTA2DX9_REGRESS_CAM=Z:\tmp\va2_cam.txt`). Before: the filer's run (stage 64c1eb2b).
After: a private stage of 3f813097 with HEAD f68928ea DLLs and the new model files. Forced models draw at tint 1
(identity.cpp), so these frames judge shape and finish. All three models are liveries, so their colours are
authored in.

- **011 Bus (`tools/vehicle_art2/car_011.py`; qav56 "ragged dark-blue awning, black quad holes in the roof, smeared
  sides").** The shell's upper body carried a sky-blue patch that hung over the windows as a torn skirt. Its roof had
  four unlit black quads and loose triangles, and the side texture was stretched. The kit body is a 1950s transit bus
  read from the sprite, nose down (3.13 x 9.92 m). It has well-rounded roof edges and rounded corners in plan.
  The cream body carries the default remap's brown livery: the roof's centre strip with three smoked escape hatches
  in pale frames and five round vents (the sprite's dark squares and dots), the letterboard band over the windows
  with amber markers, and a belt stripe with a chrome moulding. Eight glazed bays a side have pillars, with seat
  rows, a floor and a liner behind them. The front and centre passenger doors (glass leaves, a rail) are on -x, and
  the driver's seat, dash and wheel are on +x. The front is flat, with a split windscreen, a destination box,
  sealed-beam lamps, a small grille, mirrors on arms and a black wraparound bumper (the sprite's dark nose bar). The
  rear is flat, with a back light, engine louvres, tail lamps and the sprite's amber bar at the roof. The front
  tyres are single and the rear tyres twin. The end faces are planar panels cut to the section outline, in their
  own unbaked cream: the side's occlusion picture sampled across a face drew dark specks at the roof edge in the
  first build.
  Traffic draws the default remap for most buses (identity lines: paint 115,88,69, palettes 29-31, ~80 % of the
  bus records in out/), so the brown livery is the common case. The blue, green, red and teal remaps still show
  brown in 3D. 11 stays a livery (a strip-only paint half tinted by the remap would be the cure; see below).
- **017 Fire Truck (`car_017.py`; qav56 "black/white shards and a torn hose bed past the tail").** The shell's rear
  was unshaded black and white fins standing past the outline over a bed of interleaved sliver planes. The kit body
  is a 1950s pumper read from the sprite's stations (x4 row r -> z = (r - 248) x 0.0195 m). VEHICLE-ART-9's 058
  closed cab is built in its own frame and mapped onto the nose and cab rows (z scale 0.84). Its pale roof carries
  the sprite's two red beacons (the orange-red squares in the pale frame). Behind the cab is a pump section with
  chrome panels, gauges and inlets, a step, and the sprite's ringed disc as a hose reel (a drum of hose between
  chrome flanges, a dark hub). A lamp bar crosses the bed's front. Red lockers with shutter seams, chrome handles,
  amber markers and a top grab rail run down both sides, stepped round the rear wheel with a chrome fender lip. The
  hose bed between them holds folded canvas hose, and two aluminium ladders lie on three brackets inside the
  outline (the sprite's long white bars). At the back are a diamond-plate tailboard, tail lamps and grab rails.
  The 058 recipe's cab-back fan cap faced into the cab (mean normal +0.99 z) and is turned out here. The shipped
  058 has the same inverted cap (not changed: no defect filed; it sits behind the winch).
- **052 SWAT Van (`car_052.py`; qav56 "roof a blurry low-resolution smear with a floating white pillar").** The
  shell's roof was a 2-3 px-per-texel copy of the sprite with a stray white-and-red fin down the middle. The kit
  body is on VEHICLE-ART-10's 004 armoured-van recipe, read from the sprite: the box runs from the tail to sprite
  row 220 and the cab sits ahead. It has a raked windscreen, a rounded nose, a bar grille and a push bar. The cab
  roof carries the sprite's light bar (blue lenses rearward, red forward, a clear centre). The box has stiffener
  ribs, gun ports, a pale roof with the sprite's two navy stripes, two vent grilles between blue/red beacon pods at
  its rear corners, and rear doors with armoured windows. It is two-tone as the sprite: navy flanks under a pale
  grey-blue upper body. The 004 recipe's tail fan cap faced into the box (mean normal +0.9 z), so the van's back
  drew near-black; both box caps and the nose cap are now turned out. The dark rear seen in the rear34 frame is the
  dusk light on a back-facing panel: the bus's rear in the same pose measures the same (33 vs 32). The shipped 004
  has the same inverted tail cap (not changed).
- Driver seats measured (`seat_anchor.py` entries; written into the manifest for these three only). Without them
  the 017 hero sat in the cab door with his legs outside it (out/qa_va23c rear34 / eye).
- Offline: `hole_scan.py` max back-face share 011 0.25 %, 052 3.4 %, 017 7.8 %. 017's share is the front arch liners,
  the floor pan and 058's wing-shoulder seam line, the class every shipped kit body has (070 / 041 20 %). There are
  no panel or alpha holes. Files: 23 / 28 / 27 per body, 4.9 / 3.9 / 5.0 MB, replacing shells of 6.2 / 5.9 / 5.9 MB.
- Verified (frames opened): out/qa_va23a (bus first build: clean panels, a seat back through the rear corner),
  out/qa_va23b (bus final, 052 first build; `ssao` 1 / 0 in the same session: the same body, so FIX-CAR-SHADING-2's
  SSAO cloud is not in the bake), out/qa_va23c (017, 052 caps), and out/qa_va23d (all three final, at all five
  poses; sheets `sheet_011/017/052.png` there with the x4 sprite beside them). Every pose shows one closed body with
  smooth, uniformly shaded panels: the bus with a straight window band and a clean roof strip with hatches and
  vents, the fire truck with a closed tailboard and ladders inside the outline, the SWAT van with crisp roof
  stripes, pods and light bar.
- Colour (forced models, tint 1, 18:30 dusk, high pose, by hue class against the x4 sprite): 017 red L 19 vs the
  sprite's 20, hue 359 vs 9; 011 brown L 22 vs 38, hue 11 vs 24 (the dusk light and no livery gain); 052 navy L 17
  vs 41 in the first build, so the navy moved to the sprite's stripe blue (32,58,110; was 38,52,84): hue 227 vs
  the sprite's 215, L 19 (out/qa_va23e, the final 052 at all five poses). The paint-parity
  gate tests the tint path of painted bodies (a forced paint tints liveries too), so it does not apply to these
  three. Natural traffic with the lit-livery gain at noon is untested.
- Classic view: vreg on the private stage, `spawn_classic` PASS, 0 tiles changed (out/vreg_va23a). Its 3D shots
  (29 FAIL, 1 WARN) differ from the goldens by 18-30 tiles per shot. Those frames were not opened, so the cause is
  not established; ART-22's run against the same older goldens showed the same pattern (16 FAIL).
- Not verified: Remix (no prims for the new textures: they draw from their base textures); night; moving traffic;
  first person (FIX-COCKPIT-CAB-6's cab tables have no entry for the new interiors; the bus cab class is `bus`, the
  fire truck `truck`, the SWAT van `van`); the door split on the new bodies (the bus's door span from the sprite is
  mid-body, not at the authored doors).
- Still short of a shipping-AAA frame: the kit glass is dark, so the bus's seat rows hardly read through the windows
  by day (every kit body). The bus livery does not follow the remaps (blue / green / red / teal buses stay brown in
  3D). 017's lockers and 052's box are hard-edged panels with no rivets or roller-shutter relief. The SWAT van's
  nose is a 004-family snout, not a purpose-built armoured front.
- Model files: `011_bus*`, `017_fire_truck*`, `052_swat_van*` (new sets replacing the shells) in repo/assets/models,
  the shells' 53 files backed up in `/mnt/gta2/gta2-linux/backup_va23/models`: NEEDS A RESTAGE.

## VEHICLE-ART-24 (11 Nov 2026): 001 Wellard, 005 Beamer, 028 Dementia Limousine and 007 Box Truck authored

Probe: `gamerun/va24_show.py` (a copy of qav51.py whose A/B key may be a `section.key`, here `visuals.ssao` 1/0, and
which sets `force_car_paint` from `PAINT`): wil 164.5,147.6, the player's car parked and forced to the model, painted
with the default remap's sprite paint (identity record colours), fixed regression-camera poses side / front34 / rear34
/ eye / high, 13:00 clock paused, plain GL. Before: the 9744dfa1 stage (out/va24_b0, untinted). After: a private stage
of 9744dfa1 with the new model files. Moving traffic: `gamerun/va24_tcam.py`, two fixed cameras on the wil junction at
168.5,149.5 with every traffic car forced to the model and painted (out/va24_tc1; the old vr_traffic.py spot now lands
on a fenced pavement, out/va24_tr1 shows only railings).

- **001 Wellard (`tools/vehicle_art2/car_001.py`; audit "lettering ghost on the door, grille soft").** The shell was a
  1955 Thunderbird-like coupe with black drip marks on the door, the wrong era for the sprite. The kit body is the
  sprite's late-1930s coupe on 070's recipe: a long bonnet (the windscreen 38-40 px from the nose) with a chrome spine,
  pontoon front wings standing below the bonnet with the sprite's dark valleys between (a quick roll-in of the upper
  section over the wings, `leanq`), the waist sweeping up from the wing crowns into the door line, a raked chrome
  waterfall grille on the prow with a mascot, faired headlamps in the wing noses, a short cabin, a sloping back
  light, teardrop rear wings, chrome bumpers with over-riders, whitewalls.
  First build bug: the arch was capped 8 cm under the waist (0.76 over the wings), so the arch top dipped into the
  tyre; the renderer's wheel split (car_bodies.cpp BuildWheelSplit) took 90 wing triangles and steered them as a paint
  shard under the front wheel (out/va24_a1 front34). The wing's waist now stays 0.08 above the arch top
  (`wheel_split_check.py`-style scan: 0 paint triangles taken).
- **005 Beamer (`car_005.py`; audit "dark lumpy roof, missed door frame").** The shell drew near-black from every
  ground pose and white from above (out/va24_b0). The kit body is a mid-1950s roadster with its hardtop up: a full
  envelope body, a domed bonnet with a spine, round lamps in the wing tops' front corners (the sprite's discs 7-11 px
  from the nose), a wide low grille with a chrome centre bar, a raked screen and the sprite's dark grey-blue hardtop
  dome (`rubber_top`, not paint: the sprite's dome is the same grey in every remap), a belt moulding, two buckets,
  tunnel and parcel shelf.
- **028 Dementia Limousine (`car_028.py`; audit "flat facets on the bonnet", the shell a Hudson-like sedan where the
  sprite is a stretched bubble car).** ART-22's 029 section evaluated at a remapped station: the nose and the tail
  zones move rigidly with the wheels, only the cabin between the wheels (x3.28) and the tail behind the rear arch (x1.9)
  are drawn out, so the arches keep their shape. Front-opening door with the wraparound screen at the nose, the long
  pale roof dome, four glazed bays a side with pillars between (the sprite's flank marks), a driver's bench behind the
  door, a division, occasional seats and a rear bench, a full-width rear track. The kit's floor pan (a fixed 0.80 x
  half width rectangle) stood 0.3 m past the egg tail as a hard-edged dark slab (out/va24_a4 rear34): `underpan.py`
  gains `FOLLOW = {"028"}`, whose pan follows the body's floor outline and stops 15 cm short of the ends (out/va24_a6:
  it reads as shadow under the tail). The shipped 029 has the same slab (not rebuilt here).
- **007 Box Truck (`car_007.py`; audit "a cardboard box: faint grid, no panel detail, no rear door hardware").** A
  late-1930s box van on 001's cab recipe: the V-nosed bonnet with the sprite's chrome strip, pontoon wings with faired
  lamps, a rounded two-seat cab (screen at 23-25 px, cab back at 41 px), and a tall box with the sprite's raised roof
  ridge and three cross frames, nine flank ribs a side, a rub rail, amber roof-edge markers, two rear doors with
  hinges and lock bars, a step bumper and mudflaps, on a dark chassis with wide rear tyres. One paint all over (the
  remaps recolour the box and the cab alike). The shared floor pan measured a 0.16 m floor under the high chassis and
  hung as a slab between the axles: 007 joins `underpan.SKIP` with 063.
- **002 Aniston BD4: kept.** The shell reads as a clean DB4-style coupe at all five poses (out/va24_b0), as ART-19
  found when its kit body lost the A/B; no change.
- Seats measured (`seat_anchor.py` entries) and written to the four manifest entries.
- Offline: `hole_scan.py` max back-face share 001 7.8 %, 005 5.8 %, 028 6.0 % (11.6 % before the pan fix; the shipped
  029 measures 15 %), 007 3.2 %: sill undersides, arch liners and the pan's edge, no panel or alpha holes.
  Files: 17 / 18 / 15 / 19 textures, 3.3 / 3.4 / 3.6 / 3.1 MB (one 512 paint picture each), replacing shells of 6.1 MB
  each (24.4 MB for the four).
- Verified (frames opened): out/va24_a2 (001), out/va24_a3 (005), out/va24_a6 (028), out/va24_a7 (007; the car-scaled
  poses crop the truck), each at all five poses with `ssao` 1 and 0 in the same session (the same body: no SSAO cloud
  in the bakes), each sheet beside the x4 sprite; out/va24_tc1 (all four moving through the junction in traffic, one
  body and one colour each).
- Paint parity (`keys_paint_parity.sh`, POSES=top3, red / green / navy, the 050 control): out/va24_pp1 0 FAIL: 001 and
  005 hue 1-5 degrees, lightness +17..+22 % (WARN), the control 050 +15..+18 %; navy reported. out/va24_pp2 0 FAIL: 028 hue 1-5, +16..+18 %; 007 hue 0-3, +21..+23 % (its high box roof
  is the lit lid); 016 (round-8 shell) hue 1-3, +18..+21 %; control 050 +15..+18 %.
- Classic view: vreg on the private stage (out/va24), `spawn_classic` PASS, 0 tiles changed. Its 3D shots (29 FAIL,
  1 WARN, 18-43 tiles) differ from the goldens in the HUD tiles only (sheet_bank_street: the round minimap, the hearts
  and the new gauges against the goldens' square map and bars): the goldens predate the HUD work, not a car change.
- **Round-8 rows corrected.** 016 / 047 / 048 / 083 do ship their round-8 bodies: the manifest's
  `cars/models3d/0NN_*.glb` are byte-identical to `models3d_r8/chosen/` (not `old_shipped/`), and the game draws them
  (out/va24_r8: 016 a Mini, 047 and 048 late-1950s racers, 083 a 1950s GT). Their audit rows said "pre-round-8 body".
  New finding on the same frames (forced, untinted): their flanks draw near-black under a pale roof, the failure the
  005 shell had. Painted (force_car_paint 133,65,65, out/va24_r8p side / front34 / high): the flanks take the paint
  but 048's and 083's read near-black red under bright tops; 016's roof stays the sprite's tan (not the body paint);
  083's roof carries a white decal patch. All three break the one-paint rule; the next seat should author 016 / 083
  (and 047 / 048) as kit bodies rather than patch the masks.
- Not verified: Remix (no prims for the new textures: they draw from their base textures; no layer bundle); night;
  first person (no FIX-COCKPIT-CAB entries for the new interiors); the door split on the new bodies; the other remap
  colours of each model in natural traffic (the forced frames use the default remap's paint).
- Still short of a shipping-AAA frame: the kit glass is dark, so the cabins hardly read by day (every kit body). The
  box truck's box is flat panels with plain ribs (no rivets, no corner posts) and its cab is a little bulbous; 028's
  stretched tail carries AO streaks before the rear arch; 005's hardtop is one smooth shell with no seams.
- Model files: `001_wellard*`, `005_beamer*`, `028_dementia_limousine*`, `007_box_truck*` in repo/assets/models
  (shells backed up in `/mnt/gta2/gta2-linux/backup_va24/repo_models_0NN`). 001 and 005 are in the 01:37 stage
  (f649a0af); 028 and 007 NEED A RESTAGE.

## VEHICLE-ART-25 (11 Nov 2026): 016 Panto, 083 Furore GT, 047 / 048 Meteor authored

ART-24's painted A/B (out/va24_r8p, force_car_paint 133,65,65) showed the round-8 shells of these four breaking the
one-paint rule: 016's roof kept the sprite's tan, 083's roof carried a white patch, 047 / 048 / 083 drew near-black
flanks under bright tops. Each is now an authored kit body from the sprite's proportions with the paint mask over
every painted panel (same probes as ART-24: `gamerun/va24_show.py`, `va24_tcam.py`, `keys_paint_parity.sh`).

- **016 Panto (`tools/vehicle_art2/car_016.py`).** The sprite's 1960 Mini on 013's blunt-ended recipe: the roof over
  34 of the 56 px, an upright screen (rows 40-42), a short sloping bonnet, an upright back light over a short boot,
  door glass and rear quarter light split at the B pillar (the sprite's dark columns), small wheels at the corners,
  the Mini's external welded seams (drip rails, front/rear quarter flanges, sill seam), external hinges, round lamps in
  chrome bezels in the wing fronts, a moustache grille with horizontal bars, tall corner tail lamps, blade bumpers
  with over-riders, silver steel wheels. The flat ends are caps in their own unbaked paint turned to face out (the
  ART-23 lessons). Every remap recolours the whole sprite, so the roof is paint.
- **083 Furore GT (`car_083.py`).** A 275 GTB-idiom berlinetta: front and rear haunches (32 px) round a narrow cabin
  (the roof 16 of 28 px), a long bonnet, covered lamps at the wing tips, the oval mouth as the nose cap (egg-crate
  grille, chrome lip), a raked screen, a steep fastback, a cut-off Kamm tail with twin round lamps, three-slot vents,
  quarter bumpers, quad pipes, alloy wheels with spinner ears. The sprite's centre stripe (8 px) stays white under
  every remap, so it is its own untinted `stripe` region (boot, roof, bonnet, broken by the screens), not paint.
- **047 / 048 Meteor (`car_047.py`, `car_048.py` = 047 with `variant=1`).** A late-1950s sports-racing coupe from
  083's recipe re-proportioned to the sprite: pontoon wings over both axles, a narrow bubble cabin whose roof is the
  sprite's painted oval, a wraparound screen, a roll bar behind the cabin, a small back light, the long rear engine
  deck (the rear axle 13 px behind the centre), a dark grey lip across the tail (trim in every remap), twin bonnet
  intakes on 047; 048 has the sprite's open engine bay cut into the deck (cam covers, twelve stacks) and a rounded
  chrome blower through the bonnet.
- `underpan.FOLLOW` gains 083 / 047 / 048 (pinched nose and tail); seats measured (`seat_anchor.py` entries) and
  written to the manifest entries.
- Offline: hole scan max 016 6.6 %, 083 7.2 %, 047 7.6 %, 048 7.5 % (sill undersides, arch liners, the dark seal
  strips on the pillars; no panel holes). 20-23 textures, 3.4 MB each.
- Verified (frames opened, private stage): out/va25_a1 (016, default paint), out/va25_a2 (016 + 083 at the round-8
  A/B paint, ssao 1 and 0: the same bodies), out/va25_a3 (047 + 048, same paint), out/va25_tc1 (016 / 083 moving
  through the wil junction at their default paints). Paint parity out/va25_pp1 0 FAIL (016 / 083 hue 0-6 deg,
  lightness +18..+20 %, the kit band; 050 control in the run). Classic vreg (out/va25): spawn_classic PASS, 0 tiles;
  the 3D FAILs are HUD tiles against the older goldens.
- Not verified: Remix (no prims, no layer bundle), night, first person (no cockpit entries), the door split, other
  remaps in natural traffic.
- Still short of a shipping-AAA frame: the kit glass is dark (cabins hardly read by day); 016's side view reads
  estate-like at the sprite's long footprint; 083 / 047's oval mouths are large; 047 / 048 are plainer than the
  round-8 shells' sculpted pontoons; 048's engine is coarse up close.
- Model files: `016_panto*`, `083_furore_gt*` in repo/assets/models since 02:30 (staged by the 02:41 restage,
  240e3d2b); `047_meteor*`, `048_meteor*` see the batch order's READY lines. Shells backed up in
  `/mnt/gta2/gta2-linux/backup_va25/repo_models_0NN`.

## VEHICLE-ART-26 (11 Nov 2026): a swung door's inside for every body; qav89 was the old 007 shell

**qav89 (007 Box Truck rear "near-black with an oval hole").** No change: the filed stage carried the old image-to-3D
007 shell (its model file from 10 Nov, 3 meshes; the log said "3 nodes, 3 meshes"), not VEHICLE-ART-24's kit body
(19 meshes, staged since the 02:41 restage). The same repro on a HEAD stage shows two closed white rear doors with the
centre seam, hinges and lock bars, no dark face, nothing see-through (frames in the defect's READY line).

**The door's inside (qaf86, qaexp59, tri60's door item).** Since FIX-FP-EXIT-1 the first-person eye stands behind the
open driver's door for half a second. The door split (`dll/src/car_bodies.cpp` `BuildDoorSplit`) drew the door's inside
as its outer skin again, wound the other way with the skin's normals: a paper-thin slab in the shell's stretched paint
(023's brown sawtooth, 068's flat white board), dark whenever the outside was in shade (063's near-black: the inside
took the outside's light), its window part cut away by the glass path so the slab ended in a bare straight edge.

Now, in the split itself and so for every body (`DoorInside`, [devtools] `door_trim`, default 1):
- the inside sits a door's thickness (0.03 of the roof, ~7 cm) in from the skin, lit mostly from above (normals
  tilted inward and up: with the skin's normals or straight inward it went near-black whenever that side was in shade);
- under the belt (the foot of the door's own glass, else 0.60 of the roof) it is a door card: one generated texture
  (`doortrim|card`, `dll/src/model_store.cpp` `DoorCardTexture`: kick plate, warm-grey vinyl panel with an inset
  border and two pleats, a window crank, an armrest with a lit top and its shadow, a chrome pull at the latch end, a
  capping under the belt) mapped flat along the door from the hinge to the latch, so it reads the same on a shell
  and a kit body whatever their UV atlas;
- over the belt, on a body with its own door glass (kit bodies), the skin's own frame mirrored and set in by the
  thickness (the body paint round the window); on a shell (windows painted in its atlas, 023's awning stripes
  stretched over the door) the card's upper trim panel instead (a dark window tone read as a black slab on 068);
- the glass stays a thin pane (as before);
- every open edge of the door's outline (the cut edges, the window reveal) is closed by a strip from the skin to the
  inside in the card's seal grey, lit as if facing up (lit with the inside's normal they read as black bands from
  the first-person eye above the door's top): the door has an edge, not a torn sheet;
- glass and seal faces that face more forward than sideways stay on the body: 036 Schmidt's windscreen and its
  seal wrapped into the door's box and swung out as the warped crescent and shards qaf86 filed.
The outer skin is not touched, so the third-person door from outside is as before. The door is also drawn mirrored
on the far wall of the opening's cabin box (FIX-SEAT-ENTRY-3), which now shows the card too.

- Probes: `gamerun/va26_fpx.py` (`keys_qa_va26fpx.sh`: per forced model, first-person exit bursts at 15 fps, `door_trim`
  1 and 0 in one run), `gamerun/va26_door3.py` (`keys_qa_va26door3.sh`: the lens fixed beside the driver's door by
  `GTA2DX9_REGRESS_CAM`, Return, a burst while the door swings toward it). `force_car_door` cannot open a seated
  player's door (the boarding hold shuts it), and a scripted exit loses the scene car, so neither films a held door.
- Verified (frames opened, private HEAD stage, wil noon, forced models, `door_trim` 1 vs 0 in one run): first-person
  exits out/qa_va26_fpx7 (063: a grey card with the crank and a thick edge against the white mirrored skin; 068: grey
  against the flat white board; 023: a grey card against the big stretched orange slab; 036 / 069 / 001 filmed), third
  person beside the door out/qa_va26_door3 (068: the inside reads as a door card with crank, pleats, kick plate and the
  van's paint as its frame) and out/qa_va26_door4 (the pushed, rebased build). 0 FAULT. Classic vreg
  out/vreg_stage_VA26_1111_041553: spawn_classic PASS, 0 tiles; the 3D FAILs are HUD tiles against older goldens.
- Not verified: the outside face from in front of the open door (unchanged by construction: the outer triangles are
  not touched; not filmed), Remix (a generated texture, no PBR prim), night, other remaps, bodies beyond the six.
- Still short of a shipping-AAA frame: the first-person eye passes 10-20 cm from the door, so it fills a third of the
  view for ~0.3 s (the camera seat's path, tri60); 068's door top is a sawtooth with trim on and off (the split's cut
  through the shell's window region); 023 is an image-to-3D shell whose outer skin (stretched awning stripes) still
  crosses the view (needs its kit body); by noon sun the card is bright with faint detail; 069's door span sits
  behind its cab (VEHICLE-ART-20's arch clamp moves the front edge from 0.347 to 0.105): unchanged.

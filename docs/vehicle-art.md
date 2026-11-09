# Authored vehicles (carkit, VEHICLE-ART-1, 9 Nov 2026)

The owner's verdict on the 3D vehicles was "still really poor, needs drastic improvement".
The three vehicles a player sees most (docs/vehicle-art-review.md census of 9 335 drawn-car
samples in Downtown: 063 Truck Cab 2 213, 068 Van 1 110, 013 Minx 975, together 46 % of all
traffic) are no longer image-to-3D shells. Each is modelled part by part in Python
(`tools/vehicle_art/`), laid out on the game's sprite, and baked into clean textures.

## Why not another image-to-3D round

Eleven rounds of SDXL + TRELLIS (docs/car-3d-pipeline.md) give a single 5 000-face hull with
one soft baked texture: melted lamps, smeared grilles, lumpy bonnets, opaque glass with no
interior, no tread, torn shards under the sills, and a texture whose baked paint fights the
live tint. The 068 Van was not even that: a parametric box (`models_proc`) with the sprite's
roof lamps painted across its windscreen as two glowing eyes.

## How a car is built (`tools/vehicle_art/carkit.py`)

- Units: metres at 3.8 m per block (an adult is 0.46 block, `kPedHeight`), uniform so wheels
  stay round; the footprint is the sprite's `body_px` (the model's z length is what the
  renderer scales to the sprite). Nose +z, x across, wheels on y = 0.
- Panels: lofts of superellipse sections (`body_loft`: height, width at sill and roof
  (tumblehome), squareness, crown), side-profile extrusions for slab-sided bodies
  (`extrude_profile`: an outline with filleted corners and exact wheel-arch cut-outs, the
  long edges rounded, the flat sides Delaunay-filled so windows can be cut), revolved parts
  (wheels, lamps, tanks, stacks), tubes (rails, arms, wipers, mouldings), rounded boxes.
- Glass: the body has real holes where the windows are; a pane conformed to the body
  (ray-cast onto it) with a rubber or chrome rim covers each hole; an inward-facing liner
  (the body's own shape a few cm inside), seats, dash and steering wheel sit behind it.
- Wheels: a tyre with sidewall bulge and shoulder (tread grooves and lugs, whitewalls on the
  Minx), a dished rim with hub/hubcap, an inner disc; arch liners so an arch shows depth.
- Texturing is world-space: each draw group (paint / trim / glass) is unwrapped with xatlas,
  rasterised in UV space (nvdiffrast), and every texel gets its 3D position, normal and part;
  the part's shader paints it there (door shut lines, swage lines, hood louvres, tread, grille
  wires, lens flutes). Ambient occlusion is ray cast per texel against the whole car
  (open3d, 96 rays, the road counted). Chrome, glass and mirrors get a baked street
  reflection (pale sky above, a hard horizon, dark road below) because the plain renderer is
  fixed-function diffuse.
- Paint is **neutral light grey (235)** and the manifest's `paint_rgb` is 235,235,235. The
  renderer multiplies the paint texture by live sprite paint / `paint_rgb`, and today
  `model_store.cpp` reads `paint_rgb` from the import report, which never carries it, so
  every car model's reference is 235 (see the note on pf18 / pm17 in the defect queue). A
  neutral texture gives the sprite's exact colour with or without that lookup being fixed;
  the old textures, painted in a default brown, came out brown-shifted (silver -> brown,
  khaki -> brown).
- Output per car: one glTF mesh with six primitives: trim (every non-glowing part; its
  metal/roughness per texel in a `metallicRoughnessTexture` that `tools/remix_model_pbr.py`
  uses), the three lamp lenses (`headlamp_lens`, `taillamp_lens`, `marker_lamp`, each its own
  `emissiveFactor`), `paint` (the `_paint` texture the renderer tints) and `glass`. Textures
  1024 px (paint, trim), 256 px (glass). About 15 000 vertices per car (the importer's
  12 000 is a per-primitive split threshold; every primitive is under it).
- Remix: the GLBs live under `cars/models_art/`, which the Remix builder files in the
  `carproc` group: the per-texel metal/roughness texture is used, the glass material is
  glossy, the `_paint` texture gets the clear coat, the lamp lenses emit.

Build one car (gen3d venv, any GPU):

    cd tools/vehicle_art
    CUDA_VISIBLE_DEVICES=$GTA2_GPU ~/gta2-linux/gen3d/venv/bin/python m063_truck_cab.py --preview /tmp/063.png
    # -> ~/gta2-linux/assets-src/cars/models_art/063_truck_cab.glb (+ .json, atlas PNGs)
    # then import (assets-src/manifest.json entry: glb cars/models_art/..., paint_rgb [235,235,235],
    # texture_max 1024, no paint_split / paint_materials):
    cd ~/gta2-linux/assets-src && python3 <repo>/tools/import_assets.py manifest.json <models dir> --only 063_truck_cab

`--preview` renders the car offline from the views a player sees (eye height, chase, close,
side, rear, far) and the top view beside the sprite. `before_after.py` builds a before/after
sheet from the review probes (gamerun/vr_traffic.py, vr_seat.py).

## The three models

| Model | Reads as | Sprite features kept |
|---|---|---|
| 063 Truck Cab | 1950s short-nose conventional tractor: chrome grille with bars and emblem, wrap bumper, swept front fenders with pod headlamps, cab with split windscreen, sun visor, west-coast mirrors, chrome tanks and stacks with perforated shields, fifth wheel, rear duals with mudflaps | grille and bumper rows at the nose, short hood with a centre strip, the cab roof and its two round roof lamps, the dark chassis with the fifth wheel's plate behind |
| 068 Van | 1960s forward-control panel van: two-pane windscreen, round lamps in chrome rings, slotted grille band, wrap bumpers, cab and cargo doors on both sides, twin rear doors with windows, ribbed roof, drip rails, painted steel wheels with dome hubcaps | the long ribbed roof, windscreen at the nose, doors on both flanks, the khaki-olive default paint |
| 013 Minx | early-1960s compact two-door: black vinyl roof over dark glass, chrome window frames, hood ridge, round headlamps, grille between them, small tail fins with round lamps, chrome spear moulding, whitewalls and hubcaps | the dark greenhouse from the windscreen row to the rear window row, the hood ridge, the lit lamps at the nose, the corner points of the fins |

## Verified (frames opened and looked at)

- Private stage `stage_vart` (the live stage of 16:04, da43f25 DLL, plus the three models).
- `tools/identity_parity.py` (run `vart_idp2`): the 068 Van at the spawn, classic sprite
  99,97,81 against the 3D model at the classic camera 94,94,79 (delta-E 1.7; it was 16.8)
  and from the chase camera 36,36,33 (delta-E 27.8, pass; it was 33.9, dark brown).
- Natural Downtown traffic from the review kerb (`gamerun/vart_watch.py`, runs
  `vart_watch_after` / `vart_watch_before`): trucks in their sprites' own greys, mauves and
  browns instead of all green.
- Forced-model probes (`vr_traffic.py`, `vr_seat.py`, `vr_walk.py`): far, close, eye height,
  walk-round, seat; sheets `out/vart_sheets/ba_NNN.png`.
- Classic: `tools/vreg/vreg.sh stage stage_vart` (see the commit message for the result).

## The "pale dome" regression (FIX-CABIN-DOME, 9 Nov 2026)

The operator's REGRESSION-vehicle-cabin-pale-opaque-dome (owner demo, run dh_owner6) was not the car
glass (33c34be): with `[devtools] car_glass=0` the domes stay (run cd_vg1). Two causes, both on the
authored bodies:
- **Small domes on the roof (t=60):** 063's two roof lamps were mirror-chrome cans whose backs face the
  chase camera; with the baked sky reflection they read as pale sky-blue balls. Now black steel
  housings with a thin chrome bezel at the lens (m063_truck_cab.py), the rest of the model unchanged.
- **Large dome filling the seat view (t=110):** the driver's-seat bonnet (car_bodies.cpp,
  BonnetSurfaceFor) takes a texel's paint share as 1 - the base texture's alpha. The carkit bodies
  import an opaque base twin of the paint texture (`NNN_2.tga` beside `NNN_2_paint.tga`), so the share
  came out 0 and the bonnet drew untinted in the neutral 235 paint, lit pale blue by the sky. A hit on a
  `_paint` texture now takes the share from that texture's own alpha (identical for the split
  image-to-3D bodies, where it is exactly 1 - the base's alpha). Affects 063, 013 and 068 from the seat.

## What still falls short of a shipping AAA frame

- Lighting, not geometry: the street views light car bodies with one sun and an ambient of
  0.35 (`car_bodies.cpp`), so a face away from the sun is 35 % of its colour; a dark-grey
  truck seen from behind reads near black (pm3 / pf18 family). A sky fill light or the
  Remix path tracer is what fixes that; the models carry the AO for it.
- No real reflections in the plain renderer: chrome and glass carry a baked, view-
  independent street reflection; paint has none (the renderer's specular lobe only).
- Glass is opaque in the plain renderer; under Remix it is a glossy material, not a
  translucent one, so the modelled interiors are only seen where a window hole is open
  (none today). The panes' holes are there for when glass becomes translucent.
- Panel gaps and louvres are texture, not geometry; there are no normal maps of our own
  (the Remix builder derives one from the albedo).
- `force_car_model` / `force_own_car_model` draw a forced model as a livery (tint 1), so in
  those developer probes a neutral-paint model is white; natural traffic is the evidence for
  colour.
- The 068 footprint IoU in the parity check's car phase is 0.26 (limit 0.35; the old model
  0.25-0.31): the frame shows the model on the sprite's footprint; the tall van's
  perspective at the classic camera is the likely cause, not checked further.

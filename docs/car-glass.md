# Car glass, cabin, smoothed normals and grounded contact shadows (VEHICLE-GLASS, 9 Nov 2026)

VEHICLE_PRIORITY.md priorities 2 and 5: the fleet-wide realism faults VEHICLE-REVIEW's audit
(docs/vehicle-art-review.md) found on the generated car bodies. All of it is renderer-side, so it
applies to every model, including the ones other agents regenerate, with no change to the model files.
Defects: vr-car-glass-opaque-baked-no-interior-through-windows,
vr-generated-bodies-hard-facets-crumpled-bonnets-close-range, and the car half of
pm-no-contact-shadows-cars-peds-props-float (fixed by aafde55, but the car patch never showed).

## 1. Glass and cabin (dll/src/car_glass.cpp)

The image-to-3D bodies are sealed hulls with the windows painted on: the bake keeps whatever the
concept image showed through the glass as opaque albedo. Per model, once, on a worker thread:

1. **Mask.** The body texture is rasterised in UV space at 256x256 with each texel's point on the
   body and its face normal. A texel is glass when it is in the *glasshouse* and is not *paint*:
   - glasshouse: between 0.60 and 0.90 of the roof height (the roof = the highest point over the
     middle 60 % of the width, so exhaust stacks and mirrors do not count), not a roof or bonnet
     top (normal y <= 0.80), and either a side face (|nx| > 0.4) under the roof's length (the slices
     reaching 0.86 of the roof), or a windscreen (facing forward, ahead of the roof, above 0.64), or
     a rear screen (facing back, behind the roof, leaning back, darker than the paint);
   - paint: within 0.10 (RGB) of one of the body's up to three dominant colours, sampled on the
     lower flanks (0.35-0.55 of the roof, side-facing, the paint mask's texels when there are
     enough), or the same hue (22 degrees) as a saturated paint at any brightness (the bake keeps
     the concept's highlights), or any saturated bright texel (a livery band is never glass);
   - then an opening (speckle off), components under 30 texels dropped, a closing of 2 (fills the
     glass), and the paint test again (a pillar the closing bridged stays metal);
   - growth: up to 6 texels into anything in the glasshouse that is not strictly bodywork (within
     0.12 of a paint colour, a saturated bright livery, a light or upright tailgate): the bakes paint
     the lower glass with the cabin's reflection, often in the paint's hue;
   - components that read as paint as a whole are dropped: mean value over 0.62 with saturation over
     0.12 (the cream upper body of a two-tone van, cargo slats, the ice-cream van's cone), or over 0.85.
     Real glass in the bakes is darker, or a near-neutral pale grey (Maurice: saturation 0.03-0.05);
   - an upright rear screen counts only when clearly darker than the paint (under 0.55 of its value).
   A model with fewer than 200 glass texels, or no room for a cabin under its roof, keeps its
   painted windows. VEHICLE-ART-1/2's authored bodies with their own glass (`_glass`/`_interior`
   textures) are left alone; authored bodies without such names (the new 013 Minx) are lifted too.
   The mask texture is the binary mask box-blurred 3x3, so the alpha test cuts a smooth contour.
2. **Cut.** While a car's hull is drawn (`CarGlassBeginCut`), `ModelDrawBlend` binds the mask on
   the first free texture stage and multiplies the alpha with it; the hull's alpha test drops the
   glass texels. Body, door split, dented copy, wheel split and turret all share the texture and UVs,
   so all of them are cut.
3. **Cabin.** A shell just inside the side glass: floor at 0.30 of the roof, headliner at the side
   glass's top (never above the hull's lowest roof point over the cabin), from just behind the side
   windows to just ahead of them; faces wound to show from inside, so only the far walls, the floor
   and the headliner are seen, and the seated driver drawn later (FIX-SEATED) sits in front of them.
   Seat backs with headrests, a rear bench on a long cabin, and a dash. Unlit vertex colours (dark
   trim, a lighter headliner for depth), dimmed at night.
4. **Glass.** After the figures (live_geometry.cpp, after DrawPedFigures), each queued hull's glass
   triangles (any of seven UV points on glass, cached per mesh) are drawn once more: alpha
   `car_glass_alpha` over what is behind, depth tested and not written; colour = a cube map of this
   frame's sky (zenith, horizon, a dark street below; rebuilt when the sky colours change) by the
   eye-space reflection vector turned to the world, at 0x50 strength, plus a dark tint lit by the
   scene and a hard specular (power 48) for the sun.

FIX-SEATED's clip-plane band (40 % of the whole glasshouse, 4393335) is skipped for a car that has
glass; it still covers the models whose glass was not found, and a car with a seated driver whose
model's rear screen was not found (fewer than 40 rear texels: the truck cab 063), so the driver still
shows from the chase camera behind it.

Cost (plain renderer, L4, Downtown traffic, run vg_ab8): the glass pass 0.07-0.17 ms CPU a frame
(0.34 worst) for 7-28 glass draws; each mesh's glass triangles are compacted into their own small
vertex list (a UP draw copies its whole vertex range) and the pass saves and restores only the states
it touches (a full state block a frame cost ~0.3 ms). The mask build runs on a worker thread (~20 ms
per model); the car is drawn as before until it is ready. The first-person own car (the QB-31
cockpit), wrecks and open tops are untouched.

Settings: `[renderer] car_glass=1`, `car_glass_alpha=52`, `car_glass_range=40` (blocks);
`[devtools] car_glass=0|1` re-read once a second for same-spot before/after frames;
`GTA2DX9_GLASS_DUMP=1` writes each mask as `/out/glass_<texture>.pgm`.
Log lines: `car glass: <model>: N glass texels ... cabin z ..`, `car glass: X ms avg ...` every 300 frames.

## 2. Smoothed normals (model_store.cpp, SmoothCarNormals)

80 % of a generated body's vertices are UV-seam copies (xatlas charts), and each copy carried its own
chart's normal: on 050 B-Type the copies of one point are 33 degrees apart at the median, 65 at the
90th percentile. Under the per-vertex lighting every chart edge was a crease, which is the "mosaic of
flat facets" on the bonnets. At load, for every car model (`NNN_*`): angle-weighted face normals summed
over every face at the same point whose normal is within `car_crease_deg` (60) of the corner's own face.
`[renderer] car_smooth_normals=1`. Geometry is unchanged (no subdivision), so the silhouette's polygon
edges and the bakes' painted highlights remain.

## 3. Car contact shadows (live_geometry.cpp, car_bodies.cpp)

The car patch of aafde55 was placed at the game's sprite plane, which is the car's own height, inside
the body, so it never showed (VEHICLE-REVIEW: "no car has a contact shadow"). It is now placed at the
drawn body's lowest point (`CarBodiesGround`, the model's bounds through the fit, per frame).

## Evidence and what still falls short

Runner: `tools/vehicle_review/vg_walk.py` (copy in gamerun/; VEHICLE-REVIEW's walk-around with every
frame taken twice from one spot, `[devtools] car_glass=0` then `=1`, suffix `_off`/`_on`, plus a chase
frame from the jacked car). Runs (local, not in git): out/vg_ab7 (9 models: 000 004 011 012 013 040 050
063 067), out/vg_ab8 (final build: 004 013 040), out/vg_ab1 (the HEAD baseline, no smoothing, unmoved
shadow), sheets in out/vg_evidence/. Classic: vreg stage out/vreg_stage_vglassF_1109_174421,
spawn_classic PASS 0 tiles; its pixel difference to the goldens (810-860 of 921600 px) is under the
goldens' own spread (604-7212 px, the animated street). Its three FAILs (spawn_third, bank_chase,
raised_w03_high) are camera and building changes from other commits since the golden (48a9b58), with
no car in the changed tiles.
`tools/vehicle_review/vg_traffic.py` (the traffic runner in A/B) is included but its walk is blocked by
the Downtown fence since the street props became solid (FIX-COLLISION); no traffic frames were taken.
Not done / short of a shipping bar:
- Remix: nothing here applies under Remix (the cut is a second texture stage Remix ignores; the
  glass pass is not drawn). Remix glass needs separate glass geometry with its own texture hash and
  a translucent material in the gta2hd layer.
- The mask is a heuristic on painted pixels: coverage is partial on some panes (the bus's pale rear
  window, the cop car's windscreen keeps a reddish strip of bake), dark cars barely change (030 Land
  Roamer: glass and paint are the same dark green), 063's rear window is not found, and the rear deck of
  a mid-engine car (019) can still be taken for glass. 067 TV van's two-tone upper body is dropped as a
  whole now, which also drops some of its real side glass.
- The glass is one constant tint with a sky reflection and no Fresnel term (fixed function); at grazing
  angles it does not brighten the way real glass does.
- Seated drivers in traffic were not filmed (runner blocked); the chase frames show the player's car.
- The cabin is a box with block seats, not a modelled interior.
- Facets: the normals are smooth, but the low polygon count still shows on silhouettes and the bake's
  painted highlights do not move with the light.

## 4. VEHICLE-ART-5 (9 Nov 2026): a dark cabin behind the driver band, patches on the road, tyre contacts

- **Driver band interior** (feel20, `car_bodies.cpp` DrawBandInterior / MeasureBandBox). The FIX-SEATED band above
  is the hull at 40 % with no depth written. Behind it there was nothing, so the street showed through the
  roof and upper body, and the props and walls drawn after the cars painted over it (parking meters on the
  roof, a hydrant through the body). Before the band is drawn, a box inside the cabin is drawn opaque and dark
  (0x1A1C21, unlit) with depth written. Only its far walls and floor are drawn (CULL_CW): the near ones would
  hide the driver. The box is measured from the model per fit and cached:
  - **Half width:** the lower quartile, over ten stations along the cabin, of the widest vertex at the band's
    heights, times 0.9. A stack or a mirror at one station does not widen it.
  - **Length:** the hull's extent near the roof, so the box stays behind raked screens.
  - **Height:** from the belt to 0.9 of the cabin's own roof (the median highest point within the box's inner
    width).

  The band's clip planes now use that cabin roof too. The 063 cab's model height includes its stacks, which
  put 0.9 of it above the roof, so the whole roof was drawn see-through. `[devtools] band_interior=0` gives the
  old drawing for A/B. Log: `band box <model>: half width .., z .., cabin roof .. of ..`.
  VEHICLE-ART-6: the box is no longer one flat tone. The walls are lighter towards the headlining and darker at
  the belt, the floor is darkest, and the back wall (the seat backs) is a touch warmer.
- **Contact patch on the road surface** (`live_geometry.cpp` DrawContactShadows). The car patch was at the body's
  lowest point. A car with a wheel up a kerb has that point under the pavement, so the depth test buried
  the patch. The patch now lies on the map's surface: the highest of the centre and the four corners from
  `GroundSampler::SurfaceAt`, within 0.45 block of the body's foot.
- **Tyre contacts.** Each cut wheel (`CarBodiesWheelContacts`: where the tyre meets the road, from the wheel
  split's centres and radii) gets its own small patch, 1.05 r along by 0.75 r across, on that spot's surface.
  It multiplies with the car's soft patch, so the tyres sit on a darker core. Settings and logs:
  - `[renderer] tyre_shadows=1` turns it on.
  - `[devtools] tyre_shadows=0` turns off the tyre patches and the surface placement, for A/B.
  - The log line is `contact shadows: N cars (M tyres), ...`.

## 5. VEHICLE-GLASS-2 (10 Nov 2026): glass under Remix, the mask's class misses, Fresnel

### 5.1 Remix: panes as their own geometry with one shared glass texture

Remix ignores the extra texture stage that cuts the hull in the plain renderer and keys its materials
on the stage-0 texture's hash, so until now every generated car kept its opaque baked glass under Remix.
Under Remix (`RemixApiAvailable()`, `GTA2DX9_GLASS_REMIX=0` restores the old "nothing under Remix"):

- **Cut by geometry.** `CarGlassCutIndexBuffer` (one hook in `model_store.cpp`, the glass call only)
  gives the hull draw an index buffer over the mesh's own vertices less its pane triangles. A triangle is
  a pane when 8 of 15 points spread over its UV footprint lie on the *pane mask* (the glass mask eroded
  by one texel, so a pillar edge stays metal and the painted rim reads as the seal).
- **Panes.** The same triangles are drawn in `CarGlassFlush` from managed buffers with ONE fleet-wide
  texture of fixed content (256x256 A8R8G8B8, `FixedTexture`), so ONE fixed Remix hash:
  **`0x00E7B4E949140568`** (the log prints it: `car glass: pane texture 0x... (Remix hash ...)`).
  Drawn unlit, white, opaque draw state, depth written: Remix multiplies a replacement's albedo by the
  legacy vertex/material colour, and the plain pass's lit dark tint made the panes near black.
- **Cabin.** The cabin shell is drawn with two shared textures of its own, trim **`0x52573041E54EEEB7`**
  and headliner **`0x92AE80C504938232`**, without the shell's side and end walls (the path tracer sees
  faces from both sides; the walls would stand just inside the glass). Seats, dash, floor and headliner
  stay, so a side window shows the seats, the far window and the street beyond.
- **Layer prims** (tested from a private copy of the layer, handed to FIX-REMIX-MATERIALS-5; see the
  NOTE beside the vr-car-glass work order): the pane `AperturePBR_Translucent`, thin-walled
  (thickness 0.5), IOR 1.5, transmittance (0.86, 0.90, 0.90); trim and headliner `AperturePBR_Opacity`
  roughness 0.85 / 0.9 over their legacy albedo.
- **Proof the hash keys:** a probe layer with the pane prim as a flat magenta `diffuse_texture` painted
  every pane magenta on 000, 013 and 067 in one session (run vg2_rxp7). A prim carrying only
  `diffuse_color_constant` does NOT show (the legacy albedo stays): probes need a texture.
  The hash is a constant of the code, the same in every session and for every car.

### 5.2 The mask's class misses (measured offline)

`tools/car_glass_mask.py <models> <stems> [--old] [--sheet s.png] [--dump dir]` is the offline twin of
`Build` (the same masks to the texel: run vg2_pl1's `GTA2DX9_GLASS_DUMP` dumps against it, 0 texels
apart on 000/011/012/067/013, 2 of 1442 on 013_2). `--old` gives the 33c34be heuristic;
`GLASS_DEBUG=1` colours the sheet: glass cyan, strict bodywork red, paint-like orange, band yellow.
Class rules added (no per-model data):

| Miss | Cause | Rule |
|---|---|---|
| 067 two-tone band dropped with its cab windows | the cream band and the window are one component, dropped as paint | a paint-reading component loses only its bright texels and their shade (same chromaticity); the rest is closed and kept if it reads as glass |
| two-tone uppers in general | the paint colours are sampled on the lower flanks only | light near-neutral roof colours (val > 0.45, sat < 0.25) join the paint colours |
| 030 dark paint, glass barely found | 0.10 of RGB is most of a dark green's range; `val < 0.18` excluded all dark glass | the paint tolerance scales with the paint's brightness (floor 0.6); only tyre-black (< 0.08) excluded |
| 012 windscreen bake strip | saturated texels count as livery everywhere | on a screen a saturated texel may be grown into from the glass around it but never seeds glass |
| 011 pale rear | a rear screen as light as the paint was a tailgate | not when it is cooler (bluer) than a warm paint |

Texel counts old -> new: 011 4039->4091, 012 795->1047, 030 260->349, 067 1463->1993 (both cab side
windows), 019 289->563, 007 360->1088, 003 280->1714, 000 2968->2994. Tried and dropped: on a dark body a
light rear screen as glass (012's white-baked rear was found only in part: a ragged dark hole in the
chase view where FIX-SEATED's band looked better, runs vg2_pl0 vs vg2_pl1). Still short: 003 and 007
(dark utility bodies) take part of their dark rear doors around the small door windows as glass; 030's
glass is still mostly missed (its bake paints the glass the paint's own dark green); 012's rear screen
and the blue sky reflections that match its blue paint's hue; 063 and 004 are authored bodies now
(their own `_glass`), outside the mask.

### 5.3 Fresnel (plain renderer): tried, NOT working, off

Written: stage 0 looks up a 256x4 ramp by the camera-space normal's depth component (texgen
`CAMERASPACENORMAL`, u = 0.5 n.z wrapped, so 2 min(u, 1-u) is the cosine to a distant viewer): rgb = the
sky reflection's strength, 0.20 facing to 0.95 grazing ((1-cos)^4), alpha = the opacity, `car_glass_alpha`
facing to 0.94 grazing ((1-cos)^3); stage 1 multiplies the sky cube by it, stage 2 adds the lit tint and
cuts by the mask. GPU texgen only, no per-vertex work. In the frames it does not vary with the angle:
same-spot A/B (runs vg2_pl1 with the translation row u = 0.5 + 0.5 n.z, vg2_pl3 with the wrapped
form) made every pane darker by the same amount (the facing value), with no brightening on the grazing
side windows (013/012/011 front34, 013 side, 012 eye: 4.6k-20k pixels darker, under 1k brighter, the
brighter ones the moving driver). So the generated coordinate does not reach the ramp as written on
wined3d. Left in the code as `[devtools] car_glass=3` (experimental); `car_glass=1` draws the constant
look of section 1. Next step for a successor: a per-vertex factor (a diffuse-carrying copy of the pane
vertices per frame, n.v on the CPU, ~1-6k vertices) or a small vertex shader.

## 6. VEHICLE-GLASS-3 (10 Nov 2026): the 030 miss, a closed-roof test, the Remix cut along the outline

### 6.1 Dark saturated paints: glass off the paint's hue (mask class rule)

030 Land Roamer's windows are a grey-green within the RGB tolerance of its dark olive paint (paint hue 100,
saturation 0.46; window hue 136-143, saturation 0.30, the same value: 0.025 of RGB apart, the tolerance at that
brightness is 0.072). Rule (Build and `tools/car_glass_mask.py`, `--nooff` for the old one): on a body whose
paints are **all dark (value < 0.40) and saturated (>= 0.30)**, a texel more than 25 degrees off every paint's hue,
or under 0.4 of its saturation, and not in shade (at least 0.6 of the nearest paint's value) is neither near-paint
nor paint-like. The first form (any saturated paint) took 002's cream highlights for glass and the merged
component was dropped as paint (2213 -> 1870 texels): restricted to dark paints.

Fleet re-measure (offline twin, all 83 meshes; the DLL's counts in run qa_vg3_pl1 match it to the texel for 000,
002, 046, 062): 10 bodies change, none lose texels: 030 349 -> 2108 (both front door windows and most of the
windscreen; 2444 with 6.4), 062 1164 -> 1673 (its +x side window), 046 757 -> 1131, 041 312 -> 413, 022 1145 -> 1238, 007, 031,
005, 012 (+8), 077 (+1). Bodies with at least 200 glass texels: 53 before and after (the class rule adds panes to
found bodies; the remaining fleet gaps are bodies with no glass found at all, below).

### 6.2 Game open-tops with a hard-top mesh (030)

The glass pass skipped every model in `CabOpenTop` (22, 30, 31, 39, 44, 45, 53: open in the game's sprites), so
030 never drew glass in any run before (no `car glass: 030` line in VEHICLE-GLASS-2's runs either: the 5.2 "030
mostly missed" was the offline sheet). The generated 030 is a hard-top with windows. Build now records a
**closed roof**: the roof span (slices at 0.86 of the roof height) is over a fifth of the length and the middle
strip of the width stays at 0.80 of the roof over three quarters of it (030: span 0.62, 0.83; the real open meshes
fail: 022 0.60/0.34 (gun mount), 031 0.10, 044 0.38/0.39, 045 0.08). `car_bodies.cpp` lets a game open-top take
glass when `CarGlassClosedRoof`. A cabin that would not fit is now trimmed first: when the "never above the hull"
cap would put the headliner under the belt, up to a quarter of the cabin's length is cut from each end where the
roof line is lower than the headliner (030's windscreen dips to 0.67 of the roof in the middle: "no room for a
cabin, headliner 0.294, belt 0.272" before, cabin z -0.316..0.031, headliner 0.398 after). Every other body keeps
its cabin as it was (000's numbers identical in runs qa_vg3_pl1 and pl3).

### 6.3 Remix: the hull and the panes split along the window's outline

`car_glass_split.h` (no D3D; `SplitGlass`) replaces the whole-triangle vote of 5.1 under Remix. A triangle is
classified by the box-blurred pane mask sampled bilinearly on about one point per texel of its UV footprint: all
under 0.5 hull, all over pane; a straddling triangle is subdivided (4-way, each child re-classified, so only the
boundary refines) down to 1.5 texels and each leaf is clipped along the field's linear 0.5 iso-line, so the hull
and the pane get complementary pieces whose shared edge is the contour the plain renderer's alpha test cuts.
The hull then has vertices of its own: the hook `CarGlassCutIndexBuffer` (model_store.cpp, the glass lines only)
also hands back a vertex buffer and its count. 000: 3152 vertices / 3584 triangles -> hull 9107 triangles
(17807 vertices) + pane 5975, 164 triangles on the outline; 011 bus 415 on the outline -> hull 16012 + pane 9119.
Built once per mesh on first draw (milliseconds), managed buffers like the hulls.
Offline before/after (native test of the same header on the model files, rendered): the old vote's sawtooth
of whole pane triangles and the large baked triangles left on 000 become the window's outline.
Switches: `GTA2DX9_GLASS_SPLIT=0` (the vote for the session), `[devtools] car_glass=4` (glass on with the
vote, for same-session A/B under Remix).
In the game (run vg3_rx3, Remix, noon, private layer = HEAD gta2hd + the three glass prims of 5.1, same session,
same pose, `car_glass=4` then `1`): 000's side windows with the vote show large triangular baked slabs cutting
across both panes; with the split the panes follow the window outline. What is left there is the mask's own dark
blobs (6.4).

### 6.4 Dark cabin bake between two windows (mask class rule)

000's bake paints the cabin seen through the side panes dark brown in the paint's hue (value 0.26 under a 0.57
paint): paint-like by hue, not strict bodywork, and wider than the 6-texel growth, so blobs and drips stayed in
the panes (hull-coloured slabs under Remix). A side texel darker than 0.45 of the paint's value, not strictly
bodywork, becomes glass when real windows (components of 120+ texels) lie on the same side at its height both
ahead of it and behind it within a quarter of the length (grown from the glass, up to 16 texels). A first form
without the "both sides" test took 003's shaded flank and rear doors (+55 %): dropped.

Fleet after 6.1 + 6.4 against VEHICLE-GLASS-2's masks (offline twin, 83 meshes): 39 bodies change, the only
losses 1-3 texels (032, 033, 035, 044); 030 349 -> 2444, 046 757 -> 1185, 062 1164 -> 1680, 041 312 -> 413,
016 1725 -> 2224 (its rear side window), 000 2994 -> 3221, 003 +8 %. The DLL's masks match the twin within 1-6
texels (run qa_vg3_pl4 dumps: 000, 003, 016, 030), 0 FAULT.

Still short: 012's rear screen (white bake on a dark body, not attempted again); 003/007's dark rear doors
still partly glass; 030's pale rear-door pane (light on a dark body, the rule GLASS-2 dropped for 012); the
films of 5.x's list (first-person seat, a traffic driver behind the side glass, the 013/068 rim) not made in
this round; Fresnel still off.

## 7. FIX-DRIVER-GEOM (10 Nov 2026): the driver sits on the cabin's own front seat (pfl74)

A generated body (an image-to-3D shell with no manifest `driver_seat`, 57 of the car models) used to seat its
driver where the game's sprite suggests: the CARI window rows (`SeatZ`: the rear window's row plus 0.38 of a door).
On the 001 Wellard the sprite's rows put the hip at z -0.295, on the rear deck behind the hardtop: in third person
his head and shoulders stood outside the glass on the trunk lid while the cabin seen through the windows was empty
(pfl74).

Now the cabin this module builds behind the glass names the seat (`CarGlassDriverSeat`): the hip 0.06 ahead of the
drawn front seat back's face, on that seat's middle line, the cushion at its foot, and the head kept under the hull's
own roof over the seat (its middle strip, less 6 % of the height; not the cabin's headliner, which follows the
glass's top and sank him under the 001's high waist). A long cabin (a van's or a bus's side glass to the tail) keeps
the hip at most 0.30 behind the dash. car_bodies passes it to boarding exactly as a manifest seat; an authored
body's manifest seat still wins. The log line `car bodies: driver's seat of <model> (glass cabin): ...` shows it
next to the sprite's.

- `[devtools] glass_seat` (1; 0 = the sprite's seat, re-read live) for same-spot A/B.
- Verified (runs dg74a/b/d, `gamerun/keys_dg74.sh`: warp to the parked car, F9, fixed regression-camera poses with
  glass_seat 1/0, a third-person drive): 001 hip z -0.295 -> +0.026 (headliner 0.322); nothing of him outside the
  hardtop from above (dg_high_001), his head inside the cabin behind the windscreen from the rear three-quarter and
  the side.
- Still short: from straight behind (the chase view) the 001's rear screen shows no head (the bake paints most of
  the rear screen opaque and the cabin's seat back and headrest stand in front of him); from the side only the top
  of his head clears the 001's thin side-glass band (the hero, 0.46 block tall, is large against cars modelled at
  5 m a block). 005 Beamer (301 glass texels) shows no driver with either seat. The other 55 generated bodies were
  not swept side-on.

## 8. FIX-REMIX-GLASS (10 Nov 2026): the fleet glass prims were never in the shipped layer

Defect prx6 (Remix, bil night, first person: the black muscle car's side window "flat white chalk blobs and a torn
cut-out cabin"), and the same class in prxq (dawn, red coupe: "flat chalk-white panes"). Cause, measured:

- The three renderer textures of 5.1 (pane `0x00E7B4E949140568`, cabin trim `0x52573041E54EEEB7`, headliner
  `0x92AE80C504938232`) had prims only in VEHICLE-GLASS-2's private test layer. `remix_model_materials.py` writes
  prims per model *file*, and no model file names these textures, so the shipped `gta2hd` layer never had them.
  Remix drew every generated body's pane with its default opaque matte material over the pane texture's pale
  blue-white (`0x50B4C2C8`): a flat chalk card by day, cream under a street lamp at night, a dim grey-brown plane
  away from the lamp; the black stepped shapes inside it are the hull left where the mask found no glass (on the
  071 Rumbler, the filer's car: 290 glass texels, its near-black baked windows are dropped by the tyre-black rule).
  The cabin was not involved (ac922ec's lesson holds: check the draw before blaming the cabin).
- Fix: `remix_model_materials.py` emits the three prims itself (`FLEET_TEXTURES`, hashes computed from the same
  colours as `car_glass.cpp RemixTextures`, so a colour change there must be mirrored), on every full build;
  `--fleet-only` for a scratch layer + `remix_layer_merge.py`. The pane is thin-walled `AperturePBR_Translucent`, IOR
  1.5, transmittance (0.55, 0.58, 0.60) at 1 unit: a dark street tint, reflection from the Fresnel term. Trim
  roughness 0.80, headliner 0.90, colour from the legacy texture. `remix_car_prim_check.py` now counts the three
  renderer textures with the cars (it reported 0 missing while all three were).
- VEHICLE-ART-16's authored 014 / 027 / 046 / 062 also lacked prims at the time (their `_glass` drew chalk too); those
  landed meanwhile in 18accb5 (FIX-REMIX-MATERIALS-8). The takes below used a private layer with both sets.

Evidence (Ultra preset `gamerun/rglass_max.conf.extra` = the play preset + `rtx.graphicsPreset = 0`, GPU 6, own car
forced per model, window-height regress-camera poses, `gamerun/rglass_run.sh`): run rg_base2 (shipped layer) against
rg_fix1 (this layer), same stage and poses, 21:00 / 13:00 / 05:30, models 071 black, 062 black, 016, 051, 033, 014
(the stage's generated 014). Before: 014 and 033 panes flat chalk white day and night, 071 the filer's cream blob,
grey plane and black steps. After: dark tinted panes with sky and building reflections, the far window and the
street seen through, no white surface inside an unlit cabin. 051's authored glass unchanged. Run rg_fix2: the current
car set (authored 014/046/062 with their new prims, 071) at 21:00 and 13:00.

Still short of the bar (not fixed here):
- The generated bodies' masks: the pane outline follows the bake (ragged on 014-old, partial on 071, whose side
  windows stay baked hull except a rear patch). Lifting the tyre-black rule inside the glasshouse for dark coloured
  paints gives 071 290 -> 1102 texels (the whole side window) but also takes 003's rear door, 007's cab back wall and
  019's lower black flank (offline twin, fleet); not shipped. A per-z "above the paint belt" test is the next step.
- Box cabin (seats, dash, headliner boxes; no wheel), all one trim colour under Remix.
- prp1's night sparkle on authored glass (051 taxi) was not reproduced in these poses (wil 164.5,147.6, 21:00); untested
  at prp1's spot.
- The seated driver of a forced model draws outside the car in these probes (va6_own probe artefact).

rg_fix2 result: authored 014 / 046 / 062 (black) dark tinted glass with sky and facade reflections at 21:00 and 13:00.
**071 Rumbler (the filer's car) is NOT fixed:** at 13:00 its left window still shows a pale, stepped patch: the hull's
own bake where the mask found no glass (its partial pane is glass now; the rest is the 290-texel mask's miss). prx6 stays
open on the mask item above.

## 9. VEHICLE-GLASS-4 (10 Nov 2026): near-black windows on the belt; seated cars under Remix (prx6)

### 9.1 Near-black side windows over the paint belt (mask class rule, `BeltBlack` / twin `on_belt`)

The 071 Rumbler bakes its side windows near-black (value < 0.08) over a dark red paint (darkest paint cluster 0.19,
0.05, 0.04). The tyre-black rule (`val < 0.08` on a dark-paint body is never glass) dropped them: 290 glass texels, only a
rear patch. Lifting the rule (FIX-REMIX-GLASS, section 8) found 1102 but took 003's camo rear quarter, 007's cab back
wall and 019's black deck streaks. The rule now: cells of (side, 1/24 of 0.40-0.90 of the roof height, 1/48 of the
length) over the side faces (|nx| > 0.4), a cell paint / black when at least half of its texels (and 2) are. A
near-black texel in the glasshouse stays glass when its cell is black, at 0.55 of the roof or higher, has a paint cell
below it in its column, is part of a run of 3 such cells up the column, and its mirrored cell on the other side
(+-1 cell) is accepted too (bodies are symmetric; 003's black camo on one flank is green on the other). Front and
rear faces are never touched (003's rear doors, 007's cab back wall).

Fleet (offline twin, all 83 meshes, against 6a41782): 4 bodies change, none lose a texel:
071 290 -> 922 (both side windows), 019 566 -> 750 (inside its own side window), 030 2444 -> 2617 (its window's
corners), 003 1838 -> 1901 (a strip at the window's lower and rear edge). The DLL's count for 071 in the game is 922
(run vg4_rx1), the twin's to the texel. `GTA2DX9_GLASS_BELT=0` gives the old rule for a session; the twin's
`--nobelt`. Tried and dropped (twin `beltfill`, off): filling the dark cabin bake in the paint's dark shade inside
accepted window columns (071's front quarter of each window is dark red seats within its dark shade cluster's
tolerance): 071 +262 but 019 +537 and 030 +424 texels for little visible gain.

### 9.2 Seated cars with no rear screen drew no glass under Remix

`car_bodies.cpp` gives a seated car the glass only when its rear screen was found (`CarGlassHasRear`, 40 texels), so
that FIX-SEATED's see-through band shows the driver from the chase camera otherwise. That band is a plain-renderer
clip-plane draw and is never drawn under Remix, so under Remix a seated car with no rear screen got neither: its whole
baked window, the same frame with or without the glass prims (runs rg_base2 / rg_fix2 / vg4_rx1 on the own 071 are
identical in the window). 18 generated bodies with glass have no rear screen found: 002 016 017 019 021 023 030 031 037
041 044 047 048 052 054 071 083 085 (every traffic car of those models with a driver). `CarGlassHasRear` now returns
true under Remix; `GTA2DX9_GLASS_REAR_GATE=1` restores the gate.

### 9.3 Evidence and what still falls short

Remix, Ultra preset, GPU 7, `gamerun/rglass_run.sh` window-height poses, own car forced per model, 21:00 and 13:00:
run vg4_rx1 (the belt rule only: the own 071 seated, so the rear gate still blocked its glass: window identical to
FIX-REMIX-GLASS's rg_fix2) against vg4_rx2 (both changes, same poses). 071 (black): the middle and front of both side
windows become dark tinted panes with the sky/street reflection by day (blue-grey at 13:00) and the cabin's seat back and
B-pillar behind them at 21:00. 016: its rear side windows, baked red and white, become dark glass.

Still short: 071's rear quarter of each side window stays the pale stepped bake: those texels are baked in the paint's
own red hue (446 of the 531 pale side texels in the glasshouse are within the paint tolerance), so no colour rule can
take them without taking paint; a geometric fill (hull enclosed by pane and frame) is the next step. 071's rear screen
is still not found (near-black on a rear face: the belt rule is side-only). The cabin is boxes. prx6's own spot (bil
night, parked 071) not re-taken.

## 10. VEHICLE-GLASS-5 (10 Nov 2026): the mirror fill (prx6's 071 window corner)

### 10.1 One side's window copied onto the other (mask class rule, `MirrorFill` / twin `mirror_fill`)

The bodies are symmetric, their bakes are not. 071 Rumbler's left window is found up to the A pillar; on the right the
front quarter is baked in the paint's own red hue (446 of the 531 pale texels within the paint tolerance), which no
colour rule takes without taking paint. The rule, after `DropPaintComponents`: cells over the side faces of the
glasshouse (1/48 of the length, 1/16 of 0.60-0.90 of the roof height); a cell is glass when at least 0.6 of its texels
(and 2) are. Sources are glass cells with glass (or no texel) directly above and below, in an 8-connected group at least
4 rows tall and 12 cells big, so a trim strip one side's mask took (001's chrome belt) is never copied. The rule runs only
when the two sides' glass cells overlap (IoU >= 0.5): 003's camo flanks (IoU 0.00) and 007's cab (0.02) disagree, and a
mirror would copy each side's error to the other. A side glasshouse texel that is not livery becomes glass when the cell
at its station and height on the other side is a source; the result is closed by 2 texels inside the side glasshouse
(the two sides' UV rasters do not line up texel for texel). `GTA2DX9_GLASS_MIRROR=0` turns it off for a session; the
twin's `--nomirror`.

Tried first and dropped: a convex-hull fill of each side window (twin `hull=1`, off): it filled the pillars between the
006 box car's twelve windows (+3005 texels) and 002's sills, and missed 071's corner (no glass on that side to hull).

Fleet (offline twin, all 83 meshes, against b714fd5's rules): 17 bodies change, none lose a texel: 071 924 -> 1063
(its right window's front quarter), 049 2765 -> 3077 (the rear side windows baked dark red), 032 2400 -> 2712 (the third
side window), 002 +106, 033 +106, 047 +96, 083 +88, 035 +88, 037 +128, 048 +62, 064 +43, 054 +41, 019 +30, 067 +18,
001 +17, 068 +13, 016 +5.

Evidence (Remix, Ultra preset, GPU 6, `gamerun/rglass_run.sh` window-height poses, own car forced, 13:00 and 21:00):
run vg5_rx1 against VEHICLE-GLASS-4's vg4_rx2 (same poses). 071 (black): the right window's front quarter, a pale stepped
bake before, now shows the cabin seat and the street through the glass; at 21:00 the window is one dark pane with the
seat behind it, no pale blob. 049's rear side windows (baked dark red) are glass; 032's third side window is glass with
the facade reflection. DLL masks (`GTA2DX9_GLASS_DUMP`) = the twin: 071 identical, 049 one texel apart, 032 the same
count. Run vg5_rx2: the same after the rebase onto 1569a1d. Classic: vreg stage spawn_classic PASS, 0 tiles
(spawn_first's 24 tiles are the first-person fists of other commits).

Still short of the bar on 071: a pale band along the top of each window (above where either side's mask reaches) and
the baked B-pillar-like slab in the middle of the right window stay hull; the outline is ragged. 071's rear screen is
still not found. The filer's own spot (bil, parked 071, 5:30) is section 10.2.

### 10.2 The prx6 filer's own spot

Run vg5_bil1 (`gamerun/playtest_remix.sh`, bil 150.5,130.5, 21:00 and 5:30, Ultra preset, 4560f683): the parked black 071
at 5:30 in first person is a dark pane with a faint reflection; the cream/white blob, the tan wedge and the grey-brown
plane of the filing are gone. The cabin behind it is too dark to read at that hour.

### 10.3 prp1: the sparkle on moving glass is Remix's transmission PSR

Probe `gamerun/keys_vg5_prp1.sh` + `gamerun/vg5_prp1.py`: standing at the wil kerb (164.5,149.5) in third person while
traffic passes, segments of 20-25 s each with a live `[devtools] remix_config=` (re-read every 5-10 s under Remix) or
`car_glass`, cycled; frames cut from game_full.mp4 at 5 fps, the car-bearing frames picked by difference from the
segment's median (`/tmp`-side script; the method is in the run's keys.log marks).

- vg5_pq1 (19:30): the same purple sedan passed the same spot with PSR on and with `rtx.enablePSTR=False|
  rtx.enablePSRR=False`: 101 speckle pixels in its two door-pane interiors against 0. A moving bubble-top (authored
  glass) under PSR on: dense speckle on the dome.
- vg5_pq2 (6:30): reflection PSR off alone kills the reflection (a moving coupe's panes flat dark); transmission PSR off
  alone keeps the street reflection (PSRR) on a moving van, no speckle.
- vg5_dr2: the own car driven in the chase view (moving WITH the camera) shows almost no speckle: the noise belongs to
  glass moving across the screen, i.e. the denoiser's history of the surface PSTR puts behind the pane is rejected.
- vg5_np1 (static own cars, PSTR off, against vg5_rx2/vg4_rx3, rglass poses): 051's panes unchanged by day and night
  (flat dark tint, a faint low reflection); 071's pane loses the cabin and the street seen through it. So turning PSTR
  off trades the moving-glass sparkle for opaque-looking panes on the generated bodies: not shipped.
- All 15 translucent prims of the shipped gta2hd layer are model glass (hashes in model_prims.txt): a PSTR-related
  runtime option reaches only car glass.

### 10.4 Hull islands inside a pane (mask class rule, `FillHoles` / twin `fill_holes`)

VEHICLE-GLASS-4 measured the torn pane outlines as mask drips and enclosed hull islands (030 211 texels, 035 111, 034 78,
084 108). After the mirror fill, a 4-connected component of non-glass texels that touches no texel outside the body
raster (a UV island's border) and no image edge, of at most 300 texels, becomes glass unless at least half of it is
strictly bodywork. The guard matters: without it the 006 box car's paint pillars, enclosed by its glass in UV, became glass
(+2142 texels). `GTA2DX9_GLASS_HOLES=0` / twin `--noholes`.

Fleet (offline twin against 10.1): 19 bodies change, none lose a texel: 035 3734 -> 3843 (+109), 080 +13, 021 +12,
079 +6, 033 +6, the rest 1-4. 030's islands stay: they are within the paint tolerance of its dark green (strict), the
case the guard keeps out. 034, 044 and 086 were re-authored by VEHICLE-ART-17/18 at 15:07 with their own glass and are
outside the mask now (qav7's bus rear glass is theirs). The closing GLASS-4 proposed for the drips was not added: the
mirror fill's 2-texel closing already runs where it adds glass, and a fleet-wide closing grows into window frames.

Evidence: runs vg5_ho0 (`GTA2DX9_GLASS_HOLES=0`) and vg5_ho1 (on), Remix Ultra, 13:00, own 035 Benson and 033 at the rglass
poses: 035's side window had two white hull islands inside the pane (holes off); with the fill it is one continuous
pane with the facade reflection. DLL counts 3735 -> 3844 (twin 3843, the dumps one texel apart); 033 2117 -> 2123 (dump
identical to the twin). Classic: vreg stage spawn_classic PASS, 0 tiles (spawn_first's 24 = the fists of other commits).

### 10.5 prp1: two runtime knobs tried on moving traffic (FIX-REMIX-CARS-1, 10 Nov 2026; not shipped)

The probe is VG5's segment probe with three live `[devtools] remix_config` sets (`gamerun/frc1_prp1.py`, a copy of
`vg5_prp1.py`). Run `frc1_pq1`: wil 164.5,149.5, 19:30, the Ultra play rig, GPU 2. Five rounds of 25 s segments:
- A: default.
- G: `rtx.pstrMaxBounces=1`.
- H: `rtx.translucentMaterial.transmittanceColorScale=0.6`, which reaches only car glass: every translucent prim in the
  layer is car glass.

Frames were cut at 4 fps. A count of isolated bright pixels in the moving region came out at A 3.6, G 5.7 and H 3.2 per
1000 moving pixels. That count is dominated by the lane line glittering under passing head lamps, so it does not measure
the glass.

By eye, at 2x on the taxi passing in H (segment 1, frame 46), the rear door pane still carries yellow and white
dots. They are the car's own yellow inner faces and cabin, seen through the pane under the L4's noisy lighting. So:
- A darker tint does not remove the sparkle; it only dims it.
- One transmission bounce scores worse.

The L4 cannot start NRC and falls back to the importance-sampled integrator, and it has no DLSS-RR (docs/remix-parity.md
section 1). The owner's 5090 runs both, so how much of this sparkle reaches the owner is unknown from this host.

Next to try:
- An opaque glossy dark pane (AperturePBR_Opacity, roughness 0.05) for the image-to-3D bodies' far side only.
- Or a cabin liner material that is matte and dark enough that its noisy GI cannot show as dots.

Both need a same-car A/B, which only a parked own car gives. VG5 found that parked cars do not sparkle, so a deterministic
repro of the moving case is still missing.

## 11. VEHICLE-GLASS-6 (10 Nov 2026): panes synthesized from the glasshouse, column completion, a glass-path census

VEHICLE_PRIORITY 2 asks for the rule to hold by construction for every body: glass found -> a translucent tinted pane
over a dark cabin with the driver visible; glass missing in the bake -> a pane anyway, never the opaque bake and never
FIX-SEATED's band box (the black slab VEHICLE-ART-21 measured on 071/083, dd489cab).

### 11.1 Which bodies still missed glass after dd489cab (measured, offline twin over all 83 meshes + the DLL logs)

83 game models: 35 map to authored bodies with their own `_glass` (left alone), 42 to generated bodies with at least
200 glass texels, 6 below: 028 Dementia Limousine (0 texels: band when seated, painted windows otherwise), 045 Spritzer
(an open top), 054 tank, 055 tanker and 065/066 trailers, 061 flatbed (no glasshouse). Among the 42 "found" bodies whole
panes were still baked: 005 Beamer found 85 of 653 side texels, 104 of 768, no windscreen; 029 Dementia none of either
side (its windows are baked in the paint's own beige); 002, 016, 035, 037, 048, 071 no rear screen (no driver from the
chase camera, 071 is prx6's car); 016/019/029/048 no windscreen.

### 11.2 Synthesized panes (`SynthesizePanes`, twin `synthesize`)

After the colour rules, model-wide over every body texture (the floor pan excluded), four apertures from geometry: each
side's windows (side faces |nx| > 0.4 in the roof span, 0.63-0.87 of the roof height, 0.05 of the length kept at each end
as the A/C pillars, a 0.035 B pillar in the middle of a span over 0.30 of the length), the windscreen and the rear screen
(facing forward / back, 0.66-0.87, inset 0.14 of the screen's own width each side). A region whose found glass covers
under a quarter of its aperture takes the whole aperture, less bright livery (saturation > 0.55, value > 0.60). Guards:
- sides and the rear screen only on a car-like glasshouse: roof span at most 0.70 of the length and tumblehome (the side
  glass's |x| at 0.78-0.87 of the roof under 0.90 of the belt's): box truck 007, bus 011, vans 052/067/068, 003, 017,
  021 measure 0.96-1.00 (or a long span) and keep their blank flanks; the windscreen on every closed body;
- a side only when BOTH sides missed (painted-on windows); one side found and the other not is an asymmetric body
  (023's serving hatch) or the mirror fill's business (10.1);
- the tank, the trailers and the flatbed (54, 55, 61, 65, 66) and the wrecks are never glazed.

### 11.3 Column completion

On a side the colour rules did find, a station (1/48 of the length) whose aperture is at least 0.4 glass takes its
aperture above the median height of its found glass; a station under 0.4 (a pillar, a door's baked slab) stays. This
removes the pale band the bakes leave along the top of a window (prx6's 071, 10.1 "still short"). Two first forms were
dropped after frames: the whole aperture height (down to 0.63 of the roof) cut a dark notch under 071's chrome belt (run
qa_vg6_a2), and "up from the station's lowest found glass" still cut notches under 002's (qa_vg6_a3): stray found texels
sit at the sill. A synthesized side (11.2) starts at 0.66 for the same reason (028's sill spots at 0.63, qa_vg6_a1).

Switches: `GTA2DX9_GLASS_SYNTH=0` (no 11.2 or 11.3, the dd489cab masks), `GTA2DX9_GLASS_COLUMNS=0`; twin `--nosynth`,
`columns` param. Log: `car glass: <model>: glasshouse span .., tumblehome .. (car | van/truck: windscreen only),
synthesized panes: <region> N of M, ...; side columns +a / +b`.

### 11.4 The census line

`car bodies` logs once per model and seated state, for a car within 30 blocks once its mask is built:
`car glass path: model N (<mesh>) seated|empty: own glass (authored) | glass + cabin | FIX-SEATED band | open top |
painted windows`. `gamerun/vg6_census.py` (+ `keys_qa_vg6cen.sh`) stands at kerbs in third person while traffic passes
(`WARPS`, `CEN_SECONDS`), so a run's log is a census of the paths.

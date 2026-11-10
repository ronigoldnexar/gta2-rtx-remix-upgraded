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

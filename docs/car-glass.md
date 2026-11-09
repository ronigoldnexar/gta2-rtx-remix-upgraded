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

# Vehicle shading: the paint's clear coat (FIX-CAR-SHADING-1, 10 Nov 2026)

The owner, after his own session on the 5090 (defects owner10nov-4): "some of the vehicles look a bit
too childish": the green coupe (the wil 018 Shark, an authored carkit body) smooth and toy-like, no
panel lines, one flat paint tone, no material variation. This is about how the car bodies are
**shaded** in the street views, not modelled.

## What was measured first (HEAD 8879b1d8, plain GL, noon, own car stopped, forced green paint)

`out/csh_base2` (018, 063, 068, 002 at chase / rear 3/4 / side / front 3/4): every body is one flat,
saturated tone from every side. The fixed-function light gives a diffuse gradient and a per-vertex
Blinn lobe (power 50) that on the dense generated meshes is a soft blotch, not a highlight. Nothing
reflects: a car's flank facing the street is as bright as its roof facing the sky, which is what
reads as moulded plastic. The curvature view of the coat pass (`[devtools] car_coat=2`, `out/csh_ab2`)
shows why a crease-angle policy cannot add panel lines: the generated and the kit bodies have
almost no concave geometry (no modelled gaps); their door, bonnet and panel seams exist only as
dark lines painted in the textures.

## The mechanism: a coat pass over every car body (plain renderer)

`dll/src/car_coat.{h,cpp}`, `src/shaders/car_coat.hlsl` (SM3, built by
`tools/build_car_coat_shader.sh` in the Wine 10 image: Wine 9's compiler cannot build it).
`ModelDraw` (model_store.cpp) draws a second pass over each car body mesh right after its
fixed-function draw, with the same buffers, cut masks and clip planes (moved to clip space), blended
`ONE, SRCALPHA`: frame = coat.rgb + frame x coat.a. car_bodies sets the weight per car (1 clean,
less with dents and fire, 0 for wrecks, wheels, the seat view's hood copy and cab, and translucent
draws). The shader adds:

- **Clear coat**: Schlick Fresnel (F0 0.04) reflection of the street below a horizon line, a blocky
  skyline whose height steps with the reflection's bearing (it slides over the body as the car turns),
  and the sky's gradient above it, from the same weather-adjusted zenith/horizon the dome and the
  post's hemisphere term use, at the hour's light. The base takes (1 - F). A flank now darkens where
  it reflects the street; a bonnet or roof seen at a slant takes the sky.
- **Sun glint**: a normalised Blinn lobe (power 350) plus a soft halo, per pixel, in place of the old
  per-vertex lobe (`car_coat_ffp_spec_percent` 0); none at night.
- **Base coat sheen** in the paint's own colour (power 24) with a faint per-cell flake, faded out
  where a cell is smaller than a pixel.
- **Creases and edges** from the curvature (screen derivatives of the normal against the position):
  concave folds darken, convex edges catch a little of the horizon light.
- **Panel gaps**: the texture's own painted seams (a 4-tap luminance Laplacian 1.5 texels wide
  against the local level) are darkened further and break the coat's reflection, the cue that makes a
  line read as a cut in the sheet metal. Geometric gap templates (door shut lines at the door
  animation's cut, bonnet/boot lines from the cabin) were tried and dropped: on 002 the template's
  rear door line fell 25 px from the line its texture paints (a double line), on the 018 fastback the
  boot line hid under the rear glass (`out/csh_ab3`).

The paint's colour stays identity.cpp's (the coat samples the same texture and tint; it adds light,
not tint). The reflected sky keeps half its colour and its zenith half the horizon's radiance, so a
lid seen from above (the classic camera, the paint gate's pose) keeps the sprite's hue and level: a
first version with the full blue zenith put +12 % L* and 9-15 degrees of hue on the gate's lids
(`out/cshp1_parity.md`, 2 FAIL), see below for the gate on the shipped version.

Never under RTX Remix (`RemixApiAvailable()`: the path tracer has the layer's PBR maps; the pass
would also be a second draw of the same triangles, which Remix drops or doubles) and never in the
classic view (no car bodies are drawn there).

## Keys

`[renderer]` (package/gta2dx9.ini): `car_coat=1`, `car_coat_f0_percent` 4, `car_coat_reflect_percent`
100, `car_coat_sky_percent` 180, `car_coat_power` 350, `car_coat_crease_percent` 100,
`car_coat_flake_percent` 50, `car_coat_sheen_percent` 10, `car_coat_rest_percent` 35 (the coat on a
generated body's non-paint texels), `car_coat_gaps_percent` 100, `car_coat_ffp_spec_percent` 0.
`[devtools] car_coat=0|1` live A/B (re-read every 60 frames), `2` the curvature view, `3` the coat
without the gap detector. Log line at the first street frame: `car coat: ready (...)`; frame-time
detail lines carry `coat (in hull)` among the car parts.

## Crease and normal policy

`car_smooth_normals=1`, `car_crease_deg=60` stay: the welded normals are what keeps the generated
bonnets from shading as a mosaic of chart facets (VEHICLE-GLASS, vr-generated-bodies-hard-facets), and
the coat's reflection needs smooth normals (a faceted normal field breaks the horizon line into
tiles). Silhouettes are untouched by either (no geometry changes).

## Remix

Under Remix the bodies' look comes from the layer's PBR prims (tools/remix_model_pbr.py,
remix_model_materials.py): the paint texels already take a clear-coat class (roughness 0.18, metallic
0.05) and an albedo-derived normal map whose Hessian line detector turns painted seams into grooves.
What the layer still lacks is what this pass shows the bodies need and the albedo cannot give: the
kit bodies' paint textures are nearly flat, so their normal maps carry no seams. The note to the Remix
and vehicle-art seats (defects/assigned/vr-vehicle-art-audit-batch.FIX-CAR-SHADING-1-note.md) lists
the generator step. No albedo texture is changed by this work, so no Remix prim hash moves.

FIX-REMIX-CARS-1 (10 Nov) built that layer step: the paint normal loses the albedo grain, the painted gaps are cut in as grooves with a rougher floor, the kit meshes' concave folds are baked into the paint texture's normal/roughness, and the coat is 0.12. Details, frames and what is still short: docs/remix-materials.md, "Car paint under a clear coat".

## Results (frames opened, private stage of this commit's build, wil street warp, own car stopped)

- Same-pose before/after, noon: `out/csh_fin0` (car_coat=0) vs `out/csh_fin1` (coat), 018 green (the owner's
  coupe), 063 red, 068 blue at rear 3/4, side, front 3/4. The coat turns the lime-plastic tone into painted
  metal: flanks darken where they face the street, the bonnet, roof and the 063's wings take the sky, the
  painted seams read as cuts. 19:00 (paused clock, low sun; plain GL keeps a bright sky): `out/csh_dusk1`
  (live A/B per pose, `o` old, `n` coat). Earlier tuning rounds: `out/csh_ab1`..`csh_ab4`, `csh_063a`.
- Paint gate (tools/identity_parity_run.sh): `out/cshp3_parity.md` **0 FAIL**, 16 WARN; the WARNs are the
  +17..21 % lit-lid lightness the HEAD gates show too (va19_gate2: 002 +17/18, 063 +18/20), hue 0-5 degrees.
  The two earlier gates of this work failed and were fixed: cshp1 (full blue zenith: +12 % L*, 9-15 degrees
  of hue) and cshp2 (the 063 Truck Cab drew flat grey rectangles over its wheels from above, most likely a NaN
  from zero-length normals in the pass: the shader now falls back to the eye's direction; gone in cshp3).
- vreg (tools/vreg/vreg.sh stage): `spawn_classic` PASS, **0 changed tiles**; `spawn_first` 21 tiles = the
  FIGURE-14 fists against the stale golden (no car in that frame), as at HEAD; 30 PASS.
- Frame time (linux/docker/csh_perf.py + keys_csh_perf.sh, copied to gamerun/; tools/csh_perf_an.py, one session, car_coat toggled every 20 s, 4 cycles):
  the sprites stage's car part ("cars", CPU) 1.444 ms off vs 1.482 ms on over ~1500 frames each (+0.04 ms;
  +0.13 ms over the two steady cycles), below the 0.3 ms budget and inside the host's noise; the GPU share
  is not separable under the VGL readback present (~35 ms) of the container.

## Still short of a shipping-AAA frame

- The reflection is an analytic environment (street, a hashed skyline, the sky): no real buildings, no other
  cars, no screen-space reflection. It reads as paint, not as a mirror of this street.
- Panel lines exist only where the textures paint them: the kit bodies' rear decks (the owner's 018 tail) and
  most bonnets have none, and the geometry is still soft (a modelling item for VEHICLE-ART).
- No coat from the driver's seat (the seat view's hood copy and cab keep the fixed-function look).
- Under Remix nothing changes until the layer step in the note is built.

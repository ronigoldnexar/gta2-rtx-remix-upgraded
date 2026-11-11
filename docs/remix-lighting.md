# Remix lighting: the light state our DLL pushes (FIX-REMIX-NIGHT-2/-3, 10 Nov 2026)

Scope: what `dll/src/remix_lights.cpp` (and the first-person cab's Remix-only albedo path in
`cab_interior.cpp` / `car_bodies.cpp`) hands the path tracer. The materials (mod.usda prims,
`tools/remix_materials.py`) are in `docs/remix-materials.md`. The classic view's draws are untouched:
everything below either changes only the light list or is gated on a Remix device, and the plain
renderer is unchanged (checked below).

## What changed

| change | where | gate | A/B key (`[devtools]`, re-read ~1 s) |
|---|---|---|---|
| First-person cab surfaces carry their colour in the texture (Remix reads no material or vertex colour: the cab was white by day, cream at night) | `cab_interior.cpp` `SurfaceTextureTinted` | Remix device only | `remix_cab_albedo=0` |
| The seat's clean bonnet surface drawn under Remix too, its colours baked into a small texture (`BonnetTexture`); it joins the scuttle instead of the broken hood copy | `car_bodies.cpp` `DrawBonnet(..., remix)` | Remix device only | `remix_cab_albedo=0` / `fp_bonnet=0` |
| The night player fill goes over the roof while he drives (it hung inside the cab and lit the lining) | `live_geometry.cpp` `PlayerFillSubmit` | Remix light; street views | `remix_fill_in_cab=1` |
| Night sky fill: a soft cool distant light from straight above (60 deg across), radiance `NightSkyFill` (0.06) x the lamps' clock; it lit nothing before after dusk, so roofs and lids went black, worst in the classic view | `remix_lights.cpp` `ApplyAmbientFill` | Remix with its atmosphere; 0 by day | `remix_night_fill_milli=N`, probe bit 8 |
| Dusk ramp of the same fill: rises (smoothstep) from the sun `DuskFillDegrees` (25) above the horizon to the night's level at sunset | `ApplyAmbientFill` | sun elevation; 0 by day | `remix_dusk_fill_deg=N` (0 off) |
| Red/pink map lights are signs (the wide-neon warm-white rule) in the street views, not sodium lamps; lamp-post pools from saturated lights are warm white | `Describe`, `FitLampsToPosts` | street views | `remix_sign_lights=0` |
| Junction signals: a downward 75 deg soft cone at 35 % of the old power at night, 10 % of that by day, colour a third of the way to white | `Describe`, `Apply` (`TrafficShaped`) | street views | `remix_traffic_old=1`, `remix_traffic_pct`, `remix_traffic_day_pct` |

New settings (`package/tuning/gta2dx9_settings.ini`, `[lights]`): `NightSkyFill=0.06`, `DuskFillDegrees=25`.

The night/dusk fill is the only one of these that reaches the classic view: it is light state, not a
draw. By day its share is 0 (lamps' clock off and the sun above 25 deg), so the day classic frame gets
exactly the light list it had before (the fill handle is destroyed, as before the change).

## Evidence (path-traced, GPU 2, private stage, paused clock, same-session toggles)

Runs `frn3_w1` (wil, 12/17/19.5/22.5), `frn3_w2` (wil, 17/22.5), `frn3_s1` (ste junction 108,117.4 at
22/2/12), `frn3_w3` (the rebased build, wil 22.5/12); plain GPU-GL `frn3_pb` (base e561425) / `frn3_pm`
(this change). Luma is 0..1 (Rec.601 of the PNG).

| check | old | new |
|---|---|---|
| FP cab (BD4 forced), 22:30, whole frame mean / top 15 % (header) / bottom 25 % (dash) | 0.24 / 0.34 / 0.42 | 0.10 / 0.11 / 0.12 |
| FP cab, 12:00, top 15 % / bottom 25 % | 0.63 / 0.69 | 0.45 / 0.36 (no pure-white run) |
| classic 19:30 / 22:30, roof patch at 120.5,112.5 | 0.012 | 0.123 |
| classic 22:30 at 164.5,149.5, roof band (x 300-1000, y 0-50) / whole frame | 0.046 / 0.103 | 0.141 / 0.169 |
| classic 12:00 at 164.5,149.5, whole frame, rebased build (fill 0 / default, alternating) | 0.442, 0.442 | 0.443, 0.442 |
| 17:00 first person at 120.5,110.5: bench / bin / paving | | 0.16 / 0.27 / 0.35 |
| ste 02:00 crosswalk red pool | hot saturated disc | faint even pink on two stripes |

Plain renderer: first person seated, 12:00 paused: the dash band (y 560-720) of base vs this change
differs in 1.2 % of pixels (mean 1.3/255: the two runs' scene cars had different paint); on this
change's build every Remix key at default vs at its old value gives an identical dash band.

## Still short of a shipping frame

- The cab header is a flat beige slab by day and the pillars are flat bars (geometry, not light).
- At night the cab is uniformly dark: no lamp or headlight bounce shows on the dash.
- Junction signals: the far-facade green slab was not seen at the filer's spot in these runs (signal
  phase); only the red crosswalk pool is proven.
- Red neon: proven on FIX-REMIX-NIGHT-2's build at the filer's spot (`frn2_p2`, same code); the rebased
  runs' warps to the spawn plaza faced away from the sign or were refused.
- Police sirens: no flood reproduced at the filer's spot on the night-fill build (`frn2_p3`); the
  beams light little at all, which is its own question.

## FIX-REMIX-NIGHT-4 (10 Nov): sodium lamps, day bounce fill, the night orders re-judged

All takes on the shipping play config (`rtx_play.conf.extra`: game directional light ignored, see
docs/remix-materials.md on dac1c77), GPU 2, private stage, paused clock, fixed hours, same-session
`[devtools]` toggles. Runs `frn4_w1..w3` (wil), `frn4_h2..h5`, `frn4_s1` (ste). Probes
`gamerun/frn4_probe1..8.py` with `gamerun/rn4_keys.sh` (rn_keys.sh with a `to_level` that waits for the
swapped district's map, not only wil.gmp: in ste/bil the stock one taps Return for 240 s).

| change | where | gate | A/B key |
|---|---|---|---|
| Sodium map lights (#FF8000, blue exactly 0) are an amber white (1, 0.74, 0.46) at their own luminance, and their lamp-post pools with them: a wall they reach keeps its blue channel and stone colour | `Describe` | street views | `remix_sodium_white=0` |
| Day bounce fill: a warm grey (1, 0.93, 0.82) share of the overhead fill light while the sun is up (smoothstep over its first 20 deg), the bounce off sunlit stone that the 3x blue sky alone lacks | `ApplyAmbientFill` | street views, Remix atmosphere | `remix_day_fill_milli=N` (0 off; setting `[lights] DayBounceFill=0.4`) |
| Siren beams: cone 22 -> 40 deg, pitch 12 -> 6 deg down: the sweep reaches the facade across the street (it met the road within ~3 blocks and lit nothing else) | `synthetic_lights.cpp` siren defaults | sirens (all views) | `[Sirens] ConeAngle= Pitch=` in the effects ini, live with `GTA2DX9_EFFECTS_LIVE=1` |
| Player-fill probe keys (no default change): strength, height, slide toward the eye, horizontal slide, colour, emitter radius | `PlayerFillSubmit` | Remix light | `remix_fill_pct`, `remix_fill_lift_milli`, `remix_fill_toward_milli`, `remix_fill_flat`, `remix_fill_rgb`, `remix_fill_emitter_milli` |

Evidence (luma/colour of the PNG, 0..255; chroma = (max-min)/max per lit pixel):

| check | old | new |
|---|---|---|
| wil 150.5,200.5 21:00, the tan wall (third / first): b/r of the wall | 0.25 / 0.28 | 0.41 / 0.43 |
| same wall: texels with B = 0 and R > 60 (filer's 4d99b77 frame: all of them) | 0 on HEAD already | 0 |
| same wall: local contrast (mean abs high-pass) | 1.56 / 1.38 | 1.56 / 1.37 |
| wil 07:00 first person, shaded road: mean colour, chroma, hue (sunlit road 0.27, hue 41) | (48,62,75) 0.42, 208 | (84,95,95) 0.22, 183 |
| wil 16:30 p2 third, shaded road right / left | 0.51 / 0.37, hue 208 | 0.22 / 0.15, hue 190 |
| wil 16:30 first, shaded facade hue (stone is ~35) | 84-114 (grey-green) | 37 |
| Remix classic at the cobalt spots, day fill 0 vs setting (whole frame mean) | | identical |
| bil 47.5,74.5 siren (force_sirens=1), 23:00 third: facade pixels with a red or blue cast, best of 10 frames | 0.01 % | 5.3 % red, 3.5 % blue (brick visible through it) |
| same, frame-mean saturation / off-phase mean luma (bars 0.6 / 0.06) | 0.23 / 0.10 | 0.23 / 0.10 |
| SAVES courtyard 22:30, fixed camera, sign rule (3a7d510) off / on: lit paving, stair wall chroma | 0.65, 0.53 | 0.37, 0.28 |

The sign light's own colour share (a red cast) was tried at 20 and 35 %: the lit wall moved within the
noise (the courtyard is lit by the warm-white lamp-post pools, not the sign light), so it was dropped.

Re-judged, no code change needed on HEAD:
- Hero hair at 19:30 (ste 147.5,120.5): fixed close camera (0.75 tiles out, 0.65 over his head) on four
  sides, and the filer's own runner (`remix_playtest.py`, hours 12/6.5/19.5): the crown is dark brown
  at 19:30 in every take; right profile crown luma 19.8 vs face 29.1 (06:30: 31.8 vs 39.6). Player fill
  off, sky fill off and a horizontal fill all keep it brown. A 0.4-tile fill emitter floods him (rejected).
- A camera inside a wall (the probe's front pose) puts the toward-the-eye fill against the wall: a hot
  white blotch. In play the boom is collision-solved, so this needs a camera pressed to a wall to show.

Still short of a shipping frame: shade at low sun is now grey-teal rather than warm (a real street's
bounce varies with what is sunlit; one overhead fill cannot); the courtyard under the red sign has no red
cast at all; in first person a flat saturated red/blue disc floats beside a siren car (a beacon emitter seen
close: separate look defect, not addressed); the night roofs and the cab are as FIX-REMIX-NIGHT-3 left them.

## FIX-REMIX-NIGHT-5 (10 Nov): smoke puffs without fireflies, a golden low-sun bounce, the signal slab re-taken

Play config (`rtx_play.conf.extra`), GPU 6, private stages, paused clock, same-session `[devtools]` toggles; probes
`gamerun/frn5_probe1..7.py` with `gamerun/rn4_keys.sh`. Note for every probe: under Remix the devtools keys are read
every 5-10 s of wall time (slow frames), so label frames from the DLL log's `devtools:` lines, not from the probe's marks.

| change | where | gate | A/B key |
|---|---|---|---|
| Smoke and exhaust puffs: the opacity step is cut from a coherent noise (wisps ~1/16 of the puff, ranked so the covered share per step is the old one), stored as a smooth alpha field and sampled bilinear under the alpha test (smooth cut edge at any size), shaded in the albedo (thick = lighter, rim darker), one pattern per puff for its life | `vehicle_fx.cpp` `PuffWispsReady` | Remix device (the puffs are street-view effects) | `remix_puff_mode` 0 old dither / 1 wisps (default) / 2 none / 3 no exhaust |
| Day bounce fill colour: golden (1, 0.78, 0.55) with the sun under 8 deg, blending to the noon warm grey by 30 deg, same luminance | `remix_lights.cpp` `ApplyAmbientFill` | street views, sun up | `remix_low_bounce_warm=0` |
| A/B keys only (default = before): wide-neon threshold live, signal-light lift, headlamp/beacon emitter size | `Describe`, `synthetic_lights.cpp` | street views | `remix_wide_neon_tenths`, `remix_traffic_lift_milli`, `remix_bulb_pct` |

Evidence:

| check | before | after |
|---|---|---|
| wil 109.5,124.5, `spawn_smoke`, 22:00 and 12:00, far and close fixed cameras (frn5_p1, p3) | a cloud of isolated white texels (the firefly specks); at 0.6 tile hard white squares | coherent grey wisps with shaded volume; no isolated texels; `remix_puff_mode=2` (no puffs) removes the specks entirely, so the specks were the puffs |
| first person over traffic at 22:00 (frn5_p1) | white squares at a braking taxi's front wheel (the ptrmx20 look) | none from the smoke; one small white glint per headlamp on the asphalt remains with the puffs off (the lamp emitter's reflection) |
| wil 16:30 shaded road, first person p1 150.5,200.5 / third p2 240.5,100.5 (frn5_p3, alternating 0/1/0/1) | sat 0.22, hue 193 / hue 182 sat 0.07 | sat 0.11, hue 191 / hue 137 sat 0.03 (neutral, not teal) |
| wil 07:00 p2 shaded road | hue 68 sat 0.06 | hue 43 sat 0.13 (warm) |
| classic at 07:00, low bounce 0 vs 1 | | identical whole-frame mean |

The junction signal's green facade slab (pt-remix-traffic-light-green-wash-slab): five takes now (frn3_s1, frn4_s1,
frn4_s3, frn5_p2, frn5_p4). frn5_p4 put fixed cameras over the filer's landing (ste 108.0,117.4) in 8 headings at 22:00
and 02:00 and alternated the filer's light rules (`remix_traffic_old=1 remix_sign_lights=0 remix_wide_neon_tenths=0
remix_sodium_white=0`, the d933eaf look) with the shipped ones every 2 s: no facade slab in any heading with either.
The filer's frame predates f9d219f (wide saturated map lights warm white) and 3a7d510; the green map lights near
that junction (#008000 r 4 at 115.5,109.5,4.5, #80FF80 r 4 at 98.5,107.5) are now warm white; with the rule off a
facade takes a faint green cast (frn5_p2), not a slab. A red pool on the crossing (west camera) did not change with
the signal lift (`remix_traffic_lift_milli` 0/650, frn5_p6): it is probably not a junction signal (unidentified).

Headlamp discs (ptrmx20): the white discs on a stopped bus's lamps (frn5_p5b, fixed cameras in front of it) are the
model's lamp lenses, the same at emitter size 100 % and 45 %: a material (lens emissive), not a light emitter.

Still short of a shipping frame: the puffs are cut-outs (a cloud of shaded wisps, not translucent smoke: Remix's
translucent particle path rendered them black, NIGHT); shaded vertical facades at low sun stay blue (the bounce
fill comes from straight above); the headlamp lens discs blow to flat white; the red crossing pool at ste 108,117.4.

## FIX-REMIX-NIGHT-6 (10 Nov): lit windows, the gantry lenses, sign lights that spare their own letters

Play config (`rtx_play.conf.extra`), GPU 0, private stages, paused clock, same-session `[devtools]` toggles; probes
`gamerun/frn6_probe1..8.py` with `gamerun/rn4_keys.sh`. Labelling note: under Remix the devtools re-read AND the
denoiser's history lag a toggle by 10-20 s of wall time; label frames from the DLL log's `devtools:` lines and read the
light-dependent patch over the whole sequence (it steps between two levels), not the probe's marks.

| change | where | gate | A/B key |
|---|---|---|---|
| Lit-window room lights: every wall face whose tile is a lit-window tile (warm panes in the art, picked from a scan of the HD tiles: ste 276/281/311/480/493/505-508/961/962/983, wil 100/125/127/498/810/815, bil 243/246/293/788/793; tile ids and the pane band's height only) gets a small warm (1, 0.71, 0.42) spot 0.25 tile in front of the pane band, aimed down and out (80 deg), nearest 40 within 18 tiles of the eye; faces against a solid neighbour are skipped (ste: 1137 faces) | `remix_lights.cpp` `BuildWindowLights`, `SubmitWindowLightsNear` (called from `LightsSubmitMapLampsNear`) | Remix device, street views (the far lamps' sky blend), night (the lamps' clock) | `remix_window_pct` (0 off), `remix_window_out_milli`, probe bit 9 |
| Gantry signal lenses (wil, the 12 slope-53/54 slabs with tile 753 that FIX-WORLD-8 draws as a 0.17-block plate): a dim teal (0.45, 1, 0.9) sphere 0.07 tile in front of each lens at night; the tile is static decoration (no phase), so one fixed colour | same | same | `remix_gantry_pct` (0 off) |
| Sign lights spare their sign: a sign or neon map light with a curated lit-sign face (tools/remix_emissive.py's SIGNS ids) within 2 tiles is a half-space lamp shining away from that sign (80 deg, 0.12 tile further off) | `Describe`, `Apply`, `SignWallNormal` | street views, map lights | `remix_sign_wall=0`, `remix_sign_red_pct` |

Classic: `tools/vreg/vreg.sh stage` on the build, spawn_classic 0 changed tiles (out/vreg_frn6_a); the plain renderer
gets none of these lights (window/gantry lights are submitted only with a Remix device; the sign shaping is in the
Remix light description only).
| Junction signal light lifted to head height on the post by default (`remix_traffic_lift_milli` 650; it was 0) | `Describe` | street views, shaped signals | `remix_traffic_lift_milli=0` |
| A wide sign light keeps 35 % of its own colour under the warm-white sign rule (default 0 before) | `Describe` | street views | `remix_sign_red_pct=0` |

Evidence (luma 0..1 of the PNG; frames by mtime against the DLL's devtools lines):

| check | before (key off) | after (default) |
|---|---|---|
| ste 206.5,227.5 22:00, lit tower from the west (frn6_p8, rebased build frn6_p9): ledge band under the windows / lower facade / p95 | 0.122 / 0.141 / 0.244 | 0.189 / 0.193 / 0.345 (warm, under the panes; no blown area) |
| same, street camera at 211.5,226.5: ledge / lower facade / paving at the block's foot | 0.119 / 0.133 / 0.140 | 0.167 / 0.191 / 0.202 |
| same two cameras at 17:30 and at 12:00 (frn6_p8, frn6_p1) | | identical to the key off (the lamps' clock is 0) |
| wil gantry lens at 115.87,172.5 under the beam, 21:30/22:30 (frn6_p3, frn6_p5): lens patch green mean | 21 of 255 (dark teal) | 41-62 (lit teal lens, ribs readable), unchanged at 16:30 |
| ste 108.0,117.4 22:00 crossing from above (frn6_p6, three 24 s cycles; frn6_p9): traffic class out / lift 0 / lift 650 | | none / a hot red, green or amber-white double spot on the stripes in every phase (p99 0.69-0.79) / a soft even tint over 4-6 stripes (p99 0.45-0.50) |
| wil SAVES stair 22:30 (frn6_p7), stair wall right of the sign: mean rgb, chroma | (41,42,38) 0.29 with the sphere | (58,56,48) 0.33 faced away; (71-75,52-54,45-47) 0.34-0.37 with the 35 % red share: a red tint, under the 0.6 bar |

Not changed by any light: the SAVES letters' white speckle (tiles 742/743's albedo texels outside the emissive mask: a
material ask, note beside the neon order), and the first-person siren disc, which stays with every one of our lights
off (frn6_p2 shot_225/230): it is car_bodies.cpp DrawBeacons' Remix bulb quads (note beside the siren order).

Still short of a shipping frame: the window light is one spot per pane tile, so a facade reads as evenly warm ledges
rather than individual rooms (no per-window variation, no curtains, no unlit rooms); the lit windows themselves are
still albedo, not emissive (they do not bloom); the gantry lens is a teal lamp with one fixed colour (the tile has no
phase); the lifted signal pool is a soft blob of signal colour, not a lens throw; the SAVES letters stay speckled.

## FIX-REMIX-NIGHT-7 (10 Nov): a moonlit night between the sodium lamps, the siren lamp on its light bar

Play config (`rtx_play.conf.extra`, `ignoreGameDirectionalLights = True` checked in every take), GPU 4, private
stages, paused clock, same-session `[devtools]` toggles labelled from the DLL's `devtools:` log lines; probes
`gamerun/frn7_probe1.py` (light-class variants at a spot, third/first/classic, two hours), `frn7_probe2.py` (siren
states), `frn7_probe3.py` (fixed REGRESS_CAM cameras + views, moon fill A/B) with `gamerun/rn4_keys.sh`.

| change | where | gate | A/B key |
|---|---|---|---|
| Night moon fill: by the lamps' clock the street views' fill is 0.14 x (0.36, 0.48, 1.0) in place of 0.06 x (0.78, 0.86, 1.0); the dusk ramp before the lamps' hour and the classic view keep the old fill | `remix_lights.cpp` `ApplyAmbientFill` | Remix, street views, lamps' clock | `remix_moon_fill_milli=0` (the NIGHT-6 fill), `remix_moon_rgb` |
| Live probes of the sodium amber and strength (defaults unchanged) | `Describe` | street views | `remix_sodium_rgb`, `remix_sodium_pct` |
| Siren beacons under Remix: no more three crossed additive glow quads per bulb (Remix drew them as a wheel-sized flat red/blue disc with a cross, floating off the roof); one small eye-facing glow cap (half-size 0.022 tile) per lit bulb on the top of the model's own light bar, found once per model as the vertices in the top 5 % of the body's height (none on a flat-roofed body) | `car_bodies.cpp` `DrawBeacons` Remix branch, `BeaconLampSpot` | Remix only (the plain renderer's beacons unchanged) | `remix_beacon_quads=1` (old quads), `remix_beacon_cap_milli` |

Why the bil street was olive (prmx): the filer's DLL predated the amber sodium rule (road blue 6/255); on the
0d1520c stage the street was already warm-brown, not sulphur (frn7_rt1: road by the car 75,69,50; hero tee
near-black, skin natural). The class split at bil 150.5,130.5 21:00 (frn7_p1): with the street lamps out the road
read neutral (25,26,24), all our lights out near black (3,4,5); the 0.06 fill added only ~(5,7,8). The rest of the
warmth between lamps is the sodium amber on an asphalt whose albedo is itself green-yellow, so only a clearly blue
fill can give a blue-grey shade (frn7_t1 sweep: moon (0.55,0.70,1) x 0.15 turned the road teal-green, G > B).

Evidence (mean RGB of the PNG; old = key off in the same session):

| check | old | new |
|---|---|---|
| bil 150.5,130.5 21:00 third, road between lamps (frn7_v1 shot_135/150) | 41,42,33 (B < R, olive) | 41,46,46 (B >= R, blue-grey), luma 41 -> 45 |
| same, lamp pool under the post | 58,40,26 | 58,41,28 (warm pool kept) |
| same, hero tee (chest patch) at 21:00; 13:00 reference 35,35,35 (neutral charcoal) | 12-17,11-15,10-13 (warm brown-black, hue 21-27) | 16-17,15-16,17 (neutral-cool, B >= R) |
| bil 100.5,100.5 21:00 third, the lit road at the police station (shot_260/250) | 110,107,72 | 111,108,78 (warm pool kept) |
| 13:00 at both spots, third/first/classic full-frame luma (shot_375/355, 405/390, 435/420) | 132 / 116 / 139 | 131-132 / 116 / 139 (day: identical) |
| bil 21:00 classic, ground patches (shot_215/205) | 31,35,28 / 38,42,32 | 30,35,28 / 38,42,32 (classic unchanged) |
| wil SAVES 22:30 stair camera (frn7_w1 shot_140/160): sign / paving / stair wall | 203,135,122 / 58,53,47 / s 0.37 | 196,126,114 / 59,57,58 / s 0.24 (wall still red-tinted, weaker) |
| wil SAVES 22:30 third (shot_250/265): sign / paving | 206,162,147 / 65,66,57 | 206,162,147 / 66,70,70 |
| ste 206.5,227.5 22:00 lit tower, west camera (frn7_s1 shot_150/135): windows / ledge | 51,41,32 / 61,44,29 | 51,42,35 / 61,45,32 (warm windows kept) |
| ste 22:00 classic (shot_340/355) | luma 28 | luma 28, 0.75 % of pixels differ (sprite flicker) |
| siren, bil 47.5,74.5 19:30/23:00 first person (frn7_o2b, frn7_o2c), S0 and S2 | a red/blue disc with a cross right of the roof in every quads-on frame | no disc in any frame; a small red or blue cap on the light bar, alternating; third person: the red/blue dot no longer floats above the roof, the cap sits on the bar |
| siren with VEHICLE-ART-15's authored 012 (a red and a blue dome on the bar; frn7_o2d, rebased build) | the disc above the bar | the cap glows on the top of the red dome, then the blue one (`caps at x -0.098 / 0.098` in the log); cap 0: both domes unlit |
| order 1 re-taken on the rebased build (frn7_v2 shot_135/155, 205/215) | road 41,42,33 | road 41,46,46, pool 58,41,28; classic identical |
| plain GL, same pose (frn7_pl1 shot_070/090): beacon region max difference, quads on vs off/cap 0 | | 1 of 255 (the plain draw is untouched) |

Not changed: the grey "bubbles" rising from the siren car in first person stay with `remix_puff_mode=2` (frn7_o2b
shot_250/255) and with the quads off, so they are not our puffs nor the beacon draw (still open on the siren order).

Still short of a shipping frame: the moon fill is one overhead distant light, so the shade has no sky gradient
or moon direction and the far facades stay dim slabs; the asphalt's own green-yellow albedo still reads olive inside
the sodium pools' outer ring; the beacon cap is a flat eye-facing disc (no lens refraction, no rotating reflector),
and the cap was filmed on the 012 cop car only: on a body without a distinct top part (`car bodies: Remix beacon
cap for <model>: none` in the log) no cap is drawn, only the siren lights; the ambulance, fire truck and SWAT van are untested.

### FIX-REMIX-NIGHT-7 order 3: Downtown's rooftop sign plates floodlit at night (prx2, night half)

The round atom sign the filer saw from wil 167.5,21.5 is one of the flat, double-sided sign plates standing on wil
rooftops (tiles 62/63 the atom disc, 61 FUTURO RADIO; 24 faces, 11 not against a solid neighbour). They have no map
light and no emissive, so at night under Remix the disc was a dead grey-brown. Each such face now gets a small warm-white
(1, 0.88, 0.70) floodlight at night (the lamps' clock), half a tile out from its plane on its own side and 0.3 below its
middle, aimed back at the plate (50 deg cone, 0.08 emitter), through the lit-window list (`BuildWindowLights`,
nearest 40 within 18 tiles); street views and Remix only. `[devtools] remix_sign_flood_pct` (100; 0 = off).

| check (wil 165.5,17.5 disc from a fixed camera at 167.0,21.0, 20:00; frn7_x2, then frn7_x3 on the pushed build) | off | on |
|---|---|---|
| disc mean RGB (patch in the disc) | 61,52,32 (luma 53) | 25 %: 71,60,35; 50 %: 78,66,37; 100 % of the 6.0 trial: 91,78,45; 200 %: 114,99,59; shipped 9.0 between |

Not changed (a material item, note beside the order for FIX-REMIX-MATERIALS-7): the noon cream clipping and blur of the
disc, and an emissive mask for the atom lines. Still short of a shipping frame: the sign is lit from outside like a
floodlit board, not glowing; the plates on other districts are not covered.

## FIX-REMIX-NIGHT-8 (10 Nov): the first-person fists and the night fills

### Order 2: the first-person player fill (prem1)

The night player fill (`PlayerFillSubmit`, live_geometry.cpp) slides 0.9 tiles toward the eye in the street views, but in
first person the eye *is* the old spot, so the sphere stayed 0.2 tiles over the view model's fists (0.3-0.4 away). Now it
goes where the third-person boom would put it: 0.85 tiles behind the eye and 0.3 up (`[devtools] remix_fill_fp_back_milli`,
default 900, 0 = the old spot). Third person and classic are unchanged.

Same session, wil 164.5,149.5, 21:00 paused, first person (out frn8_f2; fist box / road box mean sRGB):

| state | fists | road |
|---|---|---|
| shipped before (`remix_fill_fp_back_milli=0`) | 97,66,54 | 27,40,52 |
| this change | 74,53,49 | 26,39,51 |
| player fill out (`remix_fill_pct=0`) | 70,50,45 | 26,39,51 |
| player fill and night fill out (`remix_lights_probe=256`) | 55,33,20 | 15,16,13 |
| all our lights out (`remix_lights_off=1`) | 4,4,4 | 2,4,5 |

With the change the player fill adds about 4 of the fists' 74: they are lit by the street lamps (55) and the moon fill,
like the street. What still reads as "orange" is the arms' own albedo: tools/gen_weapons.py `SKIN = (178, 128, 98)`
(linear about 0.45, 0.22, 0.12), brighter and more saturated than the asphalt (about 0.1) a hand-height surface shares
the light with. That is the figure/asset seat's (FIX-FIGURE-11 made those textures), noted beside the order.

### Order 1: headlamp beams that reach the road (prxr1, beam half)

Measured first (out frn8_h1, h4, h5: the scene van 068 seated and stopped at wil 198.5,188.5, 22:00 paused, fixed
REGRESS_CAM cameras at eye height 3 tiles out, high over the road, and low beside the bumper):

- The white lamp discs are the **model's lens material** (the `head` emission of tools/remix_model_pbr.py: the lens
  texels' own white x `HEADLAMP_INTENSITY` 3): they stay with every light of ours out (`remix_lights_off=1`) and with
  the body's additive lamp glows out (`remix_car_lamps=0`). Not the emitter.
- The missing pool had two causes. (1) No beam at all: the game leaves a stopped car's lamp bits at 0 even with a driver
  in it (`headlights: nearest car ... occupied 1 mask 00000000`), and the beam waited for those bits; moving the emitter
  (`[Headlights] Lead` -0.188 .. +0.20 live, h1) changed nothing because nothing was submitted. (2) Where a beam was
  submitted, its emitter sat 0.188 tile behind the sprite's lamp pixel and 0.24 up: inside a 3D bonnet, which swallowed
  the cone and let a few slits of light out under the bumper.

Street views now (`[devtools] remix_beam_mode`, default 1, 0 = before): a car with a driver casts its beams at night
whatever the game's bits say (a front corner's dent still breaks its lamp), and the emitter sits 0.03 tile ahead of the
body's nose at 30 % of its height (CarBodiesExtent), or, for a body that records no extent, 0.03 ahead of the sprite's
front edge at 0.15. The classic view keeps the game's bits and the old place.

frn8_h5, same session, old -> new (mean sRGB luma): road ahead of the bumper at the low camera 76 -> 144 (a warm pool
158,143,114), at eye height 3 tiles out 73 -> 121; the paving beside it 71 -> 75 (unchanged). Probe keys:
`remix_car_lamps` (car_lamps live), `GTA2DX9_LOG_HEADLIGHTS=1` (nearest car's driver/mask/body, each headlight near the
eye as given to Remix).

Still short: the lens is a flat white disc (material: emissive 3 over the whole lens island, no core/rim; for the
materials seat, beside the order); the beam is one cone per lamp with no high/low beam shape.

### Order 5 (plain renderer, `[weather] enabled`): car bodies take the night (qav1)

The 3D car bodies were lit by their own fixed sun 0.78 and ambient 0x5A at every hour, so with the weather/time-of-day on
a police car at 22:30 was brighter than in daylight rain. car_bodies.cpp now scales that sun (diffuse and specular) and the
ambient by `FigureTimeOfDayLight` (the ptm14 factor the figures and pickups take): exactly 1 by day, with the sky off or
under Remix; 0.26,0.28,0.33 at 22:30. `GTA2DX9_CAR_NIGHT=0` = before. bil spot 0 (keys_qav1.sh, out frn8_q0 before /
frn8_q1 after), car region luma p50/p90: 22:30 clear 34/234 -> 17/67 (wall 45, ground 29), day rain 32/132 both.
Headlamp quads and beams are unchanged (they are the car's own light).

### Order 5 (plain renderer, `[weather] enabled`): the headlamp pool starts at the bumper; wide sign lights stop flooding

- qav1 detached wedge: the plain head-lamp pool (vehicle_fx.cpp, `g_coneTex`) faded in over the first tenth of its 2.6-tile
  reach, so 0.26 tile of dark road separated the bumper from the light. It now comes up within 0.05 tile.
  `GTA2DX9_CONE_NEAR_OLD=1` = before. bil police car 22:30 (out frn8_q1 before / frn8_q2 after, framing differs between the
  runs): the beam is bright at the bumper instead of fading in ahead of the nose.
- qav1 ste lime flood: identified as the map's own light at ste 99.5,96.5,3.5, #80FF00, radius 4, full intensity (the
  plain pass makes it a 5.4-block light plus a ground pool). In the street views a wide (radius >= 3) neon-class map light
  (ClassifyGameLight Neon; sodium lamps never) keeps 30 % of its hue over a warm white of the same luminance, as Remix's
  wide-neon rule does (visuals.cpp). `GTA2DX9_WIDE_NEON_OLD=1` = before. ste spot 0 (out frn8_n0 before / frn8_n1 after),
  pavement/road box mean: 22:30 42,91,23 -> 63,87,56, dusk 44,71,23 -> 67,90,55, day fog 45,52,51 -> 45,53,52.
  Still short: the light still reaches across the street (a bounded pool at the shop front would need the reach cut too).

## FIX-REMIX-NIGHT-9 (10 Nov): texture streaming without sampler feedback (prx1)

`package/rtx.conf` and `linux/docker/rtx_play.conf.extra` (and the live `gamerun/rtx_play.conf.extra`) now set
`rtx.texturemanager.samplerFeedbackEnable = False` and `rtx.texturemanager.neverDowngradeTextures = True`.
With sampler feedback on, the runtime streams each replacement texture only to the mips the GPU sampled, so a
small prop a few blocks off (the stop sign's 256 px face) stayed on an 8-16 texel level: a blurred red disc,
STOP a smear (FIX-WORLD-12 found it at bil 60.5,150.5; its A/B out of `fw12_prx1_rmx` / `rmx2`).

Second A/B pair (fixed cameras, `gamerun/frn9_cams.py` via `rn_remix.sh`, wil stop sign 167.9,127.5 at 21:00,
cameras 1 and 3 blocks off, GPU 3, same stage, only the config differs): shipped = soft octagon, smeared rim and
letters at both distances; new = crisp octagon, white rim, sharp STOP. Cost over the same probe window: 43.7 vs
42.8 ms per frame (noise), VRAM peak 6.25 -> 6.75 GB (median 5.1 -> 6.0 GB) of the L4's 23 GB. The classic view
under Remix takes the same runtime option: its frame at the same moment differs by mean 5/255 in a static region
(3.6 % of pixels over 16), less than two frames of one take differ (path tracing is not byte-repeatable); no
texture in it changes visibly.

## FIX-FX-6 (10 Nov): soft blended smoke instead of cut-out wisps (owner10nov-1 "feathers / milk")

The owner saw the cars' smoke under Remix as opaque white torn-paper cut-outs ("feathers" moving, "milk" stopped):
`remix_puff_mode=1`, FIX-REMIX-NIGHT-5's coherent wisps, which are an alpha-tested cut-out with a binary edge. The
operator's stopgap shipped mode 2 (no puffs at all under Remix, ae01afd6).

| Change | Where | Switch |
|---|---|---|
| Remix puff mode 4 (the code's default and the shipped ini value): every vehicle_fx puff (tyre smoke, steam, exhaust, a hurt or burning engine's smoke) is an alpha-BLENDED camera-facing billboard (SRCALPHA/INVSRCALPHA, no alpha test, no z write); its texture holds the density, thinned by a coherent noise more at the rim than in the middle (billows), times the opacity step, the grey tone baked into the texels as FIX-FX-5's wisps (Remix drops vertex colour). Light puffs: a Gaussian core reaching 0 at the quad's edge, x0.35; mid and dark smoke: the puff's wider lumpy disc, x0.8 / x1.0 (thinner, a burning van showed no plume at all: fx6_r5..r8); 8 steps x 3 tones of 128 px, fixed content | `vehicle_fx.cpp` `PuffSoftReady`, `g_puffSoftTex`, `kPuffSoftGain` | `[devtools] remix_puff_mode` 4 / 1 wisps / 2 none / 0 dither / 3; `GTA2DX9_REMIX_PUFF_SOFT=0` turns 4 into 1 |
| Under Remix with mode 4, the shot smoke particles (kind 3: the rocket's backblast cone, gun and flame smoke) go to the same puffs instead of `ShotGlowTexture` (its falloff in the colour at near-full texture alpha, the vertex alpha dropped: a shaded chrome/glass ball, ffx5 5w3) | `live_geometry.cpp` `ShotSpawn` -> `VehicleFxEmitPuff` | `GTA2DX9_SHOT_SMOKE_REMIX_OLD=1` |

What this runtime does with a translucent puff (one Remix session each on the L4, a forced burn of the parked 068
van at wil 198.5,188.5 plus `spawn_smoke=1` beside the hero, 13:00 and 22:00, fixed cameras, the mode switched live,
runs fx6_r1..r5):

| Draw | Frame |
|---|---|
| mode 1 wisps | white (noon) / blue-grey (night) flakes with hard edges: the owner's picture, reproduced at the hero pose |
| blended, textures listed in `rtx.particleTextures` (the runtime's particle path) | soft but BLACK blobs at noon and night (fx6_r2 `a`): the particle path is not lit here. Not used; the textures' hashes are logged (`vehicle fx: soft puff texture ... 0x...`) for the same test on a stronger GPU |
| blended, untagged (mode 4) | lit, soft billows: white-grey tyre smoke and steam at noon with the road marks through the thin haze between the dense cores, a soft moonlit haze at night, a dark cloud over the burning van; no cut-out edge, no flakes, no bead column (fx6_r4 `a`, fx6_r5 `a`) |
| blended at x0.22 / x0.14 opacity | the stacked cores darker, hardly thinner (fx6_r3): the runtime's opacity response is steep, so x0.35 for light puffs |
| final (fx6_r9, after the rebase): mode 4 vs mode 1 in one session | hero pose 13:00 and 22:00: soft grey puffs with the road through the thin haze (mode 1: white flakes); third pose over the burning van: a soft dark plume off the roof at both hours (mode 1: grey flakes); eye-height pose 2.4 blocks off the van: NO plume in mode 4 (mode 1 shows a flake column): still open |
| added (ONE/ONE) with the light baked in, x1 / x2.5 | black / dark grey balls (fx6_r5 `b`, `c`): additive smoke is not lit either |

Frame time on the L4 (Medium, path traced): 70-95 ms a frame in every mode, no difference beyond the run's noise. The
5090 proof (the owner's GPU) is the operator's. The classic view does not draw these puffs (street views only).

Plain renderer: unchanged (it always drew the puffs blended with a soft disc; a burning van's plume is a soft low-contrast
veil, no hard edge, fx6_p4).

Found on the way (fire-fx 3d2, no flame tongues on a burning car): the van shows no flames in the plain renderer either.
The game's flame sprites (base 8, 402-407, at the van's front) never reach the fire-spot code in `live_geometry.cpp`
(no effect sprite near any car in the log after the burn), so no tongues and no fire plume are spawned; the warm pool
under the car is the synthetic fire light. Still open.

Still short of a shipping frame: the burning van's plume does not show from the eye-height pose under Remix (fx6_r6..r9,
cause not found: not the particle pool, not the texture build); dense plumes stack into a dark ball with a visible lumpy outline (the steep opacity
response); no self-shadowing or volume; Remix's own volumetrics fed with an emitter would be the AAA answer.

## FIX-FX-7 (10 Nov): flames on a burning car drawn as a 3D body; no bead column in the plain renderer

**Flames on a burning 3D car (fire-fx 3d2).** FX-6 found that a burning car showed no flame tongues and no fire plume
in any renderer. The cause: the fire-spot code in `LiveGeometry::Draw` tests the game's flame sprites (code object
8:402-407, laid over the engine) against `roofs`, which is built from the dome shells (`shells_`). A car drawn as a 3D
body has no dome shell, so `roofs` was empty for every car within the 3D-body distance. The flames were drawn as flat
sprites inside the bonnet, and `SpawnFlames` / `SpawnFireSmoke` never ran. The warm ground pool came from the synthetic
fire light (`g_fireSpotsLast`), which is published before that test.

| Change | Where | Switch |
|---|---|---|
| A flame sprite over a drawn 3D body (its footprint from `CarBodiesFootprints`, 1.25x its half extents + 0.05) is a fire spot of that car. Its height comes from the cabin (`CarBodiesCabin`: the bonnet ahead of the windscreen's base, the roof behind it), else 0.8 of `CarBodiesExtent`'s height. The game sprite and its layers stand with their foot 0.12 into the body (they hovered a hand over the roof, fx7_f2). Tongues and smoke spawn 0.08 over the top. The dome-shell cars are unchanged | `live_geometry.cpp` (`fireFeet`, `overCar`, `overTop`) | `GTA2DX9_FIRE_BODIES=0`: the old way |

Probe: `gamerun/keys_fx6_fire.sh` (fx6_fire.py), parked 068 van at wil 198.5,188.5, force_burn, fixed cameras (needs
`-e 'GTA2DX9_REGRESS_CAM=Z:\tmp\va2_cam.txt'`, otherwise every pose is the chase view). POSES
`third:-1.2:1.3:0.85|eye:0.9:-1.0:0.40|eyefar:2.2:-2.6:0.45`. Night in the plain renderer needs
`INI_SED='/^\[weather\]/,/^\[/ s/^enabled=0/enabled=1/'` plus `SETTINGS_SED` StartHour=22 Paused=1 (`set_hour_tenths`
alone leaves the plain picture in daylight).

| Run | Frames (opened) |
|---|---|
| fx7_f3 (13:00) | third: flames rise out of the van's roof with a dark smoke plume above. Eye-height 1.3 blocks off: the fire on the roof at the top of the frame and an orange glow through the side glass. Eye-height 3.4 blocks off: the fire on the roof and the warm pool under the van |
| fx7_n5 (22:00) | the same at night: an orange fire on the roof in all three poses, a grey plume against the night sky, the pool on the ground kept |
| fx7_n4old (22:00, `GTA2DX9_FIRE_BODIES=0`) | no flame anywhere on the van, only a pale veil (the old picture) |

Still open: (1) at night, the cab's side window of the burning 068 van shows a pale lit blob. It is present with
`GTA2DX9_FIRE_BODIES=0` too, and moving vehicle_fx's engine smoke out of the cab did not remove it (tried, not
shipped), so it is most likely the cab interior lit by the fire light. (2) Remix take on the live rig: see the work
order. (3) The game's flame sprite is a single billboard over the middle of the body. Flames licking out of the
bonnet seams and wheel arches, as a shipping game would show them, would need emitters on the model.

**No bead column in the plain renderer (qav38 / qav52).** The game's tiny smoke specks (code object 8/322, under 0.06
block) are drawn 1.35x as soft discs (`g_gamePuffs`). In the street views that is still a 3-8 px bead, and an emitter's
stream reads as a ruler-straight dotted column (bil 150.5,200.5: 8 of 8 third-person headings, QA-VISUAL v52). FX-5
(05e2eb1e) left them out under Remix only. The plain renderer's street views now leave them out too. Classic never
reaches this branch. `[devtools] remix_game_specks=1` draws them in both renderers (live A/B).
`GTA2DX9_GAME_SPECKS_OLD=1` brings them back in the plain renderer only.

Bead column A/B (the filer's qav52 repro, `gamerun/qa_run.sh <name> 600 qav52`, bil spot 3 = 150.5,200.5, 16:30, plain GL,
private stage of f739e435): with the change, no bead line in any of the 8 third-person headings (qa_fx7_qav52). With
`GTA2DX9_GAME_SPECKS_OLD=1` (qa_fx7_qav52old), heading 0 shows the filer's picture again: a ruler-straight line of pale
beads rising from a small red mark on the paving.

**Rocket backblast under Remix (ffx5 5w3), checked at a nearer camera.** FX-6's routing (64c1eb2b: shot smoke into the
mode-4 soft puffs) was re-shot with the fixed camera 1.5 tiles to his side instead of 2.2 (rn_remix + keys_ffx5_specks.sh,
wil 154.5,129.5, 12:00, `CAMD=1.5`). On every launch the backblast is a soft smoke cloud that starts at the tube's rear,
stretches back over about a second and is gone by frame 22, with no glass or chrome sphere (fx7_bb1). A denser tone
(the shot smoke in the soft puffs' mid tone) was tried as a live A/B and looked the same, so it was not shipped. Still short:
under Remix the cloud is near-black soot rather than grey-brown dust (at either tone), has path-tracer grain inside, and
casts a dark shadow on the wall.

## FIX-FX-8 (11 Nov): a burning car against a wall; the backblast under Remix; tongues from the seams

**qav79: wedges in first person, a detached column in third (commit ba9d1992).** The filer's car caught fire nosed
into the wil wall corner (111.6,109.4). Same-pose A/B with the live `[devtools] fire_ab` mask named both halves:

| fire_ab | What is left out / changed | First person at the wall |
|---|---|---|
| 0 | nothing (the shipped picture) | soft flame blobs over the bonnet |
| 1 | the game's flame sprites over cars | unchanged: they were not the wedges |
| 4 | first person's own-car bonnet tongues (`g_ownFire`) | every flame gone: the wedges are these tongues |
| 32 | the tongues' depth test | old spawn: the straight edges go (the wall's depth cut them) |
| 128 | FIX-FX-8's depth pull only | new spawn: straight cuts again |
| 16 | all of FIX-FX-8 (also `GTA2DX9_FIRE_ANCHOR_OLD=1`) | the filed V-wedges |

- First person: the bonnet tongues spawned 0.52 block ahead of the car's middle, which is past the nose of a short
  car, so with the car nosed into a wall they stood inside it. They now come off the drawn body (`CarBodiesFootprints`
  + `CarBodiesCabin`): at the nose, 0.10 inside it, at least 0.30 ahead of the eye, 0.22 over the road. The cabin's
  `deck` is the sill line at eye height, so tongues spawned there started at the horizon (run fx8w3). Every tongue is
  drawn 0.15 block nearer the eye **in depth only**: `D3DRS_DEPTHBIAS = P43/(w-0.15) - P43/w` at the tongue's own view
  depth `w` (the street views' projection has `_33 = 1`, `_43 = -0.05`, an infinite far plane). A wall just behind a
  tongue no longer cuts it, while the cab, the wheel and anything 0.15 in front of it still hide it. Tongues fade out
  over their last 0.3 block before the eye. The game's flame sprites over the car he sits in are left out in first
  person.
- Third person: the game lays its flame sprites off the car it knows, and the drawn body can sit apart from that (the
  draw-only separation pushes it off a wall). In the filer's log the flame was at along -0.16 of 0.42 and across 0.25
  of a 0.19 half width, i.e. past the roadster's side and behind its windscreen. The spot is now anchored on the drawn
  body: spread over the bonnet (from the windscreen base + 0.04 to the nose - 0.08) where the body has one, inside the
  body where it has none (a cab-over van burns on its roof, as FX-7 shipped), and never wider than 0.6 of it. The game
  sprite and its layers move with the spot.
- Probes: `gamerun/fx8_wall.py` (`qa_run.sh <name> 240 fx8wall`, `SEQ=first:0,16,...|third:...|classic:0`) steers
  the scene car into the wall corner and sets it alight with `force_blast_car=driven` (new: `force_burn` on the car he
  sits in). `GTA2DX9_LOG_FIRE=1` logs each car flame (centre, size, eye distance), the own bonnet spawn and the depth
  pull.

| Run | Frames (opened) |
|---|---|
| qa_fx8r1 (rebased ba9d1992, 23:00, model 0) | first: new soft, old (16) straight cuts; third: new on the bonnet, old a column up and left of the car; classic reference |
| qa_fx8n2 (12:00, model 50) | first: old = the filed V-wedges, new soft; third on the bonnet |
| qa_fx8w5 (23:00, model 50) | old / no depth pull (128) / new in one run: only the new one has no straight edge |
| qa_fx8w2, w3, w4 | the 069 truck, 056, 000 at the same corner |

Classic: vreg `spawn_classic` PASS, 0 of 144 tiles. Still open: the filer's open roadster 036 never came up as the
scene car; at noon the additive first-person flames wash the windscreen near-white.

**Seam tongues (FX-7's residual: one plume over the body).** A burning 3D body also sheds smaller tongues (half the
size, a third of the plume's rate each) from both front wheel arches (just outside the body, at the arch's top) and
the bonnet's rear seam under the windscreen where it has a bonnet. `GTA2DX9_FIRE_SEAMS=0` or `fire_ab` bit 256 = the
one plume. Run fx8s1 (fx6_fire.py, the 068 van parked at wil, fixed side/front/third cameras, 13:00 and 22:00,
`AB_SETS=seams:fire_ab=0|one:fire_ab=256`): with seams the near front arch burns under the cab beside the roof plume.
Without them only the roof plume burns. The far arch is hidden by the body, as it should be.

**ffx5: the rocket's backblast under Remix (not closed).** The backblast's 14 kind-3 puffs go to vehicle_fx's soft
puffs (FX-6). `GTA2DX9_LOG_FIRE=1` shows they are drawn (28 quads with the rocket's trail, alpha up to 0.34). They were
in the light tone, whose opacity is x0.35, and no backblast was visible at noon (out/fx8_bb5, out/fx8_bb6 "old"). They
now take a new soft-puff tone 3, "dust" (texel grey 0.92, opacity x0.8; tones 0-2 keep their textures and hashes):
a cloud now shows behind the tube on every launch. At the probe's spot (a building's shade), the dust and the mid
tone (0.55) are equally dark, so the soot look comes from the path tracer's lighting of the puffs, not their albedo.
`[devtools] backblast_tone_old` = 0 dust (default), 1 the old light tone, 2 the mid tone (`GTA2DX9_BACKBLAST_TONE_OLD=1`).
Probe: `KEYS=keys_fx8_bb.sh gamerun/rn_remix.sh <name> 600 wil 12 "154.5,129.5,3" -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\va2_cam.txt'
-e CAMD=1.5 -e AB_SETS=...`. Without the regression camera every "fixed" pose is the chase view from behind him.

## FIX-FX-9 (11 Nov): the fire truck's water jet in the street views (qaexp65)

**What the game draws.** The 017 fire truck's cannon (Ctrl) is a string of code-object sprites **8:417-431**, one per
drop, the number its age (texture 4x32 growing to 16x28, flags a280, additive, mean colour 718e88 for 417 darkening to
061810 for 431), lying flat on the road ahead of the cab: classic shows a long teal stream. Where it lands the game
adds a splash, **8:437-450** (grey-teal, mean 7b857f..0c120e), which it lifts off the road itself (2.1 -> 2.7 -> 2.0).
Found with `GTA2DX9_LOG_SPRITE_KINDS=1` + `GTA2DX9_LOG_FX=1` (run qa_fx9h1) and the new `hose: kind` lines of
`GTA2DX9_LOG_FIRE=1` (they print each kind's mean colour once).

**Why the street views showed nothing, a green dot or flames.** A flat strip on the road is edge-on from a street
camera. Worse, the effect classifier (black fading to a cut-out edge = fire) takes most of these frames for fire art.
The drops over the truck's own footprint then went through FX-7/FX-8's fire-over-a-3D-body path: anchored onto the
bonnet, given the flame layers and the fire tint: the orange bursts out of the cab (`fire: flame over 3D body` lines
on an unburnt truck, 24 in qa_fx9h1 and qa_fx9h2).

**Now (street views only; classic is untouched).** Each drop is three soft puffs (`g_gamePuffs`, blended, not
additive) along its own length at the game's x/z. The height comes from the drop's age `t = (n-417)/14`: from the
roof of the drawn 017 the stream comes from (`CarBodiesFootprints` + `CarBodiesCabin`, the nearest 017 whose nose the
drop is ahead of; 0.75 block over the road when none is drawn), lobbed up to 0.4 block over the cannon a third of the
way out, then down onto the road where the game's last drop lies. They are 0.13 -> 0.33 block wide, alpha 0.55 -> 0.30,
in a pale lit teal (150,226,212: the 417 frame's hue; the later frames' means are darker because the art is additive,
not another colour). The splash 8:437-450 is a soft puff of the same water colour at the game's own 3D position. Neither
kind is ever a fire spot. `GTA2DX9_HOSE_OLD=1`: the old way.

| Run (ste truck at 229,123, noon, plain GL) | Frames (opened) |
|---|---|
| qa_fx9h1 (HEAD 240e3d2b stage, the old way) | third parked: a small green glow over the cab, no stream; first: a teal glow; third after the moving truck noses into the fence: orange flame bursts on the cab and a white-green ball at the front wheel; 24 `flame over 3D body` lines |
| qa_fx9h5 (this change) | third parked: a teal stream rising over the cab and on ahead; fixed side camera: a lobbed teal arc from the cab roof onto the grass 3 blocks ahead; first: the stream rising past the windscreen's top and falling ahead; moving: the same, no flame; 0 `flame over 3D body` lines, 0 FAULT |

Probe: `gamerun/fx9_hose.py` (`QA_DISTRICT=ste ... QA_ENV="-e GTA2DX9_STATE_EVERY=3 -e GTA2DX9_LOG_FIRE=1
-e GTA2DX9_REGRESS_CAM=Z:\tmp\va2_cam.txt" gamerun/qa_run.sh <name> 220 fx9_hose`; `FX9_TRUCK=0|1` picks the ste truck,
`FX9_SIDE=0` skips the fixed cameras). Untested: Remix (the blended game-puff pass is alpha-tested at 1, not the
mode-4 soft puffs), the wil truck, night, 1440p, a burning car or ped being hosed.

**First-person flames at noon (FX-8's qav79 residual).** At the wheel of a burning car at noon the additive bonnet
tongues washed the windscreen near-white: a tongue near the eye covers much of the screen, and a few added over a
bright day saturate. In first person a tongue within 1.4 block of the eye is now dimmed, down to 0.4 of its level at
0.3 block (smoothstep over 0.3-1.4), and keeps its orange (its green falls to 0.7, its blue to 0.45 at the eye), so the
street reads through the fire. `[devtools] fire_ab` bit 512 = the old brightness (live A/B). Run qa_fx9w1 (wil wall
corner, `gamerun/fx9_wall.py` = fx8_wall.py + a `MODELS` list (`MODEL_KEY=force_own_car_model` default, or
`force_car_model` for the third-person body), 12:00, `SEQ=first:0,512,0|third:0`, own car forced to 036, 031, 063):
with 512 the filed white-yellow blobs over the wall; without it the same tongues orange, the brick and windows
readable through them, on all three cabs.

**ffx5, the rocket's backblast under Remix: measured, not fixed (released).** Remix play rig, 12:00, puff mode 4 in the
log, FX-8's dust tone (240e3d2b), probe `gamerun/fx9_bb.py` (fx8_bb.py plus `SPOTS` warps with a game-camera settle;
without the settle the hero is not drawn yet after a long warp). At FX-8's spot (wil 154.9,127.6, run fx9_bb1) the
launch flash lights the wall, and the dust puff behind the tube shows as a pale grey-white soft disc for that one
frame. Then the puff itself is not seen, and a dark smudge spreads on the wall behind him: the cloud's **shadow**, cast
by the rocket's own light as it flies off. That is most of the "soot" FX-8 saw. At a sunlit open street with nothing
taller than the ground within 3 blocks (wil 172.7,131.7, run fx9_bb2) the backblast is a faint grey haze on the road
behind him for about 0.3 s: grey, not soot, but too thin to read as a cloud. Since the albedo makes no difference (FX-8:
0.55 = 0.92), the untried next steps are a small emissive lift on the tone-3 puffs (a Remix mod material on the hashes
`vehicle fx: soft puff texture step N tone 3` logs, or Remix-API meshes with their own non-shadow-casting material,
as `LampMaterialFor` does for lamps), then a denser tone 3 judged at the sunlit spot.

**Grainy Remix fire at a distance (FX-7/FX-8's open item): measured.** Remix play rig, 13:00, the 068 van burning at
wil 198.5,188.5, fixed camera 8 blocks behind and 3 to the side (`fx6_fire.py`, `POSES=far:-8:3:1.6`), live
`fire_ab` A/B in one session (run fx9_far2; fx9_far1 adds a 3-block pose). All on: a dark stippled cloud with an orange
core over the van. Tongues off (`fire_ab=2`): the same stippled cloud. Smoke off (`fire_ab=8`): a soft orange-brown
fireball with no grain. So the grain is the **smoke** (the mode-4 soft blended puffs, a regular stipple of their
translucency on this Wine rig with no NGX denoiser), not the flame tongues. Whether DLSS-RR resolves it is the owner's
5090 test (NEEDS OWNER 40); on our side, fewer, larger, more opaque far puffs would also reduce it (untried).

## FIX-FX-10 (11 Nov): effect sprites that lay flat in the street views

**Electro gun bolt (qaexp76).** The game draws the bolt as a chain of code-object segments **8/480-495** (12x32 texels,
a quarter block along the aim line; four frames of four styles; additive), laid end to end on the ground from the
shooter to what it hits and on to the next target. Classic shows it as a short zig-zag along the aim line. The effect
pass stood each segment up like any flame (`UprightPedMatrix`), so every quarter block became its own short column on
the paving. From a chase camera the columns stacked into ground-cut zig-zags with square haze edges, which is what the
filer saw. In first person the same columns stood on the target. Now each segment keeps its long axis along the line it
lay on, is lifted 0.30 block (the figure's gun height, as the bullet streaks), and is turned about that axis to face the
eye (`ElectroRibbonMatrix`). The chain reads as one arc from the rifle to the target in third person, and as a strike on
the target in first person. The segments are also not dropped beside the shooter (`fxAtShooter`), so the arc reaches his
hand. They are never fire spots either: over a car the fire path enlarged and stacked them into a purple-white column
above the roof. `GTA2DX9_ELECTRO_OLD=1` gives the old drawing (A/B). The classic view is untouched (the effect path runs
only in the street views): vreg `spawn_classic` 0 of 144 tiles.
Runs: qa_fx10_e1 (old, sprite kinds), qa_fx10_e4new / qa_fx10_e4old (same probe `gamerun/fx10_electro.py`, noon, A/B),
qa_fx10_e5night (23:00). Still short of AAA: where the chain bends, adjacent segments leave small wedge gaps and seams at
the joins (square segment ends). Remix is untested.

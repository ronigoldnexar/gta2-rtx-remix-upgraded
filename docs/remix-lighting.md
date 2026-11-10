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

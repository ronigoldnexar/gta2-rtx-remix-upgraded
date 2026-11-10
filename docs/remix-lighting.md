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

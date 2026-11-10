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

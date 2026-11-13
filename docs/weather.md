# Weather and time of day in the plain renderer (QB-35, QB-43)

> **Status (9 Nov, QB-35-WEATHER): implemented, OFF by default** (`[weather] enabled=0`).
> Verified in the running game on a private stage, see "Verification" below; open items at the end.

The play page's plain Direct3D 9 renderer had one fixed late-afternoon sun (`[sky] follow_clock=0`)
and no weather at all; night and rain only existed under RTX Remix. This adds both to the third-
and first-person views. The classic top-down view is never touched (every effect is weighted by the
view transition and the renderer only applies it with the street shading on), and on an RTX Remix
device none of it runs (Remix has its own sky; the renderer skips the weather there).

## What it does

| Part | How | Where |
|---|---|---|
| Time of day | With `[weather] enabled=1` and `time_of_day=1` the street views' sun follows the `[timeofday]` clock (the one that already drives Remix's sun: real solar geometry, latitude 40, equinox). The sky's golden hour, violet blue hour, navy night and stars, the night light pass (lamps, neon, car lamps), the renderer's lit windows and the daylight gate of the synthetic lamps all follow that sun, so the day runs through all of them. `hour_hhmm` sets the clock live, `clock_paused` holds it | `dll/src/weather.cpp` (`ApplyClock`), `src/sky.cpp`, `dll/src/visuals.cpp` |
| Overcast | The dome greyed and darkened with the cover, the sun disc and its light hidden behind it (sun x(1-0.85 cover)), the ambient greyed, the cloud layer thickened to the cover | `src/weather_fx.cpp` `WeatherAdjustSky/Shading` |
| Fog banks | The fixed-function fog pulled in from 18-130 blocks to as little as 1.5-16 blocks, its colour the greyed horizon; the dome fades into the fog. The density at the eye follows a slow value noise over the map (~40 blocks across, drifting with the wind), so the fog thickens and thins as you move through the city | same |
| Rain | Streaks: camera-facing quads (1600 at full rain) in a 18 x 7 x 18 block box that travels with the eye; each drop keeps its place in the world (wrapped into the box), falls at 6-9 blocks/s, slants with the wind, fades at the box edge and right at the eye; alpha-blended, depth-tested, lit by the scene's light (never brighter than the night). Drawn after the cars, people and props, before the post. Rain also shortens the fog and darkens the light | `WeatherFx::DrawRain` |
| Wet roads | A pass in the `[visuals]` post chain after the night lights, before the bloom (`ps_wet`): faces that look up (from the depth normal) darken, and reflect the frame: a 10-step screen-space ray march against the scene's depth, the sky's colour where the ray leaves the frame, a Fresnel term with a floor. Puddles: a tiling noise in world space (1/32 per block) thresholded lower the wetter it is; they reflect most and ripple under the rain (two drifting noise layers bend the reflection). Walls darken a little. Fogged distance is left alone | `src/shaders/weather.hlsl`, `PostFx::Resolve` |
| Wetness | Lags the rain: about 30 s of heavy rain to wet, 150 s to dry after it stops (`wet_percent` forces it) | `dll/src/weather.cpp` `Step` |
| Weather cycle | `cycle=1`: spells of clear / cloudy / drizzle / rain / storm / fog, each about `cycle_minutes`, eased over `fade_seconds` | same |

The wet pass needs `[visuals] enabled=1` (it is part of that post chain); without it the rain,
overcast and fog still work and the roads stay dry.

### Shader

`src/shaders/weather.hlsl`, compiled offline by `tools/build_weather_shader.sh` into
`src/shaders/weather_gen.h` with Wine 9's d3dcompiler (image `gta2-remixbox`; the Wine 10 image of
`tools/build_shaders.sh` is not on the 8x L4 host). That compiler has no `if`, no comparisons and no
loops in SM3, so the march is written out by a macro and `step` is arithmetic (`St`). It also writes
a fresh `def` for every literal in every unrolled step: the first build had 436 constants
(ps_3_0 allows 224) and `CreatePixelShader` refused it in the game. The march's numbers now come
from two uniforms (`cK`, `cK2`): 103 defs, highest constant c112, highest temporary r28 (Wine's
GLSL path allows r31).

### The near-lens seam (qav9, FIX-WORLD-13, 10 Nov 2026)

qav9 filed the wet layer ending in a hard, stepped seam a few metres from the lens in rain, with a
flat dry-looking slab nearer. It was the reflection march's miss fallback: the ten steps grow with
the pixel's distance (`0.15 + 0.03 z` blocks, x1.25 a step), so from the ground just in front of the
lens a ray ends a few blocks out, short of the walls that pixels farther up the road reach; those
near pixels took the flat horizon/zenith colour, and the line where hits gave out was the seam (step
shaped by the march's discrete steps). A ray that ends still inside the frame without a hit now
takes the scene where it ended (the wall or the sky along the same direction), so both sides of that
line sample the same place; only a ray that left the frame gets the sky colour. `cK.z` carries it
(1; `[visuals] debug=64` restores the old fallback for an A/B in one session). Frames: out/qa_fw13wet3
(`*_old` vs `*_new*`, same pose, wil 210.5,100.5 / 70.5,20.5 / 20.5,160.5, rain 100 %, noon):
third person, the reflection runs on toward the lens instead of stopping at a stepped edge; first
person, ripples and reflections reach the frame's edge where there was a flat grey slab. Highest
temporary still r28.

### Ground only, soft, no seam (qav20, FIX-WORLD-14, 10 Nov 2026)

qav20 filed a car stopped at a bil wall right after rain: a hard-edged translucent grey slab over the
wall and pavement and a mirrored ghost of the car under its bumper. Same-pose A/B (out/qa_fw14ab1,
wet_roads 1 vs 0) put it all on this pass; `[visuals] debug=128` now restores the old pass live, so
out/qa_fw14cam3 and qa_fw14cam4 (bil 158.5,144.5, scene car driven into the wall, rain then fog 90)
show old / new / dry at one pose. Three faults, three changes in `ps_wet`:

- **Every face that looked up was a wet road.** A car's boot and roof took the puddle mirror and
  showed the wall through the car (old frames: the coupe's boot pale and see-through, the parked
  car's roof the colour of the wall). Every lid of the map lies at a whole block height, so the
  world height of the pixel (`c10`, view to world y) gates the mirror and the heavy darkening;
  anything at a fraction of a block keeps only a wet wall's light darkening. Ramps (tilted lids at
  fractional heights) lose their mirror too.
- **The reflection was one sharp tap**: a wall's corner continued into the pavement as a straight
  hard edge and the stopped car stood mirrored under its bumper with a legible plate. Four taps
  spread with the reflected ray's length (at least 0.007 of the frame, up to 0.035) soften it, and
  the mirror is weaker: Fresnel floor 0.40 to 0.25, a puddle's gloss 0.85 to 0.70.
- **A hit at the march's far end switched on as an edge.** Hits now fade over the second half of
  the march into the qav9 fallback, so where hits give out there is a gradient.

Frames: in the new column the boots and roofs are solid paint, the ghost under the bumper is a soft
dark smudge without the plate, the wall's reflection on the pavement has no hard corner line. The
qav9 spot (wil 210.5,100.5, out/qa_fw14wil9) still shows the hero and the taxi in the wet road,
softer. Shader: highest temporary r31 (the limit), constants to c147 of 224. Classic view: vreg
spawn_classic 0 tiles (out/vreg_fw14a). Not checked: night rain, first person, Remix (the pass does
not run there).

## Options (`[weather]` in `gta2dx9.ini`, re-read every second)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | 0 | all of it; 0 is the frame as before |
| `time_of_day` | 1 | the street views' sun from the `[timeofday]` clock (0: the fixed `[sky]` sun) |
| `hour_hhmm` | -1 | developer: set the clock to HHMM whenever the value changes |
| `clock_paused` | -1 | 1 hold the clock, 0 run it, -1 leave `[timeofday] paused` |
| `rain_percent`, `cloud_percent`, `fog_percent`, `wind_percent` | 0, 0, 0, 30 | the weather (ignored while `cycle=1`) |
| `cycle`, `cycle_minutes` | 0, 6 | the automatic weather cycle |
| `fade_seconds` | 20 | easing into a new setting (0: at once) |
| `rain_streaks`, `rain_drops` | 1, 1600 | the streaks and their count at full rain |
| `wet_roads`, `reflection_percent`, `wet_percent` | 1, 100, -1 | the wet-road pass; forced wetness (developer) |

Logs: `weather:` lines on every settings change, a status line every 30 s (clock, sun elevation,
rain / cloud / fog / wind / wetness), `weather: wet-road pass ready` when its target is made.

## Verification

Scenario: `linux/docker/weather_look.py` (`gamerun/keys_weather_look.sh`): warp to a Downtown spot,
chase and first-person views on foot, the clock set to 10:00, 17:20 (golden hour), 18:25 (blue
hour, sun -5 deg) and 22:30, each clear / rain / fog; then the roads wetting and drying with no
forced wetness; then weather off and the classic view.

Runs on the 8x L4 host, private stage (`stage_qb35`, the DLL built from fork/camera-modes plus
this change), 1280x720, `[visuals]` medium. Frames in `out/qb35_look3/t_w_*.png` (sheets
`/tmp/qb35/l3_*.png` at the time of writing); run 4 (`out/qb35_look4`) re-checks the lamp pools
and the far puddle fade (`out/qb35_look4`: wet pass ready, no FAULT; the far grain is gone in
`t_w_first_day_rain`; lamp pools not seen, see below). Note the "clear" frames after a rain frame
show drying roads: wetness follows the rain unless forced, and dries over 150 s.

Verified in frame (qb35_look3):
- **time of day**: 10:00 clear (blue sky, sun shadows), 17:20 golden hour (warm low light),
  18:25 blue hour (violet sky, lit windows, car lamps), 22:30 night (navy sky with stars, lit
  windows, head lamps); the log's status line follows the clock (`weather: 22:30 sun -45.1 deg`).
- **rain**: streaks in the chase and first-person views at every hour, slanted by the wind, darker
  grey overcast with heavy cloud, the sun and its shadows gone.
- **wet roads**: the asphalt darkens and reflects the cars, lamp posts, fence and hydrant (the
  taxi in `t_w_third_day_rain`, the van in `t_w_third_golden_rain`, the bus at night in
  `t_w_first_night_rain`); `weather: wet-road pass ready (1280x720)`.
- **fog bank**: at 10:00 with fog 90 % the street closes in to ~12 blocks in a pale grey haze,
  the dome fades into it (`t_w_third_day_fog`).
- **wetting / drying**: with no forced wetness the roads wet within ~30 s of rain and are still
  damp 15 s after it stops (`t_w_wetting_*`, `t_w_drying_*`).
- **off**: `enabled=0` gives back the plain sunny frame (`t_w_off_after`); the classic view is the
  game's own top-down picture (`t_w_classic_after`).
- no `FAULT` in any of the four runs.

Fixed on the way (each seen in a frame or the log first):
- the wet shader was refused twice by `CreatePixelShader` (`D3DERR_INVALIDCALL`): 436 constants
  (see Shader above), then a `dcl_position0` input that wined3d does not accept in ps_3_0 (the
  pixel input struct now carries the texcoord only, as the water shader's does);
- the ini was polled by frame count: under load (15 fps) a scripted change stayed unread for 4 s
  and frames were taken before it applied; now once a second by the clock;
- night head lamps were a blown white-yellow pool across the road (two beams at 0.79 each,
  from the Remix radiance 10): a beam is now at most 0.22 (`dll/src/visuals.cpp`); the frames
  after show readable beams;
- overcast clouds were white: the cloud layer now darkens with `SkySettings::cloudShade`;
- streaks were too faint at first (alpha 0.2, 0.006 blocks wide): now 0.3-0.55 and 0.009 wide;
- grain at 30+ blocks in the wet road (the puddle map minified without mips): puddles and
  reflection fade out between 25 and 60 blocks;
- street lamps lit no pool on the ground (the lamp sits 1.5-3 blocks up and the soft falloff left
  ~3 % on the pavement; the light list in the log has them at r 3-5, i 1): a second, shorter
  light a block under each map lamp was added - **but run 4 still shows no pool** at the lamp
  3.6 blocks from the player (`visuals: light src 0 at 166.50 3.50 103.50 r 5.02` in the
  `debug=32` dump, player at 164.5,149.5 = world z 106.5; `t_w_third_night_clear`,
  `t_w_first_night_clear`). Head-lamp spots from the same pass do show, so the cause is between
  the provider and `ps_light` for point lights; not found yet.

Not verified: the RTX Remix path (the renderer skips the weather on a Remix device by the same
flag the post uses; no Remix run made), the weather cycle (`cycle=1`, code only), the Windows build
(`dll/build.bat` lists the two new files), frame cost (the host ran at load 20-30 throughout; the
wet pass is one full-screen draw with 10 depth taps and the streaks one `DrawPrimitiveUP` of
≤ 9600 vertices).

## Open

- Wind in trees (QB-43's third item): the trees are rule-placed props drawn in
  `live_geometry.cpp` (another subsystem); nothing sways yet.
- Fog banks are one density at the eye (with distance fog), not volumes you can see from outside.
- No splashes or ripple rings on the ground, no wet sheen on the cars' own shaders.
- **Lamp pools (QB-35)**: not achieved, see above; night is dark away from lit windows and car
  lamps, the blue hour reads best. Next step: log `ps_light`'s inputs for one map lamp
  (`[visuals] debug=32` already dumps the provider's list).

### Covered floors (qav28, FIX-WORLD-15, 10 Nov 2026)

The Downtown plaza's grates (wil lattice lids 193/196 over the pit floor 608 a block lower) showed pale sky-blue and brown
blobs in their holes whenever the pass ran: the pit floor is a ground lid at a whole block, so it took the puddle mirror,
and its rays went up into the grate and came back as the sky fallback or a far wall. `ps_wet` now projects the point
0.95 block above the floor pixel; when the depth drawn there is within 0.30 block of that point's depth, something covers
the floor (a grate, a deck, a gantry) and it keeps the wet darkening but no mirror. The open street is unchanged (same-pose
diff out/qa_fw15c: only the walking peds differ outside the grates). `[visuals] debug=256` = the test off (live A/B). To
stay at r31 the sky test re-reads the depth at the end instead of holding a temporary through the march. Residual: a
floor point whose projected point falls in a grate hole (17%) still mirrors, so a few pale specks remain far off.

## FIX-WORLD-16: contact shadows take the fog (qav64, 10 Nov 2026)

The contact-shadow pass (`dll/src/live_geometry.cpp` `DrawContactShadows`: the soft patches under cars, tyres,
peds and placed props such as lamp posts, signs and shelters) set `D3DRS_FOGENABLE FALSE`. With `fog_percent`
50-90 the fog end comes in to 12-40 blocks, so a distant object faded into the haze while its patch stayed at
full black and hung as a dash above the road (QA-VISUAL v64). The pass now keeps the fog the world pass leaves
on for the live geometry (its colour and linear table start/end). The patch's black is fogged toward the fog
colour at its depth and then blended by its alpha over the already-fogged ground, which works out to exactly the
fogged, shadowed ground: `a(F f) + (1 - a)(g(1 - f) + F f) = g(1 - a)(1 - f) + F f`. Where the object is fully
fogged (f = 1) its patch disappears. Inside the fog start (18 blocks at fog 0) f = 0, so near patches are unchanged.
Remix draws no contact patches (`RemixApiAvailable()` returns early; it traces real shadows), so that path has
nothing to change.

- A/B: `[devtools] contact_shadow_fog=0` brings back the old pass (fog off), re-read once a second. The first
  `contact shadows:` log lines now carry `fog on|off start-end`.
- Probe: `gamerun/fw16_q64.py` (`keys_qa_fw16q64.sh`): the qav64c spot, wil 164.5,149.5, 11:00 paused, cloud
  30; fog 0/50/90 in third person and 0/90 in first, each shot with the key at 0 and then 1. Its ini writer looks
  for `[devtools]` at the start of a line, because the stage ini carries `; [devtools] car_coat=...` in a comment
  and `weather_look.setk` would write the key into that comment's section (the first run's toggle never reached
  the DLL).
- Verified (run fw16b, frames opened): at fog 90 the old pass leaves black dashes above the road down the street
  in third person and at the vanishing point in first person. The new pass leaves none, and the bus shelter's
  patch fades with the shelter. At fog 0 the crop under the van ahead is unchanged; the only differences in the
  frame are the passing car, peds and clouds. vreg `spawn_classic` PASS, 0 tiles changed.
- Not verified: night fog, rain plus fog (same code path, not framed), and a Remix take (no patches drawn there).
  Patches between 18 and 45 blocks at fog 0 now fade slightly (f up to about 0.25), which is the correct
  composite with the fogged ground; the old pass left them a little too dark there.

## WEATHER-V2: who sets the shared Remix keys (13 Nov 2026)

The day/night cycle, night exposure and the lamps belong to the LIGHTING work (branch lighting-v1). Weather and
the clock meet in ONE place: `dll/src/time_of_day.cpp` (`UpdateSky` / `UpdateDayLook`) composes the final values of
the shared Remix keys from the clock and one weather input, `TimeOfDaySetOvercast(0..1)` (set every frame by
`dll/src/weather.cpp` from max(cloud, rain overcast); 0 with [weather] off). The weather code pushes none of these
keys itself:

| key | composed in time_of_day.cpp from |
|---|---|
| rtx.atmosphere.cloudEnabled / cloudShadowStrength / cloudCoverageMean | clear-sky setting, overcast (coverage 0.29 + 0.66 o) |
| rtx.atmosphere.directionalLightRadianceScale | 1 - 0.7 o |
| rtx.atmosphere.sunShadowSoftnessDeg | 0.4 + 5 o |
| rtx.atmosphere.skyIndirectRadianceScale | day/night fill x (1 + 0.8 o) |
| rtx.autoExposure.* / rtx.tonemap.exposureBias | clock only (LIGHTING) |

Keys the weather code does push (not shared): rtx.weather.precipitation.* stays at intensity 0 (our own drops
are drawn instead; the runtime's particles were not seen on this setup), and nothing else.

## WEATHER-V2: Ray Reconstruction hides rain and volumetric fog (13 Nov 2026, gta2-rtx6000 runs vf1-vf3)

On the RTX PRO 6000 (Wine 10, Remix Plus 1.5.1, DLSS 310.6), with DLSS Ray Reconstruction ON the Remix-API rain
drops (thin water quads) and the volumetric fog (rtx.volumetrics.transmittanceMeasurementDistanceMeters, and the
runtime's own foggy preset) do not appear at all, day or night. With RR OFF both render: backlit rain streaks in the
head lamps, haze round lamps and lamp cones (vf3 norr_taau2, foggy2; vf1 taau2, dense2), and they stay visible with
DLSS super resolution back on (vf3 back_dlss2). Turning RR off live takes effect only after a renderer reset (the
next upscaler change: vf2 RR on + TAA-U shows nothing; vf3 RR off then TAA-U shows them), so set it at launch.
The frames with RR off are also much darker and noisier at night (the denoiser change, not the weather) - a LIGHTING
question. Not yet checked on the Windows 5090 (native NVAPI): re-test there.

## WEATHER-V2 handover (state 13 Nov 2026 ~16:30 UTC, branch weather-v2, local, not pushed)

Worktree /mnt/gta2/gta2-linux/wt_weather (rebased on camera-modes 2146197b). Private stage stage_wx (~/wx/mkstage.sh
rebuilds it from the worktree). 6000: /gta2/wx (runwx.sh NAME SECS, holds /gta2/remix.lock; env CASES, PROBE,
WX_MOD=/gta2/wx/gta2hd_wet, RTX_MORE=/gta2/wx/wx_base.conf, HOURS, WX_TAG, WX_ENV); DLL ships via
gs://nexar-generative-ai-gta2-xfer/wx/stage. Scenario scripts (gamerun/, both hosts): wx_probe.py (CASES
tag:kind:payload, kinds cfg / gv / ini:section:k=v / view / wait / key), wx_plain.py (gate-1 matrix, WX_POP=1 pop
sequence), wx_move.py, wx_car.py, wx_spray.py, wx_drops.py; all step 0.4 s after every warp (GHOST_STEP).
Plain runs: gamerun/grun.sh NAME SECS keys_<x>.sh with STAGE=stage_wx GTA2_DIRECT_KEYS=1 INI_SED scene/warp keys.

Done (each a commit): Remix ground layer (remix_wet.cpp: darkening film by wetness, puddles cut from a noise field
biased to gutters/ruts, damp rim, water film off by night); stepped wet materials (3 texture-hash variants of 107
road/pavement tiles at level load, only with [weather] on; tools/remix_wet_levels.py makes the gta2hd prims; layer
/gta2/wx/gta2hd_wet); overcast via TimeOfDaySetOvercast (time_of_day.cpp composes the shared keys - see table above);
Remix rain as API drop geometry (translucent; [weather] remix_rain, remix_drop_trans/ior, remix_rain_particle);
plain wet road toned down (no glass sheet); plain wet paint (car_coat c14); sprite-car Remix wet variants; wet
clothing (plain figures); road spray (both); lens drops (plain refraction, Remix shaded drop); rain under cover
(code, untested); probe tools (wx_probe_board, wx_sprite_log, remix_game_value).

Findings: Ray Reconstruction hides the Remix rain drops and volumetric fog (above); RR stays ON (orchestrator).
Lane "ghosts" were the post-warp player sprite (pedestrian agent). Lighting agent owns day/night, exposure, lamps.

Open, in order: emissive proxies under RR (backlit streaks near lights, headlight haze cones; one ini key);
puddle ripples; plain night streaks; plain puddle parity; rain-under-cover test; gate-1 matrix retake (with the
step); phase 2 (cycle, fog, storm, transitions video); phase 3 (perf both renderers, vreg same base, soak, 5090
rtx.conf keys).

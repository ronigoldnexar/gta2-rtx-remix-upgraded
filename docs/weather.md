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

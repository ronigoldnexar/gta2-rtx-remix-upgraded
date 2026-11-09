# The plain renderer's modern look (VISUALS-PLAIN, 8 Nov 2026)

> **Status (8 Nov 22:30, VISUALS-PLAIN-2): world shadows work; still OFF by default**
> (`[visuals] enabled=0`) until the Remix check and the night beam are seen.
>
> Fixed and verified in the running game (private stage, runs `out/vp2_*` on the 8x L4 host):
> - **buildings, fences and the whole world now cast sun shadows.** Cause: every world triangle
>   went through `ps_shadow_world`, which read the alpha-atlas cell as a second interpolated
>   texcoord; under Wine 9 that shader clipped every pixel (atlas dumps `vp2_dbg4`: with the solid
>   shader the city is in the map, with the cutout shader nothing; the atlas itself reads back
>   correct). The shadow copy is now its own FVF `XYZ|TEX1` buffer whose uv is already the atlas
>   coordinate, drawn through the caster path (`vs_shadow_model`, identity); solid triangles use
>   the plain depth shader, the cutout set (42k of 408k triangles) `ps_shadow_cutout`
>   (`vp2_dbg6`: the cutout set adds 9.7k atlas px; `vp2_look`: a building's shadow across the road);
> - far cascades refreshed on alternate frames (`shadow_stagger=1`) and caster replays set only the
>   state that changes: the post's own GPU time on the 90 s drive, medium, p50 8.4 -> 4.5 ms,
>   p99 23.4 -> 14.0 ms;
> - chroma flat over every drive (`vis_chroma.py`: medium p50 17.2, last 10 s 16.9; off 22.0).
>
> 90 s drive (`keys_perf2_drive.sh`, frame cost = whole - wait):
>
> | run | quality | cost p50 / p99 ms | post GPU p50 / p99 | note |
> |---|---|---|---|---|
> | vp2_off | visuals off | 5.9 / 39.3 | - | the game alone already spikes past 33 on this host |
> | vp2_med | medium, before stagger | 12.3 / 53.3 | 8.4 / 23.4 | |
> | vp2_med2 | medium | 7.3 / 26.4 | 4.5 / 14.0 | under 33 ms |
> | vp2_low | low | 9.5 / 62.6 | 3.7 / 18.0 | host load 15-17 during the run; spikes are `game` (20 ms) |
> | vp2_high | high | 12.2 / 48.5 | 7.4 / 25.2 | over budget (85-block third cascade) |
>
> Not verified: the headlamp spot lowered (x0.6 -> x0.3; at x0.6 a blown yellow-white bar on the
> asphalt, `vp2_look` tier_night_high) but no car was in shot in the rerun; street lamps light the
> facades but barely the ground; high tier over budget; Remix run (`visuals: RTX Remix device ...
> stay off`) and the Windows build (`dll/build.bat` now lists visuals.cpp, post_fx.cpp, sky.cpp).
> Debug: `debug=16|n` writes `atlas_<n>.pgm` once per value; n 8 all solid, 9 the renderer's buffer,
> 10/11 one draw, 12 cutout set left out. A cold Wine/NVIDIA shader cache makes the first run on a
> new host crawl (~1 fps for a minute); rerun before reading timings.

The play page runs the plain Direct3D 9 renderer (no path tracing), and next to the Remix
footage it looked dated: unlit-looking textures, no shadows, a flat sky, lamps that light
nothing at night. This pass gives the third- and first-person views a modern forward
renderer's look while keeping GTA2's palette and the play page's frame budget. The classic
top-down view is untouched, and under RTX Remix none of it runs.

Evidence: `out/visuals_plain_sheet.png` (before/after at the same spots and sun, third and
first person, day / golden hour / night; the quality tiers), the per-frame logs of the runs
below, and the frame-time table at the end.

## What was added

| Feature | How | Where |
|---|---|---|
| Sun shadows | Cascaded shadow maps (1-3 cascades by tier) in one 2048 px R32F atlas of 1024 px cells; a cascade is the bounding sphere of its slice of the view frustum (fixed size, so the map's scale never changes as the camera turns) and its centre is snapped to the map's texel grid (no shimmer while driving). 16-tap PCF (a 3x3 texel box with bilinear edges), normal offset of 1.6 texels plus a small depth bias (no acne, no peter-panning: the casters touch their shadows). The last cascade fades out over its final fifth. The sun is the [sky] sun (or the clock's, `follow_clock=1`); for the maps it never lies flatter than 10 degrees | `src/post_fx.cpp` `RenderShadows`, `ps_composite` |
| Shadow casters | The world: the static mesh's own vertex buffer with a second index buffer sorted into 16x16-block chunks (one draw per run of chunks the cascade touches) and an alpha atlas of the cutout tiles (fences and grilles cast cut-out shadows). Everything else (cars, people, props, map objects): every depth-writing triangle draw issued between the world pass and the end of the 3D pass is recorded from the device's draw calls (`DrawIndexedPrimitive` / `DrawPrimitive` hooked in the vtable, chained with the frame log's hooks) and replayed from the sun with a position-only shader (alpha-tested draws keep their cutout). No other subsystem's draw code changes | `PostFx::Record`, `BuildWorld` |
| Deferred shadowing | The frame is drawn as before, into an FP16 target with an INTZ depth texture; a full-screen pass reconstructs each pixel's view position and face normal from depth and takes away the sun's share of the fixed-function light where the shadow map says the sun is hidden: `dark = strength * S*ndl / (A + S*ndl)`. Faces turned away from the sun are already at ambient and are not darkened twice | `ps_composite` |
| Directional sun + hemisphere sky | While the post is on, the world's fixed-function sun is 1.5x and its ambient 0.84x (`sun_boost_percent`, `ambient_scale_percent`): sunlit faces stay as bright, faces in shade and in shadow get darker, which is what gives the shadows their contrast. A hemisphere term tints faces looking up toward the sky's hue and faces looking down toward a warm street bounce (30 %) | `Renderer::SetWorldShading`, `PostFx::SetSky` |
| Night lights | The lights the Remix path already keeps (`LightsTracked()`: the game's lamps and neon, the far map lamps, the synthetic car head and tail lamps, fires, muzzle flashes; sparks and bullets left out) become screen-space point lights, and head lamps spot lights; the nearest 16/32/64 in view, one quad each in a single draw, soft falloff `(1-x^2)^2/(1+4x^2)`, summed into a light buffer of their own (FIX-FX, 9 Nov), then added once as albedo (the frame's colour over the ambient it was drawn with) times the sum, the sum's strongest channel kept as it is up to 0.5 and rolled off exponentially to a ceiling of 1.0 with its hue (a strong saturated light, a siren, pales by up to 35 % towards white): overlapping pools, sirens, head lamps and fires tint a wall instead of clipping it to flat white, red, blue or yellow. A point light is bounded per light too (Remix radiances of 10 had made 2.6). The game's fire lights (one per flame) are merged into one warm flickering point light per blaze (radius 3.4 blocks), which keeps 45 % of its strength by day; every other light fades in as the sun goes down | `dll/src/visuals.cpp`, `ps_light`, `ps_light_apply` |
| SSAO | Half resolution, a normal-oriented hemisphere of 8 (medium) or 12 (high) samples within 0.38 blocks, range-checked, a per-pixel rotation; a depth-aware 3x3 blur; faded out beyond 45 blocks | `ps_ssao8/12`, `ps_ao_blur` |
| Bloom | Soft-knee bright pass (threshold 0.80) to quarter resolution, a 9-tap separable Gaussian; the high tier adds an eighth-resolution level | `ps_bright`, `ps_blur` |
| Tonemap | Fixed exposure (slightly up at night; no adaptation, so nothing pumps), a filmic shoulder from 0.78 that leaves the mid tones as the artwork has them, a gentle toe and 1.10 saturation so GTA2's colours stay loud | `ps_final` |
| Sky | A richer palette when `[visuals]` is on: deeper day blue, a golden hour with an orange horizon, a violet dusk, a navy night; stars at night (a generated 512 px star field, faded toward the haze, under the clouds); an HDR sun disc that the bloom picks up. The fog keeps the horizon's colour, so streets fade into the sky at every hour. The clouds are unchanged (still built in the warm-up) | `src/sky.cpp` |

### Shaders

Shader model 3 HLSL in `src/shaders/visuals.hlsl`, compiled offline to bytecode in
`src/shaders/visuals_gen.h` by `tools/build_shaders.sh` (runs `tools/shc.cpp` under Wine 10's
`d3dcompiler_47`, image `gta2-wine2510`; Wine 9's compiler has no loops). The DLL needs no
shader compiler at run time; on Windows `fxc /T ps_3_0` builds the same entry points. That
compiler has no integer arithmetic in SM3 and cannot unroll loops with conditionals, so the
shaders select cascades with `step()` and the PCF and blur taps are written out.

### RTX Remix

The renderer notes which `d3d9` answered `Direct3DCreate9`: the renamed bridge client
`d3d9_remix.dll`, or any `d3d9.dll` exporting `remixapi_InitializeLibrary` (the same export
`remix_api.cpp` uses). On such a device `PostFx::Init` installs no hook and creates nothing,
`BeginScene` always declines, and the sky keeps its v1.5 palette; the log says
`visuals: RTX Remix device: ... stay off`.

## Options (`[visuals]` in `gta2dx9.ini`, re-read every 2 s while the game runs)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | 0 | all of it; 0 is the v1.5 look (off until verified) |
| `shadows`, `ssao`, `bloom`, `tonemap`, `lights`, `hemisphere` | 1 | each pass |
| `shadow_stagger` | 1 | far cascades redrawn on alternate frames |
| `quality` | medium | `low`: 1 cascade to 30 blocks, bilinear PCF, no AO, 16 lights; `medium`: 2 cascades (14, 56), 16-tap PCF, AO 8 samples, 32 lights; `high`: 3 cascades (9, 28, 85), AO 12 samples, a second bloom level, 64 lights |
| `shadow_strength_percent` | 135 | 100 removes exactly the sun's share |
| `ao_strength_percent`, `bloom_strength_percent`, `bloom_threshold_percent`, `exposure_percent`, `saturation_percent`, `light_intensity_percent` | 75, 55, 80, 100, 110, 100 | tuning |
| `sun_boost_percent`, `ambient_scale_percent` | 150, 84 | the world's fixed-function light while the post is on |
| `sun_elevation_tenths`, `sun_azimuth_tenths` | -9999 | developer: move the sun live (day / dusk / night checks in one session) |

Logs: a `visuals:` line every 256 street-view frames (CPU and GPU ms p50/p99, casters, lights,
cascades); `GTA2DX9_VISUALS_LOG=<path>` writes one line per frame (CPU shadow / post ms, GPU
shadow / post ms from timestamp queries, caster and world draws, lights).

## Costs

(Filled in from the measurement runs below.)

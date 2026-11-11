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
| SSAO | Half resolution, a normal-oriented hemisphere of 8 (medium) or 12 (high) samples within 0.38 blocks, range-checked, rotated in a 4x4 pattern of 16 angles; a depth-aware 4x4 blur (FIX-CAR-SHADING-2; was a per-pixel random rotation and a 3x3 blur); faded out beyond 45 blocks. The pixel's depth is read at one full-resolution texel's centre and the comparison bias grows with the surface's depth step per texel (pmy3, FIX-WORLD-10: a half-resolution pixel sat on the edge of two depth texels and rounding picked one or the other, drawing 10 px vertical stripes of false occlusion on every wall) | `ps_ssao8/12`, `ps_ao_blur4` (`ps_ao_blur`: the old pass) |
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
| `twilight_fill_percent` | 60 | the sky's fill on the world through twilight (below; applies with the passes on or off, never under Remix) |

Logs: a `visuals:` line every 256 street-view frames (CPU and GPU ms p50/p99, casters, lights,
cascades); `GTA2DX9_VISUALS_LOG=<path>` writes one line per frame (CPU shadow / post ms, GPU
shadow / post ms from timestamp queries, caster and world draws, lights).

## Shaded walls at noon and at dusk (qav7, FIX-WORLD-13, 10 Nov 2026)

qav7 filed ste walls turned from the sun as near-black slabs (luma ~30) beside sunlit facades of
~116. Measured at the filer's poses (ste 90.5,170.5 and 210.5,110.5) with the passes switched live
in one session (out/qa_fw13ab1): at noon (sun 50 deg) nothing is missing or clamped on vertical
faces. A face turned from the sun gets the full ambient (0.8 x 0.84 = 0.66 of the texture), a sunlit
vertical face 0.66 + 0.6 x cos 50 = 1.05, so shade/sun = 63 % on the same texture, inside the
55-70 % the filer asked for; SSAO costs 2-5 %, the hemisphere tint 1-3 %, and with `[visuals]` off
the wall reads 48 instead of 32. The "4x" is the art: the dark ste stone (tiles 103, 105, 109,
luma 44-56 in the original, HD and photo sets alike) against the tan facades (173, 189: luma 100-137).
FIX-REMIX-MATERIALS-9 reached the same verdict for the Remix twin prx10 (baked-dark wall art).

The dusk half was a real lighting gap: the ambient fell with `day` (0 at -8 deg) while the dome
stays lit to -14 deg, so at 18:30 (sun -5.7 deg, day 0.04) every wall stood at 0.25 of its texture
under a bright violet sky. `AmbientDayLight` (src/sky.h, used by the world, the props and the
figures) adds the sky's remaining light, `twilight = max(0, lit - day)`, faded in as the sun goes
from 4 deg above the horizon to 2 below, times `twilight_fill_percent` (60). The ambient tint
there is already the cool night tint, so the fill reads blue-grey. Same pose, fill 0 vs 60
(out/qa_fw13twi2_ste, qa_fw13twi3_bil): noon unchanged (94.9 / 94.4, 79.0 / 79.6), 17:45 (sun
+2.9) +2-4 %, 18:30 +50-80 % (ste third-person shaded wall 24.5 -> 42.0, 53 % of its noon 79;
bil 19.0 -> 34.4), 19:00 (-11.4) +7-10 %, night unchanged. Zero on an RTX Remix device
(`g_skyRemix`); classic draws no world shading.

Then the art side, as the coordinator asked once FIX-REMIX-MATERIALS-9 had lifted the dark ste
wall art to an albedo floor in the Remix layer: `tools/photo_albedo_floor.py` scales the street
views' photo copies of ste's darkest wall tiles to a mean luma of 70 (103, 105, 109 green stone at
the filer's pose x1.23-1.52; 168-170 dark planks x1.26-1.42), a plain multiply that keeps the hue and
the art's own contrast. Classic draws the HD set and Remix never loads photo/, so neither changes;
originals in the host's `backup_fw13_photo/ste`. At the filer's spot (out/qa_fw13ab1 before,
out/qa_fw13flr_ste after) the shaded green wall goes from a near-black 32 to a textured dark green
41 at noon.

## The first-person hands and the night lights (qav19, FIX-FIGURE-16, 10 Nov 2026)

The light pass adds albedo x the summed lights to every pixel, and the first-person hands are pixels too: at the
wil dock (100.5,230.5, z 0) at 22:30 a teal light on the wall beside the eye added brown skin x teal, and the
arms read olive-green (`[visuals] lights=0` gave the brown back; shadows, AO, hemisphere, bloom and the tone
map did not change them). Now the view model (hands, fists, the gun) marks its pixels with stencil bit 0x40
(`kViewModelStencil`, post_fx.h) and `ps_light_apply` is stencil-tested off them; the hands take the same
lights themselves through their fixed-function ambient: `VisualLightAtEye` (post_fx.cpp) sums the night lights
at the eye with ps_light's falloff and a half-wrapped facing, bounded as the apply pass bounds them, and the view
model keeps 25 % of that light's hue over a warm white of its luminance (the wide-neon rule of visuals.cpp), so a
teal sign brightens skin without turning it green. Log: `view model: night light at the eye R,G,B -> hands R,G,B`.
`GTA2DX9_VM_LIGHT_OLD=1`: the hands under the light pass as before. Verified out/qa_fig16h0 (HEAD, olive) vs
out/qa_fig16h1 (skin) with `gamerun/keys_qa_fig16h.sh` (fig16_hands.py: FH_SPOTS, FH_TOG live ini A/B).

## Street lamps on posts at night (qav101, FIX-WORLD-20, 11 Nov 2026)

At wil 60.5,60.5 (the player walked to about 60.75,196.55) at 23:00, rain 80 fog 20 wet 1, the two pale facades
across the street were washed one flat olive-lime from lamp height to the roof line (mean RGB 79,83,33). The
filer read it as first person only; at the same facing third person shows the same wash (out/qa_fw20a), the
filer's third frame had looked another way. `[visuals] lights=0` removed it (40,41,23 -> 19,19,23 on the filer's
patch); `window_glow` (renderer and devtools) and `wet_roads` did not change it.

The light probe (`GTA2DX9_LOG_LAMPS=1`, post_fx.cpp: every 60 street frames the lights within 14 blocks of the
eye, and `lamps: kept N of M lights in view`) named it: each lamp post at x 56.92 sent three lights of the map
colour (0.89,0.89,0.33) = #E3E354, and one of them, the lantern copy at the head (y 3.54), at this pass's full
1.00 over the full 6-block reach. `FitLampsToPosts` (remix_lights.cpp) fits a map lamp to its drawn post for Remix
and raises the lantern's and the dish pool's intensity by (reference / emitter)^2, Remix radiance per emitter
area (10-40x); visuals.cpp read that raised value, so every lantern clamped to the maximum and one omni at the
head lit both facades evenly. Yellow with no red lead times a pale grey wall reads lime (blue 40 % of green).

`ProvideLights` (dll/src/visuals.cpp) now, for a fitted game lamp in the street views: takes the emitter gain back
out (the game's own strength), gives the lantern 1.8x of that over a 3-block reach (a warm patch round the head
that fades out a storey up), leaves the Remix dish spot to Remix (each lamp took three of the frame's 32 lights
at medium and the cap was always full at night, 32 of 63-145 in view, so third person lost the far lamps), and
raises the pool a block under the head to 0.5 x strength; and any street-class map light (red leads, blue
trails) takes 90 % sodium (255,190,110) at its own luminance. `[devtools] lamp_plain` = 1 (default), 0 as
before, 2 the strength part only, 4 the hue part only; re-read live. The classic view and Remix are untouched.

Verified (plain GL, 23:00 rain, the filer's walk, `gamerun/keys_qa_fw20c.sh`-style A/B on one build): out/qa_fw20f
first and third agree: the right-hand lamp lays a warm pool on the corner wall (97,79,60, G/R 0.81 B/R 0.62)
that is dark 100 px up the wall (20,21,26), where lamp_plain=0 washes it (130,128,33). Noon frames at the pose
are identical with 0 and 1 (mean of the filer's patch equal in both views). Not verified: dusk, clear-night
frames other than wil, Remix (not touched by this code).

## Sodium street lamps, the frame's light cap (FIX-WORLD-21, 11 Nov 2026)

FIX-WORLD-20's residual: its lamp pools read warm but paler than sodium (97,79,60 at the wil pool, G/R 0.81).
The frame is the scene (night ambient, blue-grey) plus albedo x the summed lights (ps_light_apply, which also
pales a strong light toward grey). A (255,190,110) light therefore landed paler still.
- `[devtools] lamp_plain=1` now gives a street-class map light a deeper high-pressure sodium (255,163,71) and
  the fitted lamp's pool a fifth more strength (0.60 vs 0.50 of the lamp). `lamp_plain=6` is FIX-WORLD-20's
  hue and pool, for a live A/B.
- Measured (out/qa_fw21l1, wil 60.5,60.5 walk, third person, the lit facade patch round the wall lantern,
  130x75 px mean): 23:00 rain 100,87,71 (G/R 0.88, B/R 0.71) -> 111,88,63 (0.79, 0.57); 19:30 (night
  on the game's clock) 106,96,78 -> 117,97,71 (0.83, 0.60). What the lamp adds over the unlit wall
  (32,36,44) is now +79,+52,+19 (G/R 0.66): deep sodium. What stays paler than a sodium photograph is the
  moonlit ambient under it, which this change leaves alone (a brighter lantern brings back qav101's wash).
  First person agrees; noon is unchanged (night-only lights; vreg noon shots as before).
- **Found, not fixed: the 32-light cap (`[visuals] quality=medium`).** The frame keeps the 32 nearest lights in
  view. In clear 23:00 traffic at that spot, 85 lights are in view (62 in the rain take), the 32 nearest all lie
  within ~5 blocks (car beams and brake lights among them), and the facade lantern ~10 blocks out is dropped
  in both settings: no pool at all (GTA2DX9_LOG_LAMPS=1, out/qa_fw21l2). Ranking the cap by a light's reach
  over its distance, or keeping map lamps ahead of car beams, is the next step; untried.
- Remix, one take (out/fw21rx, `gamerun/rn_remix.sh`, wil 60.5,60.5 at 23:00, Ultra rig defaults): no lime
  wash. The post lantern lays a small warm pool on the road, the facade beside the lens reads warm tan, and the
  far lamps are warm-white points; with the DLL's lights off (`remix_lights_off=1`) the street goes near-black.
  Remix's lamps read warm-white rather than sodium; that is Remix's light colour (remix_lights.cpp), untouched here.
- 19:30 is already full night on the game's clock at this spot (stars, lamps at full strength); a true dusk
  (sun just set, sky still lit) was not framed.

## The night light budget: map lamps apart from traffic (fw21 light cap, FIX-WORLD-22, 11 Nov 2026)

The plain pass drew the 16/32/64 lights nearest the eye (quality low/medium/high). At night in wil traffic,
100 to 200 lights are in view: each car brings two head-lamp beams and two tail lamps, and each map lamp brings
its lantern and its pool. Round a third-person eye most of the nearest 32 were car lamps. At the fixed eye
`58.3 50.5 3.0 -> 58.3 71.0` (game coords, wil 23:00 clear, `GTA2DX9_REGRESS_CAM`), the nearest-32 cut kept
only 10 to 30 map lights, and it dropped the junction lamp heads and pools 15-16 blocks down the street. Which
lights it dropped changed with every passing car: map lights switched between drawn and not drawn **53 times
in a 20 s traffic pass** (54 at the reverse eye).

`src/post_fx.cpp` now does three things (`[devtools] light_rank=1`, the default):

1. The map's own lights (`VisualLight::fixed`: game lights that never move, and lit windows) and the
   moving ones (car lamps, sirens, fire, muzzle flashes) each get a budget of their own: low 12 + 4,
   medium 40 + 16, high 64 + 24. Traffic can no longer take a lamp's light.
2. Inside each budget, a light ranks by what it adds to the frame: strength x min(1, reach^2 / distance^2).
   A beam is measured at the middle of its throw, and ranks at 5 % when that point lies behind the eye. A
   far beam ranks under a lantern's pool, and a car's beams behind the lens give way to the beams on the
   road ahead.
3. A light kept last frame ranks x1.5 (hysteresis). A light crossing the budget eases in or out over 10
   frames, smoothstepped. Every light in view is tracked: map lights by their spot, moving ones by the
   nearest spot within 0.6 blocks. A light that has just come into view is drawn at once, as before.

`light_rank=0` is the old nearest cut (live A/B, re-read every ~2 s). `light_budget=N` overrides the map
share. `GTA2DX9_LOG_LAMPS=1` now logs, every 60 frames: map/moving kept of budget, how many lights are
easing, how many times map lights switched since the last line, and the six nearest map lights in view that
were not drawn (distance, place, screen pixel). Light positions in that log are renderer coordinates
(x, up, 256 - game y); the regress camera takes game coordinates.

Measured (out/qa_fw22c3, out/qa_fw22d1; L4, medium, `visuals: quality` 256-frame lines):

| eye | mode | map kept | map switches / 20 s | GPU post p50 |
|---|---|---|---|---|
| c1 (down the street) | nearest 32 | 17-30 of 32 | 53 | 1.74-2.45 ms (mean 2.03) |
| c1 | ranked 40 + 16 | 40 of 40 | 0 | 1.03-1.69 ms (mean 1.25) |
| c2 (reverse) | nearest 32 | 10-18 of 32 | 54 | 0.45-1.91 ms (mean 1.30) |
| c2 | ranked 40 + 16 | 40 of 40 | 0 | 0.67-1.22 ms (mean 0.98) |

The ranked 56 lights cost less GPU time than the nearest 32. The nearest-first cut kept the screen-filling
beams round the eye, and the cost of each light is the screen area of its quad. A map budget of 56 (64
lights) measured 2.7 ms against 0.3-0.6 ms for 40 (out/qa_fw22c1), so medium stops at 40 + 16. With the
ranked budget, the map lights not drawn at c1 are small (r 2.0, i 0.32) lights 15.7+ blocks out. With the
nearest cut they were lamp heads and pools at 15-16 blocks.

Video check: 2 fps sheets of the four 20 s passes (`feel_tools/fw22/pass_sheet.py`, crops of the near
lantern, the median lamp and the far junction). The lamp crops' mean luma holds flat through both modes,
apart from cars driving through the crop. Most of the nearest cut's drops were 15+ blocks out, where a
pool is a few pixels, so its flicker shows in the log more than in a still.

Not covered: rain, other districts, high and low quality (their budgets are set by proportion but not
measured), and RTX Remix (this pass does not run under Remix).

### A faded car's contact patch (fw21 near-lens car, FIX-WORLD-22)

The chase view fades a car standing between the lens and the hero, or around the lens (live_geometry
`ChaseCarFades`, FIX-CAMERA-18), but its contact patch (`DrawContactShadows`) stayed at full strength. A dark,
car-shaped patch slid along the road under a body that was not there. Now a car faded under half draws no body
patch and no tyre patches, and a car faded above half draws them at the patch opacity x its alpha, as a second
draw after the rest (the rule `mast_fade` gives props). `[devtools] car_fade_shadow=0` is the old behaviour
(live A/B). Whenever a faded car was seen, the log gets one line per 300 frames: how many faded cars' patches
were dropped or scaled.

Probe: out/qa_fw22s5 (`gamerun/fw22_shadow.py`). wil 13:00, sun shadows off so only contact patches darken
the road. Every traffic car is held at 40 % alpha (`GTA2DX9_CAM_FADE_TEST=40`), at a fixed eye over the
lane. car_fade_shadow 0/1 alternates every 2 s. Pair s3: with 0, a large dark patch lies under the car at the
lens, whose body is invisible. With 1, no patch, and the 40 % truck in view stands on clean road. The log
counted 500-2100 faded-car patches dropped per 300 frames.

Not covered: the 50-100 % band (the fade test holds one alpha a run; 40 % was filmed). A faded car's **sun
shadow** (the post pass's shadow map) still falls (out/qa_fw22s3 pair s8, the 40 % truck). Small staggered
tyre patches with no body over them appear after a truck passes, in both modes. They belong to a vehicle
whose body is not drawn (probably the truck's trailer), not to a faded one, so this rule does not touch them.

## Smooth car panels under the AO (coord82, FIX-CAR-SHADING-2, 11 Nov 2026)

With the AO on, a pale car's flank, bonnet and boot carried grey clouds 10-30 cm across: a hammered-metal mottle
over a smooth panel (VEHICLE-ART-19's same-spot A/B: car sun, shadow mask and paint texture ruled out, `ssao=0`
clean). Measured on the white 044 parked at wil 206,199.7 (`keys_va11_own.sh`, `EXIT=1`, poses side/front34/eye,
12:00 clear), the frame divided by its `ssao=0` twin: the flank sits at 0.73-0.75 of its AO-free brightness, a
smooth fall toward the sill (the road and the wheels occlude the lower half of a vertical panel: that part is
real), plus pixel-to-pixel noise in the ratio (high-pass std 0.0136). The noise is the cause: each half-resolution
pixel turned the 8-sample kernel by its own random angle (a sine hash of the pixel), so where a surface is partly
occluded each pixel counted a different random subset of hits, and the 3x3 blur averaged only 9 of them. Pale paint
shows what textured ground and walls hide.

Tried first and dropped: a horizon-angle test (an occluder counts only above N degrees over the tangent plane,
against the mesh's own small dents). On the 044's flank it changed the ratio by 0.001: the occluders there are
steep (road, wheels), not dents.

Shipped: the kernel's rotation now follows a 4x4 Bayer order of 16 evenly spaced angles, and the blur
(`ps_ao_blur4`) averages a 4x4 footprint with the same depth weights, so every output pixel on a smooth surface
holds the mean of all 16 rotations (128 samples at medium quality) and the noise cancels. The weights still stop at
depth edges, so a crease, a wheel arch, the shade under the sills and a wall's foot keep their AO. Same sample
count, 16 blur taps instead of 9 at half resolution. 044 flank: high-pass std of the AO ratio 0.0136 -> 0.0054,
mean unchanged (0.745 -> 0.744).
034 flank 0.0167 -> 0.0107. Crease and contact AO unchanged: the 044's arch and underbody at the eye pose 0.723 ->
0.722 of the AO-free frame (white) and 0.722 -> 0.721 (forced dark paint 18,18,22), the ground beside the car 0.933 ->
0.932; a standing figure at the spawn wall and the wall's foot look the same old and new (frames opened at full size
and 3x crops).

Cost, interleaved in one session (the key flipped live every 26 s through a 300 s third-person walk/drive soak,
`qa_stress3_third.py`, frames binned by the log's `ao denoise` lines): post-chain GPU time median 0.206 -> 0.212 ms
(`GTA2DX9_VISUALS_LOG`); median frame 33.26 ms in both at the 30 fps cap; frames over 50 ms 2.2 % (old) vs 1.0 %
(new), within the run-to-run spread of the streaming hitches (an earlier soak leaned the other way); the `frame
times` lines' sprite stage (where the post resolves) 17.8 vs 17.3 ms avg. The change adds no draw call and no CPU work.

`[devtools] ao_denoise=0`: the old pass (re-read live, for A/B). The classic view never runs the post chain:
`tools/vreg/vreg.sh stage` gives `spawn_classic` PASS, 0 tiles changed. The Remix path draws no AO of ours (the post
chain does not start on a Remix device).

## Costs

(Filled in from the measurement runs below.)

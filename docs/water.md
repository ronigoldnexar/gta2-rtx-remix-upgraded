# Water in the street views (QB-37)

Quality-bar row QB-37 ("a flat turquoise textured plane"). The water tiles
(608-619, the game's animated water group) get a small shader-model-3 surface in
the third- and first-person views. The classic view is unchanged (the renderer
only uses it when the street shading is on), and so is an RTX Remix device (Remix
lights and path-traces the water itself; the fixed-function draw is what it hashes).

Code: `src/water.h`, `src/water.cpp`, `src/shaders/water.hlsl` (compiled into
`src/shaders/water_gen.h` by `tools/build_water_shader.sh`, Wine 9's d3dcompiler in
the `gta2-remixbox` image - the shader is loop-free and has no `sin`, which that
compiler lacks). Hooks in `src/renderer.cpp` (`DrawWorld`: water batches only).

## What it draws

| Part | How |
|---|---|
| Movement | Three layers of a 256 px tileable wave map (value-noise chop over four directional swells with whole periods, so it tiles), drifting in different directions at different scales; the slopes give a per-pixel normal. Mip-mapped by averaging the slopes, so distant water calms instead of shimmering. |
| Body | The game's own water tile (still animated by the game, or the HD sheet), lit like the fixed-function pass lights an upward face, shaded by the wave height. |
| Reflection | Schlick Fresnel against the per-pixel normal: almost none looking down from the chase camera, mostly sky at a grazing angle across a basin. The reflected colour is the sky dome's own zenith/horizon gradient for the frame (`Renderer::DrawSky`). **Sky only**: buildings, cars and people are not reflected (no planar or screen-space reflection pass). |
| Sun glint | Blinn-Phong highlight of the sun on the wave faces, faded out as the sun sets (nothing at night). |
| Edges | A 256 x 256 distance-to-shore map (one texel per map cell, chamfer distance, capped at four cells) built at level load from the water lids in the world mesh. A thin foam line where the water meets a quay or bank, and a lapping band that comes and goes with the waves, broken up by the wave height. |
| Fog | ps_3_0 gets no fixed-function fog: the same linear fog by view depth in the shader. |

## Settings (`[renderer]` in `gta2dx9.ini`)

| Key | Default | |
|---|---|---|
| `water_shader` | 1 | 0 = the older fixed-function ripple (`water_effect`) |
| `water_waves` | 100 | wave slope strength, percent (0..200) |
| `water_reflection` | 100 | Fresnel reflection strength, percent |
| `water_foam` | 100 | foam strength, percent; 0 = no foam |

It falls back to the fixed-function ripple by itself when the device has no
shader model 3, a shader is refused, or the shore map cannot be made (the log
says which: `water:` lines).

## Verification

See the section below, filled from the runs.

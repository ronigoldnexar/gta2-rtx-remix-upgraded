# Water in the street views (QB-37)

Quality-bar row QB-37 ("a flat turquoise textured plane"). The water tiles
(608-619, the game's animated water group) get a small shader-model-3 surface in
the third- and first-person views. The classic view is unchanged (the renderer
only uses it when the street shading is on), and so is an RTX Remix device (Remix
lights and path-traces the water itself; the fixed-function draw is what it hashes, and the
gta2hd layer gives those hashes a smooth water material: `tools/remix_water.py`,
docs/remix-materials.md "Water under Remix").

Code: `src/water.h`, `src/water.cpp`, `src/shaders/water.hlsl` (compiled into
`src/shaders/water_gen.h` by `tools/build_water_shader.sh`, Wine 9's d3dcompiler in
the `gta2-remixbox` image - the shader is loop-free and has no `sin`, which that
compiler lacks). Hooks in `src/renderer.cpp` (`DrawWorld`: the water batches are held back from the
tile loop and drawn together after it, one shader switch per frame).

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

## Pitfall met on the way: Wine 9's compiler and unused inputs

The first build declared the vertex shader's unused `NORMAL` input in the same
register as `POSITION` (`dcl_position0 v0` / `dcl_normal0 v0` in the disassembly):
the vertices landed nowhere and the basin showed the sand riverbed under it. The
vertex input is position and texture coordinates only. When changing the shader,
look at the `dcl` lines (`wine shc.exe water.hlsl vs_water vs_3_0 a.h k a.txt`).
Wine 9's compiler also lacks `sin` and the `?:` operator on floats; the lapping
band uses a parabola on `frac`.

## Verification

Probe: `gamerun/qb37_water.py` (keys `gamerun/keys_qa_qb37_water.sh`; copies in `linux/docker/`) through
`gamerun/qa_run.sh` on the GPU image, Downtown: warp to the roof at (203.5, 237.5),
height 4, west of the harbour basin (x 209-232, y 241-252; quays at level 1, water
at level 0); turn by the log's `face=` until facing the basin; first-person frames
(a burst 0.4 s apart), then third person. Runs `qa_qb37_on9` (this build, on top of the weather pass), `qa_qb37_on8` (batched, before the merge),
`qa_qb37_on7` (per-batch switching), `qa_qb37_off7` (`water_shader=0`, the old ripple).

Verified in frames:
- The basin is a moving surface: the wave pattern shifts between frames 2 s apart
  (`qa_f1_00` vs `qa_f1_05`); the old path showed the flat turquoise tile.
- Fresnel: near water under the roof shows the game's water colour with waves; toward
  the horizon it turns to the sky's horizon colour.
- Foam: a thin white line along the foot of the far quay wall (`qa_f1_sse`, crop
  left of centre). Thin at that distance; closer views were not framed.
- `water: shader surface ready` and `water: 5340 water cells, shore map built` in the
  log; no FAULT lines in any run.

Frame times (`frame times` log lines, same spot, 30 fps cap; the host was at load
20-60 from other agents' runs, so these are noisy):

| run | game avg ms | world avg ms | wait avg ms |
|---|---|---|---|
| off7 (old ripple) | 2.8-3.6 | 2.0-2.2 | 22-25 |
| on7 (shader, per batch) | 3.8-6.3 | 2.4-3.6 | 18-22 |
| on8 (shader, batched) | 6.1-6.8 | 2.8-3.1 | 18 |

The water costs at most about a millisecond of CPU submit time here and leaves 18 ms of
the 33 ms frame unused; a clean A/B on an idle host was not possible this session.

Not verified in a run:
- RTX Remix: the shader is never created on a Remix device (`WaterFx::Init` returns at
  once), so Remix keeps the fixed-function draw it hashes; code-gated, not run.
- The classic view: the shader path needs the street views' sun or fog, as the old
  ripple did; the classic frames in these runs looked as before, not byte-compared.
- Night and dusk (the glint fades with the sun; the sky colours come from the dome).
- Other districts (Residential, Industrial): the shore map is built from the water
  lids of any map, but only Downtown was framed.
- Water seen from the water itself (swimming / drowning frames): the camera dives in
  as the player drowns.

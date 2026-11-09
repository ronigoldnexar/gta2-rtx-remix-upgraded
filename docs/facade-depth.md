# Facade depth from tile-art segmentation (QB-25, 9 Nov 2026)

Quality-bar row 25: "Buildings are the map's boxes with one texture per face: flat windows,
flat doors". This pass gives the wall tiles of all three districts a height map built from
what the art *is* (window, door, shop window, frame, sill), so RTX Remix's parallax
displacement recesses the openings into the box faces. Plain renderer: unchanged.

## Why the old height was not enough

`tools/remix_pbr.py` (VISUALS-REMIX) makes a height only from a band-passed luminance, and
it leaves out every tile that has windows or signs: a dark window would come out as a
groove and a bright frame as a ridge. So the 1 674 tiles with a height were brick, block
and cobble, and the facades that most need depth had none (or, where its window detector
missed the windows, a luminance relief with the glass bulging at 0.018).

## Pipeline

1. **Wall tiles** (`facade_depth.py usage`): from each district's `.gmp`, how often each
   tile is on a block's side face and on a lid. Tiles used more as a lid than half their
   side use are roofs or ground and are skipped. 1 205 wall tiles over wil/bil/ste.
2. **Grounding** (`tools/facade_ground.py`): Qwen3-VL-8B-Instruct (Apache-2.0, already in
   the host's Hugging Face cache; no download) is shown each wall tile's HD texture at
   448 px and asked for boxes of `window`, `door`, `shop window` and `sill`. Batches of 8,
   ~2 s a tile on one L4 (41 min for 1 185 tiles; `CUDA_VISIBLE_DEVICES=2`, under
   `/tmp/gta2-gen.lock`, `taskset -c 0-4`, `nice -n 10`). The boxes, in 64 px tile units,
   are committed as `tools/facade_boxes.json` (coordinates only, no art).
   Result: 507 tiles with at least one opening; 984 windows, 136 doors, 97 shop windows,
   685 sills.
3. **Segmentation** (`segment_boxes`): the boxes on the game's own 64 px palette art,
   snapped to its pixel grid. A box is dropped when it does not stand out from a 3-texel
   ring round it (Lab distance < 9, flat inside, not darker), when it is a big panel that
   is not darker than its ring (> 40 % of the tile, plaster panels), and when a "window"
   spans the tile's whole width (girders, bridge bands; only a shop window may). Inside an
   opening, texels much lighter than its median that lie on a mostly-light row or column
   or on the box's rim are frame and glazing bars; light blobs inside (curtains,
   reflections) stay glass.
4. **Height** (`height512`), 1 = outermost (what the runtime's POM treats as the
   surface): sill 1.0, wall 0.80, frame and bars 0.70, door 0.34, glass 0.18; edges
   softened to a ~2 px bevel at 512 px; plus the HD tile's own structure band (bricks,
   joints) at +-0.05 so the wall keeps its relief. `displace_in` 0.04 (depth per UV
   width; a tile is one block wide), so glass sits ~2.5 % of a block behind the wall
   (0.07 was the first value; see the verification below for why it was lowered).
5. **Normal**: the remix_pbr normal with the new relief's slope added, so the reveal
   edges shade under the path tracer's lights as well as parallax-shift.
6. **Layer** (`facade_depth.py build`): for 450 tiles (wil 211, bil 120, ste 119; the rest
   of the 507 lost all their boxes to the checks above) writes `<hash>.h.rtex.dds` (256 px
   BC4, max mip chain, `remix_materials.write_height`) and `<hash>.n.rtex.dds` (512 px
   BC5), sets `displace_in` (and a `facade` summary) in `pbr.json`, and patches only those
   prims in `mod.usda` and `mod_wet.usda` in place; every other line stays byte-identical
   (car, prop, avatar and emissive prims included). Files are unlinked before writing, so
   a private layer of hard links to the package layer (`cp -al`) is safe to build into.

Checking sheets (art, labels, height, old vs new relief under a raking light):
`BOXES=tools/facade_boxes.json python3 tools/facade_depth.py sheet game/data <wil|bil|ste> out.png [tiles]`.

Known weak spots, seen on the sheets: the grounding misses some windows in brick with
strong mortar (wil 405) and on a few dark tiles; ornaments or vent grilles are sometimes
called windows (wil 485, bil 575 lettered grille, bil 649 green light slots) and get
recessed; arched windows are boxes (the arch head is recessed as a rectangle). A tile whose
window is cut by the tile edge is recessed only on the side that holds most of it.

## Reproducing

    # wall-tile boxes (GPU, ~40 min; resumable)
    CUDA_VISIBLE_DEVICES=2 HF_HUB_OFFLINE=1 flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10 \
      python3 repo/tools/facade_ground.py game/data repo/assets/textures_hd boxes.json
    # into a private layer
    cp -al repo/package/rtx-remix/mods/gta2hd gamerun/remix_vis/qb25_gta2hd
    python3 repo/tools/facade_depth.py build game/data repo/assets/textures_hd \
      gamerun/remix_vis/qb25_gta2hd repo/tools/facade_boxes.json --report rep.json

Python: torch + transformers >= 4.57 for the grounding (a venv; the host has none
system-wide), numpy, Pillow, xxhash for the build.

## Verification under Remix

Take: `linux/docker/facade_run.sh <name> [layer]` (copy to `gamerun/`; it runs
`keys_remix_facade.sh` -> `remix_facade_take.py` through `remix_l4.sh`, so the GPU lock and
the run slots apply). At three Downtown pavement spots chosen from the map as looking along a
wall of window tiles (164.5,202.2; 228.5,137.2; 239.8,191.5), first person and chase view,
14:00 and 17:30, it holds the pose and pushes `rtx.displacement.displacementFactor` live
through `[devtools] remix_config` (`FAC_FACTORS`, default 1,0,2,1): the same frame with the
displacement off, at the shipped scale and exaggerated. Frames: `remix_frames.py dump
out/<run> <secs> <dir> "^f" 0.3` after the session has ended (it times frames from the mp4's
end).

**Run qb25_C (displace_in 0.07, the private layer at `gamerun/remix_vis/qb25_gta2hd`),
seen in frame:**
- The height maps are read and displace: at 14:00 on the brick wall of spot 2 the windows
  are flat at factor 0 and set back with visible reveals at 1, deeper at 2; at 17:30 the
  arched windows of spot 0 (chase view) the same. Same pose in all three frames, so the
  difference is the displacement alone.
- At 0.07 the reveals were too deep for the art: at grazing angles POM stretches the rim
  texels (white frames) into wide pale bands down the side of each window, and the arched
  window tile's glass (curtains, reflections) read as melted. Factor 2 (0.14) is clearly
  wrong. So the shipped scale was lowered to 0.04 and the bevel sharpened.
- 0 faults in the game log of the earlier full-layer run (qb25_B, 0.07), no texture or
  material errors in the Remix log; the layer loaded with 12 735 textures (41 more than the
  package layer: window tiles that had no height map before).
- Spot 1 (228.5,137.2) looked down a sunlit pavement along a plain wall: no visible change
  (its windows are above the frame).

**Run qb25_D (displace_in 0.04, sharper bevel; factors 1, 0, 1.75 = the old 0.07, 1), seen in
frame.** The warps landed at other headings than in qb25_C (and the stage now draws the modern
HUD), so D is compared within itself, frame for frame:
- Rectangular windows in brick (spot 2, first person, 14:00): at 0.04 the sashes sit behind the
  frame with a thin dark reveal and no pale smear; at x1.75 (0.07) deeper and, with the sharper
  bevel, also without the bands seen in qb25_C. 0.04 is kept as the shipped value: it reads as a
  real reveal without stretching the art.
- Arched-window wall (spot 0, chase view, 14:00): the windows are recessed at 0.04 with dark
  reveals, but the reveal edges are ragged: the frame/glazing-bar mask is snapped to the 64 px
  art and its steps show under parallax. Defect, open: smooth or drop the frame level inside
  arched and many-barred windows. The x1.75 frame of this pose looks nearly flat, unlike spot 2;
  not explained (possibly the renderer's temporal accumulation after the live push).
- Game and Remix logs of qb25_D were not copied out by the time of this note; faults unchecked
  for D (qb25_B and qb25_C: 0).

Earlier whole-session A/B (qb25_A package layer vs qb25_B facade layer at 0.07, the
`keys_remix_vis.sh` take) is not a valid comparison: the warps landed at different poses in
the two sessions; it is kept only as the no-fault check above.

Not verified: the ragged arched-window reveals above (open defect); Bus Terminal (bil) and Industrial (ste) facades under Remix (the tiles are in
the layer; only Downtown was taken); motion (swimming) of the parallax while walking; the
frame cost of 450 more/deeper POM materials (the frame log was not on); night.

The package layer (`package/rtx-remix/mods/gta2hd`, used by the 8082 Remix play page) is NOT
rebuilt by this pass: `build_remix_mod.sh` now runs the facade step, so the next layer
rebuild (or `facade_depth.py build` into the package layer) ships it.

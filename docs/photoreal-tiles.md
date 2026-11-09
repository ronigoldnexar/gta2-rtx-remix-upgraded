# Photo-material tiles: real surfaces on GTA2's buildings and streets (ASSET-BUILDINGS, 9 Nov 2026)

Goal: buildings, streets and props read as photographed materials at street level, while the
city keeps GTA2's layout and every recognisable landmark (windows, doors, cornices, signs, kerbs,
road markings stay exactly where the 64 px art put them).

## What it does

`tools/photoreal_tiles.py` writes a second tile set, `gta2dx9_textures_hd/photo/<style>/tile_NNNN.dds`
(512 px, DXT1/DXT5 with mips, same format as the HD set). The renderer loads a tile from there
first and falls back to the HD set (`[renderer] photo_tiles=1`, default on; `0` turns it off).
On an RTX Remix device the photo set is never used: the Remix PBR layer
(`package/rtx-remix/mods/gta2hd`, and QB-25's facade displacement) is keyed by the HD set's
texture hashes, and it must keep matching. The log line `photo tiles: N of them from ...` after
`hd tiles:` says how many were used.

Per tile:

1. **Class** (`classify`, Qwen3-VL-8B on the HD tile, GPU): first whether it is a sign, logo,
   lettering, neon, screen or water (then it is left alone), then the material of most of the
   wall (wall list: plaster, painted render, stone, concrete, brick, painted/rusty/bare metal,
   wood, marble, glass) or of the surface (ground list: asphalt, paving, concrete, dirt, grass,
   gravel, roof, ...), the list chosen by whether the maps use the tile mostly on building sides
   or on lids. Tiles in the map's `ANIM` groups (water, neon, screens) are always skipped so the
   frames of an animation stay identical.
2. **Base**: the clean Real-ESRGAN upscale of the tile for walls and pavements (the SD 1.5
   rendering in the HD set invented crackle on plain concrete and cracks in bricks); the shipped
   HD tile for road lids (where `tools/reauthor_road_markings.py` re-authors the paint) and for
   grass, dirt and gravel (SD's rendering of those is better than ESRGAN's).
3. **Material** (`MATERIALS`): one CC0 photo-scanned material per class (ambientCG, 2K JPG:
   colour and displacement), tiled a whole number of times across a 4 m block face, so the
   tile still wraps seamlessly.
4. **Transfer**: `out = base * exp(w * (a * grain + b * relief))`. `grain` is the material's
   luminance high-pass (pores, aggregate, scratches, stains; features under ~25 cm, never its
   bricks or slabs, so it cannot fight the art's own structure); `relief` is its displacement
   high-pass shaded by a light from above-left: micro shadows that survive in the fixed-function
   world pass, which has no normal maps. `w` fades both out over the art's own detail (local
   contrast of the original at 64 px scale: openings, glass, lettering, ornament), over dark
   voids and over cutout texels. Alpha is the HD tile's, untouched. Colours, layout and
   structure are the base's: the photo layer only adds surface.

Commands (the workdir used on 9 Nov was `/mnt/gta2/ab_work`, venv with torch + transformers):

    photoreal_tiles.py fetch    <cc0 dir>                             # CC0 materials from ambientCG
    photoreal_tiles.py usage    <game/data> usage.json                # side/lid counts, anim tiles, road lids
    photoreal_tiles.py classify <64px dump/style> usage.json <style> labels_<style>.json --hd assets/textures_hd/<style>
    photoreal_tiles.py build    assets/textures_hd/<style> labels_<style>.json <cc0 dir> <out>/photo/<style> \
                                --esrgan <ESRGAN 1024 px dir>/<style> --usage usage.json --style <style>
    photoreal_tiles.py sheet    <64px dump/style> assets/textures_hd/<style> <out>/photo/<style> sheet.png --tiles a,b,c

Classification takes ~25 min for the three districts on one L4 (~86 tiles/min), the build
~2 min per district on 4 CPUs. Like the HD set, the photo set embeds the game's art and is not
committed: it ships in the textures archive (`assets/textures_hd/photo/` sits inside the folder
`tools/pack_release.py` already zips).

## What was tried first and rejected

SDXL base + the SDXL tile ControlNet (`xinsir/controlnet-tile-sdxl-1.0`), circular padding,
init from the ESRGAN upscale, per-tile material prompts, strength 0.5 / 0.7 / 0.85 / 1.0:
up to 0.85 the result hugs the init and adds little over the shipped set; at 1.0 it invents
crackle and lattice patterns over plain walls and glass. A tile is a whole block face (two
window bays), so a diffusion model has no real-world scale to work at; the transfer above makes
the scale explicit instead.

## Licences

Materials: ambientCG (ambientcg.com), CC0 1.0: Plaster001, PaintedPlaster017, Concrete031,
Concrete034, Concrete044A, PaintedMetal004, PaintedMetal009, Metal012, Wood067, Marble012,
Asphalt026B, Ground054, Grass004, Gravel022. Classifier: Qwen3-VL-8B-Instruct (Apache-2.0),
used offline only.

## Verification

See the Status section below (frames from the running game, classic view beside the street
views at the same spots, photo set off vs on).

## Status (9 Nov 2026)

Built: all three districts (Downtown 756, Residential 811, Industrial 750 photo tiles; 482 MB on
disk; in game a photo tile replaces its HD tile, so texture memory is unchanged). Classes per
district in `labels_<style>.json` of the workdir (Downtown: concrete 245, paving 147, brick 139,
painted render 73, asphalt 69, stone 41, skipped 44 of which 40 signs/neon/logos, ...).

Verified in the running game (plain GL renderer, L4, Downtown, my DLL on a private stage,
`linux/docker/ab_facades.py` at six wall-facing spots from `ab_spots.py`, one run with
`photo_tiles=0` and one with `photo_tiles=1`, runs `ab_photo_off` / `ab_photo_on`):
- the log says `photo tiles: 756 of them from ...\photo\wil` with the set on and
  `photo tiles: 0 of them from (off)` with it off; `hd tiles: 818 loaded, 0 failed` in both;
  0 faults in both runs.
- frames (classic view beside first person at the same spot): pavements gain a photographic
  concrete-slab surface with stains and pores instead of the smooth SD paint; ashlar and brick
  walls get straight courses and crisp windows (no SD wobble) plus fine stone grain; road lids
  keep their markings and get asphalt cracks and aggregate. Layout and landmarks are unchanged
  (same art, same positions).

Not verified / still wrong:
- Residential and Industrial sets were built with the same code but not looked at in game.
- On walls the grain is subtle at street distance; the overall look is still limited by flat
  fixed-function lighting (no normal maps in the world pass) and the map's box geometry. Real
  depth on facades is QB-25's Remix displacement; in the plain renderer it would need a
  normal-mapped world shader (not done).
- Class labels are imperfect (e.g. a wooden floor tagged concrete, a stained-glass window tagged
  stone); the effect is grain only and fades over detail, so a wrong class costs little, but
  `labels_<style>.json` can be hand-corrected and the build re-run in two minutes.
- The two runs' headings differ slightly (the turn-to-face is timing dependent), so the A/B
  frames are not pixel-aligned.
- Props (3D models in `assets/models`) are untouched by this pass.

## Update: Residential and Industrial checked, labels corrected (ASSET-BUILDINGS-2, 9 Nov 2026)

Which dir is which: the in-game intro text at the `bil` spots reads "Industrial District", so
**`bil` = Industrial (811 tiles) and `ste` = Residential (750)**; the counts in the Status section
above were attributed the other way round.

Looked at in game (plain GL renderer, L4, private stage, `linux/docker/ab_facades.py`, six wall-facing
spots per district from `ab_spots.py`, third and first person, `photo_tiles=0` vs `1`): both sets load
(`photo tiles: 750 ... \photo\ste`, `811 ... \photo\bil`), `hd tiles` all loaded, 0 faults. Pavements,
roads and ashlar/brick walls read as in Downtown. Headings still differ slightly between runs, so the
A/B frames are not pixel-aligned (same caveat as before).

Labels: the classifier used `concrete` as its catch-all. Reviewing the tiles by class on contact sheets
showed dark steel plates, pipes, corrugated and blue/green painted metal, plank floors and fences, brick
walls, grass lids, plaster panels and road lids all tagged concrete or wood, plus posters/graffiti that
should be left alone. `tools/photo_label_fixes.json` holds the hand corrections (`ste` 202, `bil` 217
tiles; `{style: {tile: class}}`); `photoreal_tiles.py build --fixes tools/photo_label_fixes.json
--tiles <those tiles>` applies them (a tile fixed to `skip` has its photo tile removed, so the renderer
falls back to the HD tile). Result: Residential 725 and Industrial 802 photo tiles (25 and 9 corrected to
skip). Tile-level before/after (HD | old label | fixed label) confirms the change is where expected, e.g. blue
planked metal gets metal grain instead of concrete pores, plaster panels get plaster. The effect stays
subtle by design (grain only). The corrected tiles are in the local `assets/textures_hd/photo/` and ship in
the textures archive; they are not committed. Labels not reviewed: `paving`, `stone`, `brick`, `asphalt`
and `skip` lists.

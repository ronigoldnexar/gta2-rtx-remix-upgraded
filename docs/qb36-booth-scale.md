# QB-36: phone booth at human scale

Quality-bar row 36 ("Phone booth: oversized box and PHONE sign"). 9 Nov 2026, agent QB-36-BOOTH.

## Cause

`dll/src/map_objects.cpp` fits every standing code object onto the game's sprite quad: the
model's longest footprint edge is scaled to the quad's longer edge. The pay phone's quad is
0.50 x 0.47 blocks, so whatever the generator authored, the booth came out half a block square
(1.9 m on the renderer's 0.46-block, 1.75 m person) with a 1.4 m PHONE sign; the committed model
was drawn at scale 0.91 (0.55 m roof overhang onto the 0.50 quad).

## Change

- `tools/gen_code_objects.py build_phone`: the booth in real proportions (a metre is 0.263
  blocks): 0.95 m square (0.25 blocks), 2.24 m to the roof (0.59), PHONE sign box 0.65 x 0.17 m
  on top (2.47 m overall). Posts, panels, the pay phone (23 x 50 x 11 cm, face at 1.03-1.52 m),
  shelf and handset resized to match. Same parts, same triangle counts (242 + 46 lit + 48 glass).
- `objects_anim` value `"authored"` (manifest, `4:510-512`): the renderer draws the model at
  scale 1 (its authored size in blocks) instead of stretching it onto the quad, and uses the
X
- Meshes re-imported with `tools/import_assets.py` (only the nine `code_phone*` meshes changed;
  the textures are byte-identical). The manifest entries were added by hand: the assets-src
  manifest has drifted from the committed one, so a full import would rewrite unrelated entries.

## Verified

Same script, same spot (Downtown spawn booth, map 158.5,137.5), committed stage vs this change:
`linux/docker/qb36_booth.py` (keys `keys_qb36_booth.sh`; run with `GTA2_DIRECT_KEYS=1`,
`INI_SED` setting `scene_key=F10`, `-e GTA2DX9_SCENE_NO_CAR=1`). Runs `qb36_before2` /
`qb36_after2`, sheet `out/qb36_booth_scale_sheet.png`.

- Classic: the game's own sprite, unchanged.
- Third person, about 1.2 blocks off: a pedestrian at the booth's depth is ~130 px tall, the
  booth with its sign ~178 px (ratio 1.37; designed 0.65 / 0.46 = 1.41). Before: a box as wide
  as it is tall.
- First person in front of it: an upright booth with the keypad, handset and PHONE sign in
  proportion; before, the back wall filled the frame.
- Log: `object fit: code_phone... scale 1.00`, 0 FAULT lines.

Not verified: the booth in Residential and Industrial and at night (same model, same code
path); the player answering a ringing phone from inside the smaller booth (game logic is not
touched, but the chase camera inside a 0.25-block booth was not framed); Remix (the booth's
Remix replacement, if any, is keyed by mesh hash and the mesh changed).
The `beside` third-person frame did not frame the player and the booth together (the chase
camera looked at the wall), so the side-by-side scale read comes from a pedestrian instead.

# PROPS-SLIM: street furniture without the triangle bloat (9 Nov 2026)

Wave B row PROPS-SLIM (`docs/STATUS-2026-11-08.md`). Goal: street furniture that reads right in
the street views without bloating the scene.

## What changed

- **Street lamp rebuilt**: 30 610 triangles down to 1 656 (`tools/gen_objects.py` `build_lamp`). The
  Poly Haven post (30 050 triangles of cast-iron ornament) is now a surface of revolution about its
  axis (base, shaft, collars, lantern dish and roof, 37 profile points x 14 segments), a second one
  about x for the cross-bar, and four bars for the lantern's corner posts. Between the dish and the roof
  the lathe drops to a thin stem, so the glass stays visible and is not walled in. The scan's glass is
  kept as it was (336 triangles, same texture bytes as before, so the Remix hash does not change).
  The bulb moved onto a flat patch of the atlas, so the lamp is still two draws (atlas, glass).
  Sheet (offline renderer): before/after from two sides, silhouette and lantern kept.
- **Hydrant and bin** (rebuilt earlier, PROPS-3, partly committed in `76569af`): their atlases
  `fire_hydrant_0.tga` and `trash_can_0.tga` were never committed, and neither was `obj_girder_2.tga`
  (the girder plate's 8x8 rivet colour). All three meshes in git pointed at textures that only existed
  in the working tree. They are committed now, so a fresh checkout or restage gets textured props.
- **Manifests**: `assets/manifest.json` now points `street_lamp`, `fire_hydrant` and `trash_can` at
  the slim GLBs (it still pointed hydrant and bin at the raw scans); `assets/models/manifest.json`
  has the new lamp's import record. The obsolete `street_lamp_3.tga` is removed.
- **In-game count** (`DrawProps`, `dll/src/live_geometry.cpp`): every 300 drawn frames the log has
  `props drawn: per frame <in range>, <drawn> (max), <triangles> (max), <draws>; drawn by kind
  lamp bin bench hydrant tree other`. "Drawn" means after the frustum cull.

## Verification (in game, Downtown, third person, standing 11 s at three spots)

Probe: `gamerun/props_slim.py` (`keys_props_slim.sh`), run as
`GTA2_DIRECT_KEYS=1 FPS=0 STAGE=<stage> INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/'
gamerun/grun.sh <run> 200 keys_props_slim.sh -e GTA2DX9_SCENE_NO_CAR=1`. Both runs used the same DLL
(HEAD plus the counter) and differed only in the lamp files (old lamp vs new lamp).

| log window covering the stand at the "scene" spot (164.5,149.5) and the look round after it | lamps drawn | props drawn | prop triangles / frame | draws |
|---|---|---|---|---|
| before (old lamp) | 32.3 | 93.8 | 1 014 513 (max 1 068 670) | 200 |
| after (slim lamp; two windows) | 33.0-33.7 | 100.8-101.8 | 86 789-87 747 (max 100 958) | 212-214 |

The lamps were ~97% of the prop triangles. Now the furniture as a whole is ~88k triangles a
frame. Breakdown after: lamps 33 x 1 656 = 55k, hydrants 14 x 1 184 = 17k, bins 10 x 772 = 8k,
benches 7 x 630 = 4k, the rest (meters, signs, mailboxes, trees) about 5k.

At the shop spot the third-person camera faces the shop front, so about 3 props are drawn there in both runs.

Frames: `t_ps_{shop,scene,booth}_{third,third_l,third_r,first}.png` in both runs. The lamps, the
hydrant and the meter look the same at street distance. One booth frame shows WASTED because a
passing car ran the player over, which has nothing to do with the props.

Frame times (indicative only: the host load was not the same in the two runs): during the stands,
`sprites` (which includes props) was 8.5-15 ms on average before and 3.7-7.3 ms after, and the frame
wait (headroom under the 30 fps cap) was 0.2-8 ms before and 16-21 ms after.

## Not verified / open

- Remix: the lamp atlas `street_lamp_0.tga` is new, and so are the hydrant and bin atlases. No PBR
  replacement exists for them in `package/rtx-remix/mods/gta2hd` until `tools/remix_model_pbr.py` is
  rerun. The glass hash did not change. No Remix frame was taken.
- The lamp could drop to ~1 000 triangles (10 segments, scan glass rebuilt as 4 panes), or get a
  distance LOD. Not done, because draws (2 per lamp), not triangles, now dominate the prop cost.
- Bench (630) and drum/tyre/planter map objects (1.4k-4k) are drawn far less often and were left alone.
